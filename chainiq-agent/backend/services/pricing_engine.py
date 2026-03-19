from __future__ import annotations
from typing import Optional
from backend.data_loader import data_store
from backend.config import COUNTRY_TO_REGION


def get_pricing(
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    region: str,
    currency: str,
    quantity: int,
) -> Optional[dict]:
    """Find the pricing tier for a supplier given category, region, currency, and quantity."""
    key = (supplier_id, category_l1, category_l2)
    tiers = data_store.pricing_by_supplier_category.get(key, [])

    for tier in tiers:
        if tier["region"] != region:
            continue
        if tier["currency"] != currency:
            continue
        if tier["min_quantity"] <= quantity <= tier["max_quantity"]:
            return {
                "pricing_id": tier["pricing_id"],
                "unit_price": tier["unit_price"],
                "total_price": round(tier["unit_price"] * quantity, 2),
                "expedited_unit_price": tier["expedited_unit_price"],
                "expedited_total": round(tier["expedited_unit_price"] * quantity, 2),
                "standard_lead_time_days": tier["standard_lead_time_days"],
                "expedited_lead_time_days": tier["expedited_lead_time_days"],
                "moq": tier["moq"],
                "min_quantity": tier["min_quantity"],
                "max_quantity": tier["max_quantity"],
                "pricing_model": tier["pricing_model"],
                "tier_label": f"{tier['min_quantity']}–{tier['max_quantity']} units",
            }
    return None


def get_best_pricing_for_supplier(
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    delivery_countries: list[str],
    currency: str,
    quantity: int,
) -> Optional[dict]:
    """Find the best pricing across applicable regions."""
    for country in delivery_countries:
        region = COUNTRY_TO_REGION.get(country)
        if not region:
            continue
        pricing = get_pricing(
            supplier_id, category_l1, category_l2, region, currency, quantity
        )
        if pricing:
            pricing["region"] = region
            pricing["currency"] = currency
            return pricing
    return None


def get_min_total_cost(
    category_l1: str,
    category_l2: str,
    region: str,
    currency: str,
    quantity: int,
) -> Optional[tuple[float, str]]:
    """Find the minimum total cost across all suppliers for a category/quantity.
    Returns (min_cost, supplier_id) or None."""
    key_prefix = (category_l1, category_l2)
    min_cost = float("inf")
    best_supplier = None

    for (sid, c1, c2), tiers in data_store.pricing_by_supplier_category.items():
        if (c1, c2) != key_prefix:
            continue
        for tier in tiers:
            if tier["region"] != region or tier["currency"] != currency:
                continue
            if tier["min_quantity"] <= quantity <= tier["max_quantity"]:
                total = round(tier["unit_price"] * quantity, 2)
                if total < min_cost:
                    min_cost = total
                    best_supplier = sid

    if best_supplier:
        return min_cost, best_supplier
    return None
