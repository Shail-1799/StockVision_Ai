import math
from datetime import datetime
import pandas as pd

import config
from services.aggregator import get_aggregated_products
from database.db import session_scope
from database.models import MissingProduct, OrderRecord, ImageRecord, ProductMaster


def _moq_lookup() -> dict:
    with session_scope() as s:
        return {
            row.product_alias: row.moq
            for row in s.query(ProductMaster.product_alias, ProductMaster.moq).all()
            if row.moq
        }


def export_to_excel() -> str:
    summary_rows = get_aggregated_products()
    moq_map = _moq_lookup()

    summary_records = []
    for r in summary_rows:
        moq = moq_map.get(r["product_alias"])
        order_qty = r["total_required_quantity"]
        moq_applied = False
        if moq and order_qty < moq:
            order_qty = math.ceil(moq)
            moq_applied = True
        summary_records.append(
            {
                "Product Alias": r["product_alias"],
                "Shortfall Quantity": r["total_required_quantity"],
                "Order Quantity (MOQ-adjusted)": order_qty,
                "MOQ Applied": "Yes" if moq_applied else "",
                "Times Missing": r["times_missing"],
                "Last Retailer": r["last_retailer"],
                "Last Seen": r["last_seen"],
            }
        )
    summary_df = pd.DataFrame(summary_records)

    with session_scope() as s:
        detail_rows = (
            s.query(MissingProduct, OrderRecord, ImageRecord)
            .join(OrderRecord, MissingProduct.order_id == OrderRecord.id)
            .join(ImageRecord, MissingProduct.image_id == ImageRecord.id)
            .filter(MissingProduct.status == "accepted")
            .order_by(MissingProduct.created_at.desc())
            .all()
        )
        detail_df = pd.DataFrame(
            [
                {
                    "Product Alias": mp.product_alias,
                    "Retailer": o.retailer_name,
                    "Order ID": o.id,
                    "Image ID": mp.image_id,
                    "Image Filename": img.filename,
                    "Uploaded By": img.uploaded_by or "",
                    "Quantity": mp.required_quantity,
                    "Date": mp.created_at,
                }
                for mp, o, img in detail_rows
            ]
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = config.EXPORTS_DIR / f"purchase_order_{timestamp}.xlsx"

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        (
            summary_df
            if not summary_df.empty
            else pd.DataFrame(columns=["Product Alias", "Order Quantity (MOQ-adjusted)"])
        ).to_excel(writer, sheet_name="Summary", index=False)
        (detail_df if not detail_df.empty else pd.DataFrame(columns=["Product Alias", "Retailer"])).to_excel(
            writer, sheet_name="Detailed History", index=False
        )

    return str(out_path)
