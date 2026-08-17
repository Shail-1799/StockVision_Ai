"""Orchestrates the full pipeline for one uploaded file:
dedup check -> enhance -> quality check -> (pdf split) -> Groq vision
extraction -> validate -> persist.
"""
from pathlib import Path
from datetime import datetime

from database.db import session_scope
from database.models import ImageRecord, OrderRecord, MissingProduct
from services.image_enhance import enhance_image, check_image_quality
from services.pdf_utils import pdf_to_images
from services.rotation import correct_orientation, rotate_90_steps
from services.groq_vision import extract_document, GroqVisionError
from services.validator import validate_row
from services.dedup import sha256_of_file, dhash, is_near_duplicate

DEFAULT_RETAILER = "Unknown Retailer"


def process_upload(filepath: str, retailer_name: str = "", uploaded_by: str = "") -> dict:
    """Handles a single uploaded image OR pdf. `retailer_name` is the value
    typed by the user on the Upload page, if any - leave it blank/None to
    have the retailer auto-extracted from each image instead. `uploaded_by`
    is the name picked in the navbar. Returns a summary dict."""
    filepath = Path(filepath)
    summary = {"images_created": 0, "rows_found": 0, "errors": [], "duplicates": [], "quality_rejects": []}

    if filepath.suffix.lower() == ".pdf":
        page_paths = pdf_to_images(str(filepath))
    else:
        page_paths = [str(filepath)]

    for page_path in page_paths:
        result = _process_single_image(
            page_path,
            (retailer_name or "").strip(),
            original_name=filepath.name,
            uploaded_by=(uploaded_by or "").strip(),
        )
        if result.get("duplicate"):
            summary["duplicates"].append(result["duplicate"])
            continue
        if result.get("quality_reject"):
            summary["quality_rejects"].append(result["error"])
            continue
        summary["images_created"] += 1
        summary["rows_found"] += result["rows_found"]
        if result["error"]:
            summary["errors"].append(result["error"])

    return summary


def _find_duplicate(original_path: str, enhanced_path: str):
    """Checks the two-layer dedup rule (see services/dedup.py) against every
    previously SUCCESSFULLY processed image. Returns (duplicate_info_or_None,
    content_hash, phash) - the hashes are returned either way so the caller
    can store them on the new record even when there's no match."""
    content_hash = sha256_of_file(original_path)
    incoming_phash = None
    try:
        incoming_phash = dhash(enhanced_path)
    except Exception:
        pass

    with session_scope() as s:
        exact = (
            s.query(ImageRecord)
            .filter(ImageRecord.content_hash == content_hash)
            .filter(ImageRecord.processing_status == "done")
            .first()
        )
        if exact:
            return (
                {
                    "filename": exact.filename,
                    "uploaded_by": exact.uploaded_by or "",
                    "upload_date": exact.upload_date,
                    "match_type": "exact",
                },
                content_hash,
                incoming_phash,
            )

        if incoming_phash:
            candidates = (
                s.query(ImageRecord)
                .filter(ImageRecord.processing_status == "done")
                .filter(ImageRecord.phash.isnot(None))
                .all()
            )
            for c in candidates:
                if is_near_duplicate(incoming_phash, c.phash):
                    return (
                        {
                            "filename": c.filename,
                            "uploaded_by": c.uploaded_by or "",
                            "upload_date": c.upload_date,
                            "match_type": "near",
                        },
                        content_hash,
                        incoming_phash,
                    )

    return None, content_hash, incoming_phash


def _process_single_image(image_path: str, manual_retailer_name: str, original_name: str, uploaded_by: str) -> dict:
    # Local, free checks BEFORE any DB rows are created and BEFORE any Groq
    # call is spent: duplicate detection, then image quality.
    enhanced_path = enhance_image(image_path)

    duplicate, content_hash, incoming_phash = _find_duplicate(image_path, enhanced_path)
    if duplicate:
        return {"rows_found": 0, "error": None, "duplicate": duplicate}

    is_blurry, blur_msg, _score = check_image_quality(enhanced_path)
    if is_blurry:
        return {"rows_found": 0, "error": blur_msg, "duplicate": None, "quality_reject": True}

    # Placeholder retailer until extraction runs (or the manual override if given).
    placeholder_retailer = manual_retailer_name or DEFAULT_RETAILER

    with session_scope() as s:
        image = ImageRecord(
            filename=original_name,
            filepath=str(image_path),
            display_path=enhanced_path,
            retailer_name=placeholder_retailer,
            upload_date=datetime.utcnow(),
            processing_status="processing",
            uploaded_by=uploaded_by,
            content_hash=content_hash,
            phash=incoming_phash,
        )
        s.add(image)
        s.flush()  # get image.id

        order = OrderRecord(image_id=image.id, retailer_name=placeholder_retailer)
        s.add(order)
        s.flush()
        image_id, order_id = image.id, order.id
        # Default Order ID label = the order's own numeric id, so every row
        # extracted from this image shares the same label out of the box.
        order.order_label = str(order.id)

    result = _run_extraction(enhanced_path, manual_retailer_name, image_id, order_id)
    return result


