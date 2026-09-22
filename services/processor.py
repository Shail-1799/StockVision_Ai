"""Orchestrates the full pipeline for one uploaded file:
dedup check -> enhance -> quality check -> (pdf split) -> Groq vision
extraction -> validate -> persist.

--- Why extraction runs in a background thread ---
The Groq call chain (extraction, sometimes a second call for a rotated
photo, sometimes rate-limit retries with backoff) can take anywhere from a
couple seconds to over a minute in a bad case. Running that INSIDE the HTTP
request the browser is waiting on means the request's total duration is
however long Groq happens to take that time - and on a small hosting tier,
that can exceed the platform's own reverse-proxy timeout (which no amount
of gunicorn --timeout tuning can override), surfacing as a 502 the user
never gets an explanation for. It's also the reason mobile uploads could
look like "nothing happens": the browser is just waiting on a slow request,
often over a slower connection than a desk.

So the split here is deliberate: process_upload() does only the FAST, local
work synchronously (dedup hash check, blur check, DB record creation - all
comfortably sub-second even on a fraction of a CPU core) and hands the slow
part to a small bounded thread pool, returning to the caller almost
immediately with a "queued" status instead of the final result. The Upload
page polls image_id statuses afterward (see pages/upload.py) instead of
waiting on the original request.

SQLAlchemy's scoped_session (see database/db.py) is keyed by thread ID by
default, so each background thread automatically gets its own DB session -
no special handling needed for that here.
"""
import gc
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta

from database.db import session_scope
from database.models import ImageRecord, OrderRecord, MissingProduct
from services.image_enhance import enhance_image, check_image_quality
from services.pdf_utils import pdf_to_images
from services.rotation import correct_orientation, rotate_90_steps
from services.groq_vision import extract_document, GroqVisionError
from services.validator import validate_row
from services.dedup import sha256_of_file, dhash, is_near_duplicate

logger = logging.getLogger(__name__)

DEFAULT_RETAILER = "Unknown Retailer"
# An image stuck in "processing" longer than this was almost certainly
# abandoned by a crashed/OOM-killed worker mid-request, not genuinely still
# working. Swept to "failed" on the next process_upload call so it (a) stops
# being invisible to duplicate detection and (b) shows up in the Orders
# "Retry" panel instead of silently blocking that image forever.
STALE_PROCESSING_MINUTES = 10

# Bounded concurrency for the slow part (Groq calls). Deliberately small -
# this is a single 512MB/0.1-vCPU instance; a handful of photos uploaded at
# once should queue behind each other rather than all fight for the same
# thin CPU slice simultaneously, which would just make every one of them
# slower. Two lets one person's retry not block behind someone else's whole
# batch, without over-committing the box.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="extraction")


def _sweep_stale_processing():
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_MINUTES)
    with session_scope() as s:
        stale = (
            s.query(ImageRecord)
            .filter(ImageRecord.processing_status == "processing")
            .filter(ImageRecord.upload_date < cutoff)
            .all()
        )
        for img in stale:
            img.processing_status = "failed"
            img.error_message = (
                "Processing didn't finish (likely a server restart or memory limit "
                "mid-upload). Use Retry on the Orders page to try again."
            )


def process_upload(filepath: str, retailer_name: str = "", uploaded_by: str = "") -> dict:
    """Handles a single uploaded image OR pdf. Returns FAST (no waiting on
    Groq) - image_id's for anything that passed the local checks are queued
    for background extraction; poll them with get_image_status(). `duplicates`
    and `quality_rejects` are resolved immediately since those checks are
    local and instant."""
    _sweep_stale_processing()

    filepath = Path(filepath)
    summary = {
        "queued": [],  # [{"image_id":..., "filename":...}] - still processing, poll for outcome
        "duplicates": [],
        "quality_rejects": [],
        "errors": [],  # immediate failures (e.g. a corrupt/unreadable file) - resolved synchronously
    }

    try:
        if filepath.suffix.lower() == ".pdf":
            page_paths = pdf_to_images(str(filepath))
        else:
            page_paths = [str(filepath)]
    except Exception as e:
        summary["errors"].append(f"Could not read this file: {e}")
        return summary

    for page_path in page_paths:
        result = _prepare_image(
            page_path,
            (retailer_name or "").strip(),
            original_name=filepath.name,
            uploaded_by=(uploaded_by or "").strip(),
        )
        if result.get("duplicate"):
            summary["duplicates"].append(result["duplicate"])
        elif result.get("quality_reject"):
            summary["quality_rejects"].append(result["error"])
        elif result.get("error"):
            summary["errors"].append(result["error"])
        else:
            summary["queued"].append({"image_id": result["image_id"], "filename": filepath.name})
        gc.collect()

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


