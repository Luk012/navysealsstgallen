from __future__ import annotations
from typing import Optional
from backend.data_loader import data_store
from backend.config import COUNTRY_TO_REGION


def get_approval_threshold(currency: str, amount: float) -> dict:
    """Find the matching approval threshold tier for a given currency and amount."""
    for t in data_store.approval_thresholds:
        if t["currency"] != currency:
            continue
        min_a = t["min_amount"]
        max_a = t["max_amount"] if t["max_amount"] is not None else float("inf")
        if min_a <= amount <= max_a:
            return t
    # Fallback: highest tier for that currency
    currency_thresholds = [
        t for t in data_store.approval_thresholds if t["currency"] == currency
    ]
    if currency_thresholds:
        return max(currency_thresholds, key=lambda t: t["min_amount"])
    return {}


def is_preferred_supplier(
    supplier_id: str, category_l1: str, category_l2: str, delivery_countries: list[str]
) -> tuple[bool, Optional[dict]]:
    """Check if a supplier is preferred for the given category and region."""
    key = (supplier_id, category_l1, category_l2)
    entry = data_store.preferred_lookup.get(key)
    if not entry:
        return False, None

    # Check region scope if present
    region_scope = entry.get("region_scope", [])
    if not region_scope:
        return True, entry

    # Map delivery countries to regions and check overlap
    delivery_regions = set()
    for c in delivery_countries:
        region = COUNTRY_TO_REGION.get(c)
        if region:
            delivery_regions.add(region)
        delivery_regions.add(c)  # Also add country code (CH is both a country and scope)

    if delivery_regions & set(region_scope):
        return True, entry

    return False, entry


def check_supplier_restriction(
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    delivery_countries: list[str],
    total_value: float = 0.0,
    currency: str = "EUR",
) -> tuple[bool, str]:
    """Check if a supplier is restricted. Returns (is_restricted, reason)."""
    for restriction in data_store.restricted_suppliers:
        if restriction["supplier_id"] != supplier_id:
            continue
        if restriction["category_l1"] != category_l1:
            continue
        if restriction.get("category_l2") and restriction["category_l2"] != category_l2:
            continue

        scope = restriction.get("restriction_scope", [])

        # Global/value-conditional restriction (e.g., SUP-0045)
        if scope == ["all"]:
            reason = restriction.get("restriction_reason", "")
            # Parse value threshold from reason if present
            if "below" in reason.lower() and "eur" in reason.lower():
                import re
                match = re.search(r"(\d+)", reason.replace(" ", ""))
                if match:
                    threshold = float(match.group(1))
                    if total_value > threshold:
                        return True, reason
                    else:
                        return False, ""
            return True, reason

        # Country-scoped restriction
        if any(c in scope for c in delivery_countries):
            return True, restriction.get("restriction_reason", "")

    return False, ""


def get_category_rules(category_l1: str, category_l2: str) -> list[dict]:
    """Get all category rules for a given category."""
    return data_store.category_rules.get((category_l1, category_l2), [])


def get_geography_rules(delivery_countries: list[str]) -> list[dict]:
    """Get all geography rules for the delivery countries."""
    rules = []
    seen_ids = set()
    for country in delivery_countries:
        for rule in data_store.geography_rules_by_country.get(country, []):
            if rule["rule_id"] not in seen_ids:
                rules.append(rule)
                seen_ids.add(rule["rule_id"])
    return rules


def get_escalation_rules() -> list[dict]:
    """Get all escalation rules."""
    return data_store.escalation_rules
