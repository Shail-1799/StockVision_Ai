"""Orchestrates the full pipeline for one uploaded file:
enhance -> (pdf split) -> Groq vision extraction -> validate -> persist.
Nothing is overwritten; every upload creates new Image/Order/MissingProduct rows.
"""
from pathlib import Path
from datetime import datetime

from database.db import session_scope
from database.models import ImageRecord, OrderRecord, MissingProduct
from services.image_enhance import enhance_image
from services.pdf_utils import pdf_to_images
from services.rotation import correct_orientation, rotate_90_steps
from services.groq_vision import extract_document, GroqVisionError
from services.validator import validate_row

DEFAULT_Retailer = "Unknown Retailer"


def process_upload(filepath: str, retailer_name: str = "") -> dict:
    """Handles a single uploaded image OR pdf. `retailer_name` is the value
    typed by the user on the Upload page, if any - leave it blank/None to
    have the retailer auto-extracted from each image instead. Returns a
    summary dict."""
    filepath = Path(filepath)
    summary = {"images_created": 0, "rows_found": 0, "errors": []}

    if filepath.suffix.lower() == ".pdf":
        page_paths = pdf_to_images(str(filepath))
    else:
        page_paths = [str(filepath)]

    for page_path in page_paths:
        result = _process_single_image(
            page_path, (retailer_name or "").strip(), original_name=filepath.name
        )
        summary["images_created"] += 1
        summary["rows_found"] += result["rows_found"]
        if result["error"]:
            summary["errors"].append(result["error"])

    return summary


def _process_single_image(image_path: str, manual_retailer_name: str, original_name: str) -> dict:
    # Placeholder retailer until extraction runs (or the manual override if given).
    placeholder_retailer = manual_retailer_name or DEFAULT_Retailer

    with session_scope() as s:
        image = ImageRecord(
            filename=original_name,
            filepath=str(image_path),
            retailer_name=placeholder_retailer,
            upload_date=datetime.utcnow(),
            processing_status="processing",
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

    rows_found = 0
    error = None
    try:
        enhanced_path = enhance_image(image_path)
        straightened_path = correct_orientation(enhanced_path)
        doc = extract_document(straightened_path)

        # Rare case: EXIF didn't fix it and the sheet was genuinely
        # photographed sideways/upside-down. The model told us so on the
        # same call - rotate locally (free) and read it again properly.
        # This only fires occasionally, so it doesn't affect the typical
        # per-image request budget.
        if doc["rotate_clockwise_degrees"]:
            rotated_path = rotate_90_steps(straightened_path, doc["rotate_clockwise_degrees"])
            doc = extract_document(rotated_path)

        # Retailer: the manual field on the Upload page is an override - if
        # the user left it blank, use whatever the vision model read off the
        # sheet itself, falling back to "Unknown Retailer" if neither is set.
        final_retailer = manual_retailer_name or doc["retailer_name"] or DEFAULT_Retailer
        order_date = doc["order_date"]

        with session_scope() as s:
            img = s.get(ImageRecord, image_id)
            img.retailer_name = final_retailer
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

    return {"rows_found": rows_found, "error": error}