def _prepare_image(image_path: str, manual_retailer_name: str, original_name: str, uploaded_by: str) -> dict:
    """The FAST synchronous part: local checks + record creation. On
    success, submits the slow extraction to the background thread pool and
    returns immediately with the new image_id - it does NOT wait for
    extraction to finish."""
    try:
        enhanced_path = enhance_image(image_path)
    except Exception as e:
        return {"error": f"Could not read this image: {e}"}

    duplicate, content_hash, incoming_phash = _find_duplicate(image_path, enhanced_path)
    if duplicate:
        return {"duplicate": duplicate}

    is_blurry, blur_msg, _score = check_image_quality(enhanced_path)
    if is_blurry:
        return {"quality_reject": True, "error": blur_msg}

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
        s.flush()

        order = OrderRecord(image_id=image.id, retailer_name=placeholder_retailer)
        s.add(order)
        s.flush()
        image_id, order_id = image.id, order.id
        order.order_label = str(order.id)

    _EXECUTOR.submit(_run_extraction_safe, enhanced_path, manual_retailer_name, image_id, order_id)
    return {"image_id": image_id}


def _run_extraction_safe(enhanced_path: str, manual_retailer_name: str, image_id: int, order_id: int):
    """Thread-pool entry point - _run_extraction already catches everything
    it knows about, but a background thread that raises is otherwise
    invisible (no request to show a traceback in), so this is a hard
    backstop that guarantees the image never gets stuck at "processing"
    even if something truly unexpected happens."""
    try:
        _run_extraction(enhanced_path, manual_retailer_name, image_id, order_id)
    except Exception as e:
        logger.exception("Background extraction crashed for image_id=%s", image_id)
        try:
            with session_scope() as s:
                img = s.get(ImageRecord, image_id)
                if img and img.processing_status == "processing":
                    img.processing_status = "failed"
                    img.error_message = f"Unexpected background error: {e}"
        except Exception:
            pass


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
        if doc["rotate_clockwise_degrees"]:
            rotated_path = rotate_90_steps(straightened_path, doc["rotate_clockwise_degrees"])
            doc = extract_document(rotated_path)
            total_tokens += doc.get("tokens_used", 0)
            straightened_path = rotated_path

        final_retailer = manual_retailer_name or doc["retailer_name"] or DEFAULT_RETAILER
        order_date = doc["order_date"]

        validated_rows = [validate_row(row) for row in doc["rows"]]

        # Everything below is ONE transaction: every row plus the "done"
        # status flip commit together, or none of them do - a crash mid-loop
        # (OOM, restart) never leaves a half-written, dedup-invisible image.
        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            img.retailer_name = final_retailer
            img.display_path = straightened_path
            img.tokens_used = (img.tokens_used or 0) + total_tokens

            ordr = s.get(OrderRecord, order_id)
            ordr.retailer_name = final_retailer
            ordr.order_date = order_date

            for row in validated_rows:
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
    finally:
        gc.collect()

    return {"rows_found": rows_found, "error": error, "duplicate": None}


def get_image_status(image_id: int) -> dict | None:
    """Used by the Upload page's poller. Returns None if the image_id is
    somehow gone; otherwise the current status plus enough info to render a
    result once it's done/failed."""
    with session_scope() as s:
        img = s.get(ImageRecord, image_id)
        if not img:
            return None
        rows_found = 0
        if img.processing_status == "done":
            rows_found = (
                s.query(MissingProduct).filter(MissingProduct.image_id == image_id).count()
            )
        return {
            "image_id": image_id,
            "status": img.processing_status,  # "processing" | "done" | "failed"
            "filename": img.filename,
            "rows_found": rows_found,
            "error_message": img.error_message or "",
        }


def retry_failed_image(image_id: int) -> dict:
    """Re-runs extraction on an image that previously failed, reusing its
    already-saved file (no re-upload needed). Clears any partial rows left
    over from the failed attempt first. Also runs in the background thread
    pool and returns immediately - see module docstring."""
    with session_scope() as s:
        img = s.get(ImageRecord, image_id)
        if not img:
            return {"error": "Image not found"}
        manual_retailer = "" if img.retailer_name in ("", DEFAULT_RETAILER) else img.retailer_name
        source_path = img.filepath
        order = s.query(OrderRecord).filter(OrderRecord.image_id == image_id).first()
        order_id = order.id if order else None

    if not order_id:
        return {"error": "No order record found for this image"}

    with session_scope() as s:
        s.query(MissingProduct).filter(MissingProduct.order_id == order_id).delete(synchronize_session=False)
        img = s.get(ImageRecord, image_id)
        img.processing_status = "processing"
        img.error_message = None

    try:
        enhanced_path = enhance_image(source_path)
    except Exception:
        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            enhanced_path = img.display_path or img.filepath

    _EXECUTOR.submit(_run_extraction_safe, enhanced_path, manual_retailer, image_id, order_id)
    return {"queued": True}
