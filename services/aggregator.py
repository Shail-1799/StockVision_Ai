from datetime import datetime, timedelta
from sqlalchemy import func

from database.db import session_scope, get_setting
from database.models import MissingProduct, ImageRecord, OrderRecord, AppUser, ProductMaster

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

MANUAL_ENTRY_RETAILER = "Manual Entry"


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
                "uploaded_by": img.uploaded_by or "",
                "row_sr_no": mp.row_sr_no,
                "order_id": o.order_label or "",
                "order_date": o.order_date or "",
                "created_at": mp.created_at.strftime("%d %B %Y %H:%M:%S") if mp.created_at else "",
            }
            for mp, o, img in rows
        ]


def get_missing_product_with_image(row_id: int) -> dict | None:
    """One row plus enough context to render the side-by-side verify view:
    the source image path and the rest of that row's fields."""
    with session_scope() as s:
        result = (
            s.query(MissingProduct, OrderRecord, ImageRecord)
            .join(OrderRecord, MissingProduct.order_id == OrderRecord.id)
            .join(ImageRecord, MissingProduct.image_id == ImageRecord.id)
            .filter(MissingProduct.id == row_id)
            .first()
        )
        if not result:
            return None
        mp, o, img = result
        return {
            "id": mp.id,
            "product_alias": mp.product_alias,
            "required_quantity": mp.required_quantity,
            "row_sr_no": mp.row_sr_no,
            "raw_row_text": mp.raw_row_text,
            "ocr_confidence": mp.ocr_confidence,
            "cross_confidence": mp.cross_confidence,
            "status": mp.status,
            "retailer": o.retailer_name,
            "order_date": o.order_date or "",
            "filename": img.filename,
            "image_id": img.id,
            "uploaded_by": img.uploaded_by or "",
        }


