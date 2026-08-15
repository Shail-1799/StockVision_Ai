from datetime import datetime
import pandas as pd

import config
from services.aggregator import get_aggregated_products
from database.db import session_scope
from database.models import MissingProduct, OrderRecord, ImageRecord


def export_to_excel() -> str:
    summary_rows = get_aggregated_products()
    summary_df = pd.DataFrame(
        [
            {
                "Product Alias": r["product_alias"],
                "Total Quantity": r["total_required_quantity"],
                "Times Missing": r["times_missing"],
                "Last Retailer": r["last_retailer"],
                "Last Seen": r["last_seen"],
            }
            for r in summary_rows
        ]
    )

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
                    "Quantity": mp.required_quantity,
                    "Date": mp.created_at,
                }
                for mp, o, img in detail_rows
            ]
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = config.EXPORTS_DIR / f"purchase_order_{timestamp}.xlsx"

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        (summary_df if not summary_df.empty else pd.DataFrame(columns=["Product Alias", "Total Quantity"])).to_excel(
            writer, sheet_name="Summary", index=False
        )
        (detail_df if not detail_df.empty else pd.DataFrame(columns=["Product Alias", "Retailer"])).to_excel(
            writer, sheet_name="Detailed History", index=False
        )

    return str(out_path)
