from __future__ import annotations
from backend.data_loader import data_store


def get_candidate_suppliers(
    category_l1: str,
    category_l2: str,
) -> list[dict]:
    """Get all suppliers that serve a given category."""
    return data_store.suppliers_by_category.get((category_l1, category_l2), [])


def supplier_covers_countries(
    supplier: dict,
    delivery_countries: list[str],
) -> bool:
    """Check if a supplier's service regions cover all delivery countries."""
    regions = supplier.get("service_regions_list", [])
    return all(c in regions for c in delivery_countries)