def update_missing_product_field(row_id: int, field: str, value) -> tuple[bool, object]:
    """Used by every editable AG Grid in the app - persists a single cell
    edit. order_id / order_date are stored on the shared OrderRecord, so
    editing either one from any row updates it for every row from that same
    sheet. Returns (ok, previous_value) so callers can offer Undo."""
    if field in ORDER_LEVEL_FIELDS:
        with session_scope() as s:
            row = s.get(MissingProduct, row_id)
            if not row:
                return False, None
            order = s.get(OrderRecord, row.order_id)
            if not order:
                return False, None
            old_value = getattr(order, ORDER_LEVEL_FIELDS[field])
            setattr(order, ORDER_LEVEL_FIELDS[field], str(value or ""))
            return True, old_value

    if field not in EDITABLE_FIELDS:
        return False, None
    with session_scope() as s:
        row = s.get(MissingProduct, row_id)
        if not row:
            return False, None
        old_value = getattr(row, field)
        if field == "required_quantity":
            try:
                value = float(value)
            except (TypeError, ValueError):
                return False, None
        setattr(row, field, value)
        return True, old_value


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
            .filter(ImageRecord.retailer_name == MANUAL_ENTRY_RETAILER)
            .filter(ImageRecord.filename == "Manual Entry Log")
            .first()
        )
        if img:
            order = s.query(OrderRecord).filter(OrderRecord.image_id == img.id).first()
            return img.id, order.id

        img = ImageRecord(
            filename="Manual Entry Log",
            filepath="",
            retailer_name=MANUAL_ENTRY_RETAILER,
            processing_status="done",
        )
        s.add(img)
        s.flush()
        # order_label / order_date left blank ("") - manually entered rows
        # get no default Order ID or Order Date; the user types their own.
        order = OrderRecord(
            image_id=img.id,
            retailer_name=MANUAL_ENTRY_RETAILER,
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
    reorder_min_times = int(float(get_setting("reorder_alert_min_times", 3)))
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
                    "recurring": "🔥 Recurring" if times_missing >= reorder_min_times else "",
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
        failed_uploads = (
            s.query(func.count(ImageRecord.id))
            .filter(ImageRecord.processing_status == "failed")
            .scalar()
            or 0
        )

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
            "failed_uploads": failed_uploads,
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


def get_ocr_confidence_histogram() -> list[dict]:
    """Bucketed OCR confidence distribution, for a data-quality view."""
    with session_scope() as s:
        confs = [
            c for (c,) in s.query(MissingProduct.ocr_confidence).all() if c is not None
        ]
    buckets = ["0-0.5", "0.5-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"]
    counts = [0, 0, 0, 0, 0]
    for c in confs:
        if c < 0.5:
            counts[0] += 1
        elif c < 0.7:
            counts[1] += 1
        elif c < 0.8:
            counts[2] += 1
        elif c < 0.9:
            counts[3] += 1
        else:
            counts[4] += 1
    return [{"bucket": b, "count": c} for b, c in zip(buckets, counts)]


def get_reorder_alerts(min_times: int = None) -> list[dict]:
    """Products that have shown up as unavailable repeatedly, not just
    once - the real signal something needs restocking permanently rather
    than a one-off supply hiccup."""
    if min_times is None:
        min_times = int(float(get_setting("reorder_alert_min_times", 3)))
    return [r for r in get_aggregated_products() if r["times_missing"] >= min_times]


def get_retailer_reliability() -> list[dict]:
    """Per-retailer rollup: how many orders, how often something was
    unavailable, total shortage quantity, most recent order - useful for
    spotting which retailer to renegotiate with or move away from."""
    with session_scope() as s:
        orders = (
            s.query(
                OrderRecord.retailer_name,
                func.count(func.distinct(OrderRecord.id)).label("order_count"),
                func.max(OrderRecord.created_at).label("last_order"),
            )
            .join(ImageRecord, OrderRecord.image_id == ImageRecord.id)
            .filter(ImageRecord.processing_status == "done")
            .group_by(OrderRecord.retailer_name)
            .all()
        )
        shortages = dict(
            s.query(
                OrderRecord.retailer_name,
                func.count(MissingProduct.id),
            )
            .join(MissingProduct, MissingProduct.order_id == OrderRecord.id)
            .filter(MissingProduct.status == "accepted")
            .group_by(OrderRecord.retailer_name)
            .all()
        )
        shortage_qty = dict(
            s.query(
                OrderRecord.retailer_name,
                func.sum(MissingProduct.required_quantity),
            )
            .join(MissingProduct, MissingProduct.order_id == OrderRecord.id)
            .filter(MissingProduct.status == "accepted")
            .group_by(OrderRecord.retailer_name)
            .all()
        )

    results = []
    for retailer, order_count, last_order in orders:
        shortage_rows = shortages.get(retailer, 0) or 0
        results.append(
            {
                "retailer": retailer,
                "order_count": order_count,
                "shortage_rows": shortage_rows,
                "shortage_qty": round(shortage_qty.get(retailer, 0) or 0, 2),
                "shortage_rate_pct": round((shortage_rows / order_count) * 100, 1) if order_count else 0,
                "last_order": last_order.strftime("%d %B %Y") if last_order else "",
            }
        )
    results.sort(key=lambda r: r["shortage_qty"], reverse=True)
    return results


def get_user_activity() -> list[dict]:
    """Per-user upload counts - admin-only team activity view."""
    with session_scope() as s:
        rows = (
            s.query(
                ImageRecord.uploaded_by,
                func.count(ImageRecord.id).label("uploads"),
                func.sum(func.coalesce(ImageRecord.tokens_used, 0)).label("tokens"),
                func.max(ImageRecord.upload_date).label("last_upload"),
            )
            .filter(ImageRecord.uploaded_by.isnot(None))
            .filter(ImageRecord.uploaded_by != "")
            .group_by(ImageRecord.uploaded_by)
            .order_by(func.count(ImageRecord.id).desc())
            .all()
        )
        return [
            {
                "uploaded_by": r.uploaded_by,
                "uploads": r.uploads,
                "tokens_used": r.tokens or 0,
                "last_upload": r.last_upload.strftime("%d %B %Y %H:%M") if r.last_upload else "",
            }
            for r in rows
        ]


def get_groq_usage_today() -> dict:
    """Rough daily token-usage total - a cost/trend indicator, not a live
    per-minute quota gauge (Groq's limit is per-minute, this is per-day)."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as s:
        total = (
            s.query(func.sum(func.coalesce(ImageRecord.tokens_used, 0)))
            .filter(ImageRecord.upload_date >= today_start)
            .scalar()
            or 0
        )
        calls = (
            s.query(func.count(ImageRecord.id))
            .filter(ImageRecord.upload_date >= today_start)
            .scalar()
            or 0
        )
    return {"tokens_today": int(total), "uploads_today": calls}


def get_failed_images() -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(ImageRecord)
            .filter(ImageRecord.processing_status == "failed")
            .order_by(ImageRecord.upload_date.desc())
            .all()
        )
        return [
            {
                "id": img.id,
                "filename": img.filename,
                "retailer": img.retailer_name,
                "uploaded_by": img.uploaded_by or "",
                "upload_date": img.upload_date.strftime("%d %B %Y %H:%M") if img.upload_date else "",
                "error_message": img.error_message or "",
            }
            for img in rows
        ]


# --- Lightweight user list (no passwords - see AppUser docstring) ---

def get_users() -> list[dict]:
    with session_scope() as s:
        rows = s.query(AppUser).order_by(AppUser.name).all()
        return [{"name": u.name, "is_admin": u.is_admin} for u in rows]


def is_admin_user(name: str) -> bool:
    if not name:
        return False
    with session_scope() as s:
        u = s.get(AppUser, name)
        return bool(u and u.is_admin)


def add_user(name: str, is_admin: bool = False) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    with session_scope() as s:
        existing = s.get(AppUser, name)
        if existing:
            existing.is_admin = is_admin
        else:
            s.add(AppUser(name=name, is_admin=is_admin))
        return True


def remove_user(name: str) -> bool:
    with session_scope() as s:
        u = s.get(AppUser, name)
        if not u:
            return False
        s.delete(u)
        return True
