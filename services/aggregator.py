from datetime import datetime
from sqlalchemy import func

from database.db import session_scope
from database.models import MissingProduct, ImageRecord, OrderRecord

EDITABLE_FIELDS = {
    "product_alias",
    "required_quantity",
    "row_sr_no",
}

# These live on OrderRecord, not MissingProduct - editing one row's value
# updates the shared order, so every other row from the same sheet reflects
# the change too.
ORDER_LEVEL_FIELDS = {
    "order_id": "order_label",
    "order_date": "order_date",
}

MANUAL_ENTRY_Retailer = "Manual Entry"


def get_all_missing_products() -> list[dict]:
    """Every row from every order, any status - the 'spreadsheet' view."""
    with session_scope() as s:
        rows = (
            s.query(MissingProduct, OrderRecord, ImageRecord)
            .join(OrderRecord, MissingProduct.order_id == OrderRecord.id)
            .join(ImageRecord, MissingProduct.image_id == ImageRecord.id)
            .order_by(MissingProduct.created_at.desc())
            .all()
        )
        return [
            {
                "id": mp.id,
                "product_alias": mp.product_alias,
                "required_quantity": mp.required_quantity,
                "retailer": o.retailer_name,
                "filename": img.filename,
                "row_sr_no": mp.row_sr_no,
                "order_id": o.order_label or "",
                "order_date": o.order_date or "",
                "created_at": mp.created_at.strftime("%d %B %Y %H:%M:%S") if mp.created_at else "",
            }
            for mp, o, img in rows
        ]


def update_missing_product_field(row_id: int, field: str, value) -> bool:
    """Used by every editable AG Grid in the app - persists a single cell edit.
    order_id / order_date are stored on the shared OrderRecord, so editing
    either one from any row updates it for every row from that same sheet."""
    if field in ORDER_LEVEL_FIELDS:
        with session_scope() as s:
            row = s.get(MissingProduct, row_id)
            if not row:
                return False
            order = s.get(OrderRecord, row.order_id)
            if not order:
                return False
            setattr(order, ORDER_LEVEL_FIELDS[field], str(value or ""))
            return True

    if field not in EDITABLE_FIELDS:
        return False
    with session_scope() as s:
        row = s.get(MissingProduct, row_id)
        if not row:
            return False
        if field == "required_quantity":
            try:
                value = float(value)
            except (TypeError, ValueError):
                return False
        setattr(row, field, value)
        return True


def delete_missing_products(row_ids: list[int]) -> int:
    if not row_ids:
        return 0
    with session_scope() as s:
        count = (
            s.query(MissingProduct)
            .filter(MissingProduct.id.in_(row_ids))
            .delete(synchronize_session=False)
        )
        return count


def get_or_create_manual_source() -> tuple[int, int]:
    """One persistent pseudo image/order that all manually-typed rows attach
    to, so they show up in Orders/history without needing a real photo."""
    with session_scope() as s:
        img = (
            s.query(ImageRecord)
            .filter(ImageRecord.retailer_name == MANUAL_ENTRY_Retailer)
            .filter(ImageRecord.filename == "Manual Entry Log")
            .first()
        )
        if img:
            order = s.query(OrderRecord).filter(OrderRecord.image_id == img.id).first()
            return img.id, order.id

        img = ImageRecord(
            filename="Manual Entry Log",
            filepath="",
            retailer_name=MANUAL_ENTRY_Retailer,
            processing_status="done",
        )
        s.add(img)
        s.flush()
        # order_label / order_date left blank ("") - manually entered rows
        # get no default Order ID or Order Date; the user types their own.
        order = OrderRecord(
            image_id=img.id,
            retailer_name=MANUAL_ENTRY_Retailer,
            order_label="",
            order_date="",
        )
        s.add(order)
        s.flush()
        return img.id, order.id


def add_manual_row(product_alias: str = "NEW-ITEM", required_quantity: float = 0) -> int:
    """Adds a blank/default editable row a user can then fill in like Excel."""
    image_id, order_id = get_or_create_manual_source()
    with session_scope() as s:
        row = MissingProduct(
            order_id=order_id,
            image_id=image_id,
            product_alias=product_alias,
            required_quantity=required_quantity,
            row_sr_no="",
            raw_row_text="Manually entered",
            ocr_confidence=1.0,
            cross_confidence=1.0,
            status="accepted",
        )
        s.add(row)
        s.flush()
        return row.id