def _run_extraction(enhanced_path: str, manual_retailer_name: str, image_id: int, order_id: int) -> dict:
    """The Groq call + persistence step, shared by a fresh upload and a
    manual retry of a previously failed one. `enhanced_path` should already
    be the enhanced (and, for a retry, previously-deskewed) image."""
    rows_found = 0
    error = None
    total_tokens = 0
    try:
        straightened_path = correct_orientation(enhanced_path)
        doc = extract_document(straightened_path)
        total_tokens += doc.get("tokens_used", 0)

        # Rare case: EXIF didn't fix it and the sheet was genuinely
        # photographed sideways/upside-down. The model told us so on the
        # same call - rotate locally (free) and read it again properly.
        # This only fires occasionally, so it doesn't affect the typical
        # per-image request budget.
        if doc["rotate_clockwise_degrees"]:
            rotated_path = rotate_90_steps(straightened_path, doc["rotate_clockwise_degrees"])
            doc = extract_document(rotated_path)
            total_tokens += doc.get("tokens_used", 0)
            straightened_path = rotated_path

        # Retailer: the manual field on the Upload page is an override - if
        # the user left it blank, use whatever the vision model read off the
        # sheet itself, falling back to "Unknown Retailer" if neither is set.
        final_retailer = manual_retailer_name or doc["retailer_name"] or DEFAULT_RETAILER
        order_date = doc["order_date"]

        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            img.retailer_name = final_retailer
            img.display_path = straightened_path
            img.tokens_used = (img.tokens_used or 0) + total_tokens
            ordr = s.get(OrderRecord, order_id)
            ordr.retailer_name = final_retailer
            ordr.order_date = order_date

        for row in doc["rows"]:
            row = validate_row(row)
            with session_scope() as s:
                s.add(
                    MissingProduct(
                        order_id=order_id,
                        image_id=image_id,
                        product_alias=row["product_alias"],
                        required_quantity=row["required_quantity"],
                        row_sr_no=row["row_sr_no"],
                        raw_row_text=row["raw_row_text"],
                        ocr_confidence=row["ocr_confidence"],
                        cross_confidence=row["cross_confidence"],
                        status=row["status"],
                    )
                )
            rows_found += 1

        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            img.processing_status = "done"

    except GroqVisionError as e:
        error = str(e)
        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            img.processing_status = "failed"
            img.error_message = error
    except Exception as e:
        error = f"Unexpected error: {e}"
        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            img.processing_status = "failed"
            img.error_message = error

    return {"rows_found": rows_found, "error": error, "duplicate": None}


def retry_failed_image(image_id: int) -> dict:
    """Re-runs extraction on an image that previously failed, reusing its
    already-saved file (no re-upload needed). Clears any partial rows left
    over from the failed attempt first."""
    with session_scope() as s:
        img = s.get(ImageRecord, image_id)
        if not img:
            return {"error": "Image not found", "rows_found": 0}
        enhanced_path = img.display_path or img.filepath
        manual_retailer = "" if img.retailer_name in ("", DEFAULT_RETAILER) else img.retailer_name
        order = s.query(OrderRecord).filter(OrderRecord.image_id == image_id).first()
        order_id = order.id if order else None

    if not order_id:
        return {"error": "No order record found for this image", "rows_found": 0}

    with session_scope() as s:
        s.query(MissingProduct).filter(MissingProduct.order_id == order_id).delete(synchronize_session=False)
        img = s.get(ImageRecord, image_id)
        img.processing_status = "processing"
        img.error_message = None

    # Re-run enhancement from the original file in case display_path went missing.
    with session_scope() as s:
        img = s.get(ImageRecord, image_id)
        source_path = img.filepath

    try:
        enhanced_path = enhance_image(source_path)
    except Exception:
        pass  # fall back to whatever enhanced_path we already had

    return _run_extraction(enhanced_path, manual_retailer, image_id, order_id)
