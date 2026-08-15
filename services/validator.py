import re
from rapidfuzz import process, fuzz

from database.db import session_scope, get_setting
from database.models import ProductMaster


def get_product_master_aliases() -> list[str]:
    with session_scope() as s:
        return [row.product_alias for row in s.query(ProductMaster.product_alias).all()]


def validate_row(row: dict) -> dict:
    """Mutates confidence/status decisions based on regex + optional product master.
    Returns the row dict with an added 'status' key: 'accepted' or 'pending'."""
    alias_regex = get_setting("alias_regex", r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")
    ocr_threshold = float(get_setting("ocr_confidence_threshold", 0.75))
    cross_threshold = float(get_setting("cross_confidence_threshold", 0.70))
    fuzzy_threshold = float(get_setting("fuzzy_match_threshold", 85))

    alias = row["product_alias"]
    regex_ok = bool(re.match(alias_regex, alias))

    master_aliases = get_product_master_aliases()
    if master_aliases:
        best = process.extractOne(alias, master_aliases, scorer=fuzz.ratio)
        if best and best[1] >= fuzzy_threshold:
            # Snap to the canonical master alias if it's a near-exact match
            if best[1] >= 98:
                row["product_alias"] = best[0]
            row["master_match_score"] = best[1]
        else:
            row["master_match_score"] = best[1] if best else 0
    else:
        row["master_match_score"] = None

    meets_confidence = (
        row["ocr_confidence"] >= ocr_threshold
        and row["cross_confidence"] >= cross_threshold
    )
    master_ok = row["master_match_score"] is None or row["master_match_score"] >= fuzzy_threshold

    row["status"] = "accepted" if (regex_ok and meets_confidence and master_ok) else "pending"
    row["regex_ok"] = regex_ok
    return row
