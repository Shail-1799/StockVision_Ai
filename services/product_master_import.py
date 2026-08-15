import pandas as pd

from database.db import session_scope
from database.models import ProductMaster

EXPECTED_COLS = {
    "product alias": "product_alias",
    "product name": "product_name",
    "brand": "brand",
    "category": "category",
    "mrp": "mrp",
    "current stock": "current_stock",
}


def import_product_master(filepath: str) -> dict:
    if filepath.lower().endswith(".csv"):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)

    df.columns = [c.strip().lower() for c in df.columns]
    rename_map = {c: EXPECTED_COLS[c] for c in df.columns if c in EXPECTED_COLS}
    df = df.rename(columns=rename_map)

    if "product_alias" not in df.columns:
        raise ValueError(
            "Product master file must have a 'Product Alias' column (Product Name, "
            "Brand, Category, MRP, Current Stock are optional)."
        )

    inserted, updated = 0, 0
    with session_scope() as s:
        for _, row in df.iterrows():
            alias = str(row.get("product_alias", "")).strip()
            if not alias or alias.lower() == "nan":
                continue
            existing = s.get(ProductMaster, alias)
            values = dict(
                product_name=str(row.get("product_name", "") or ""),
                brand=str(row.get("brand", "") or ""),
                category=str(row.get("category", "") or ""),
                mrp=float(row["mrp"]) if pd.notna(row.get("mrp")) else None,
                current_stock=float(row["current_stock"]) if pd.notna(row.get("current_stock")) else None,
            )
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                s.add(ProductMaster(product_alias=alias, **values))
                inserted += 1

    return {"inserted": inserted, "updated": updated}