def get_aggregated_products(status="accepted") -> list[dict]:
    """Group accepted rows by product_alias, summing quantity across all uploads."""
    with session_scope() as s:
        q = (
            s.query(
                MissingProduct.product_alias,
                func.sum(MissingProduct.required_quantity).label("total_qty"),
                func.count(MissingProduct.id).label("times_missing"),
                func.max(MissingProduct.created_at).label("last_seen"),
            )
            .filter(MissingProduct.status == status)
            .group_by(MissingProduct.product_alias)
            .order_by(func.sum(MissingProduct.required_quantity).desc())
        )
        results = []
        for alias, total_qty, times_missing, last_seen in q.all():
            last_retailer = (
                s.query(OrderRecord.retailer_name)
                .join(MissingProduct, MissingProduct.order_id == OrderRecord.id)
                .filter(MissingProduct.product_alias == alias, MissingProduct.status == status)
                .order_by(MissingProduct.created_at.desc())
                .first()
            )
            results.append(
                {
                    "product_alias": alias,
                    "total_required_quantity": total_qty or 0,
                    "times_missing": times_missing,
                    "last_seen": last_seen,
                    "last_retailer": last_retailer[0] if last_retailer else "",
                }
            )
        return results


def get_product_history(product_alias: str) -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(MissingProduct, OrderRecord)
            .join(OrderRecord, MissingProduct.order_id == OrderRecord.id)
            .filter(MissingProduct.product_alias == product_alias)
            .order_by(MissingProduct.created_at.desc())
            .all()
        )
        return [
            {
                "retailer": o.retailer_name,
                "order_id": o.id,
                "image_id": mp.image_id,
                "quantity": mp.required_quantity,
                "status": mp.status,
                "date": mp.created_at,
            }
            for mp, o in rows
        ]


def get_review_queue() -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(MissingProduct, ImageRecord)
            .join(ImageRecord, MissingProduct.image_id == ImageRecord.id)
            .filter(MissingProduct.status == "pending")
            .order_by(MissingProduct.created_at.desc())
            .all()
        )
        return [
            {
                "id": mp.id,
                "product_alias": mp.product_alias,
                "required_quantity": mp.required_quantity,
                "ocr_confidence": mp.ocr_confidence,
                "cross_confidence": mp.cross_confidence,
                "raw_row_text": mp.raw_row_text,
                "retailer": img.retailer_name,
                "filename": img.filename,
            }
            for mp, img in rows
        ]


def review_action(row_id: int, action: str, edited_alias: str = None, edited_qty: float = None):
    """action: 'accept' | 'edit' | 'reject'"""
    with session_scope() as s:
        row = s.get(MissingProduct, row_id)
        if not row:
            return False
        if action == "reject":
            row.status = "rejected"
        elif action == "accept":
            row.status = "accepted"
        elif action == "edit":
            if edited_alias:
                row.product_alias = edited_alias
            if edited_qty is not None:
                row.required_quantity = edited_qty
            row.status = "accepted"
        return True


def get_dashboard_stats() -> dict:
    with session_scope() as s:
        images_uploaded = s.query(func.count(ImageRecord.id)).scalar() or 0
        orders_processed = (
            s.query(func.count(ImageRecord.id))
            .filter(ImageRecord.processing_status == "done")
            .scalar()
            or 0
        )
        missing_products = (
            s.query(func.count(func.distinct(MissingProduct.product_alias)))
            .filter(MissingProduct.status == "accepted")
            .scalar()
            or 0
        )
        total_missing_qty = (
            s.query(func.sum(MissingProduct.required_quantity))
            .filter(MissingProduct.status == "accepted")
            .scalar()
            or 0
        )
        all_rows = s.query(func.count(MissingProduct.id)).scalar() or 0
        avg_ocr_conf = s.query(func.avg(MissingProduct.ocr_confidence)).scalar() or 0

        return {
            "images_uploaded": images_uploaded,
            "orders_processed": orders_processed,
            "missing_products": missing_products,
            "total_missing_qty": round(total_missing_qty, 2),
            "ocr_accuracy_pct": round((avg_ocr_conf or 0) * 100, 1),
            "pending_review": s.query(func.count(MissingProduct.id))
            .filter(MissingProduct.status == "pending")
            .scalar()
            or 0,
            "total_rows_extracted": all_rows,
        }


def get_daily_trend() -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(
                func.date(MissingProduct.created_at).label("day"),
                func.sum(MissingProduct.required_quantity).label("qty"),
            )
            .filter(MissingProduct.status == "accepted")
            .group_by(func.date(MissingProduct.created_at))
            .order_by(func.date(MissingProduct.created_at))
            .all()
        )
        return [{"day": r.day, "qty": r.qty or 0} for r in rows]


def get_retailer_distribution() -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(
                OrderRecord.retailer_name,
                func.sum(MissingProduct.required_quantity).label("qty"),
            )
            .join(MissingProduct, MissingProduct.order_id == OrderRecord.id)
            .filter(MissingProduct.status == "accepted")
            .group_by(OrderRecord.retailer_name)
            .all()
        )
        return [{"retailer": r.retailer_name, "qty": r.qty or 0} for r in rows]


def get_top_missing_products(limit: int = 10) -> list[dict]:
    return get_aggregated_products()[:limit]
