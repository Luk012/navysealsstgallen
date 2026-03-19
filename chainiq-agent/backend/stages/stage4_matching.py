from __future__ import annotations
from datetime import datetime, timezone
from backend.models.prs import PRS
from backend.models.constraint import (
    ConstraintFlag, SupplierConstraintResult,
    compute_penalty, is_hard_fail, HARD_MASK,
)
from backend.services.supplier_filter import get_candidate_suppliers, supplier_covers_countries
from backend.services.pricing_engine import get_best_pricing_for_supplier
from backend.services.prs_utils import coerce_bool, coerce_number
from backend.services.policy_engine import (
    is_preferred_supplier, check_supplier_restriction,
)
from backend.services.historical import get_supplier_performance_summary
from backend.data_loader import data_store


def run_stage4(prs: PRS) -> list[SupplierConstraintResult]:
    """Stage 4: Evaluate every candidate supplier against the finalized PRS."""
    cat_l1 = prs.category_l1.value or ""
    cat_l2 = prs.category_l2.value or ""
    currency = prs.currency.value or "EUR"
    quantity = coerce_number(prs.quantity.value, default=0) or 0
    budget = coerce_number(prs.budget_amount.value)
    delivery_countries = prs.delivery_countries.value or []
    required_by_date = prs.required_by_date.value
    data_residency = coerce_bool(prs.data_residency_required.value, default=False)
    esg_required = coerce_bool(prs.esg_requirement.value, default=False)
    preferred_stated = prs.preferred_supplier_stated.value
    incumbent_stated = prs.incumbent_supplier.value

    # Compute days until required
    days_until = None
    if required_by_date:
        try:
            req_date = datetime.fromisoformat(required_by_date)
            if req_date.tzinfo is None:
                req_date = req_date.replace(tzinfo=timezone.utc)
            days_until = (req_date - datetime.now(timezone.utc)).days
        except (ValueError, TypeError):
            pass

    candidates = get_candidate_suppliers(cat_l1, cat_l2)
    results = []

    # If delivery_countries is empty, use supplier's HQ country or default
    # region to allow pricing lookup. This prevents all suppliers from
    # failing with CURRENCY_MISMATCH when no delivery country is specified.
    effective_delivery_countries = delivery_countries
    if not effective_delivery_countries:
        # Derive a fallback from currency → typical region
        from backend.config import COUNTRY_TO_CURRENCY
        fallback_countries = [
            country for country, curr in COUNTRY_TO_CURRENCY.items()
            if curr == currency
        ]
        if fallback_countries:
            # Pick the first matching country as a fallback for pricing lookup
            effective_delivery_countries = fallback_countries[:1]

    for supplier in candidates:
        sid = supplier["supplier_id"]
        sname = supplier["supplier_name"]
        result = SupplierConstraintResult(supplier_id=sid, supplier_name=sname)
        bitmask = ConstraintFlag.NONE
        details = []

        # 1. Check if supplier covers delivery countries
        # If no delivery countries specified, skip this check (vacuously true)
        if delivery_countries:
            covers = supplier_covers_countries(supplier, delivery_countries)
            result.covers_delivery_country = covers
            if not covers:
                bitmask |= ConstraintFlag.NO_REGION_COVER
                details.append({"constraint": "NO_REGION_COVER", "status": "fail",
                                "reason": f"Service regions {supplier.get('service_regions_list', [])} do not cover {delivery_countries}"})
            else:
                details.append({"constraint": "NO_REGION_COVER", "status": "pass"})
        else:
            result.covers_delivery_country = True
            details.append({"constraint": "NO_REGION_COVER", "status": "pass",
                            "reason": "No delivery countries specified — region check skipped"})

        # 2. Check restricted status
        pricing = get_best_pricing_for_supplier(
            sid, cat_l1, cat_l2, effective_delivery_countries, currency, quantity
        )
        estimated_value = pricing["total_price"] if pricing else 0
        is_restricted, restriction_reason = check_supplier_restriction(
            sid, cat_l1, cat_l2, effective_delivery_countries, estimated_value, currency
        )
        if is_restricted:
            bitmask |= ConstraintFlag.RESTRICTED
            details.append({"constraint": "RESTRICTED", "status": "fail", "reason": restriction_reason})
        else:
            details.append({"constraint": "RESTRICTED", "status": "pass"})

        # 3. Data residency check
        if data_residency and not supplier.get("data_residency_supported"):
            bitmask |= ConstraintFlag.DATA_RESIDENCY
            details.append({"constraint": "DATA_RESIDENCY", "status": "fail",
                            "reason": "Data residency required but supplier does not support it"})
        else:
            details.append({"constraint": "DATA_RESIDENCY", "status": "pass"})

        # 4. Pricing / Budget check
        if pricing:
            result.pricing = pricing
            if budget is not None and pricing["total_price"] > budget:
                bitmask |= ConstraintFlag.BUDGET_BREACH
                details.append({"constraint": "BUDGET_BREACH", "status": "fail",
                                "reason": f"Total {pricing['total_price']} > budget {budget}"})
            else:
                details.append({"constraint": "BUDGET_BREACH", "status": "pass"})
        else:
            bitmask |= ConstraintFlag.CURRENCY_MISMATCH
            details.append({"constraint": "CURRENCY_MISMATCH", "status": "fail",
                            "reason": "No pricing found for this supplier/category/region/currency"})

        # 5. Lead time check
        if pricing and days_until is not None:
            if pricing["expedited_lead_time_days"] > days_until:
                bitmask |= ConstraintFlag.LEAD_TIME_MISS
                details.append({"constraint": "LEAD_TIME_MISS", "status": "fail",
                                "reason": f"Expedited lead time {pricing['expedited_lead_time_days']}d > {days_until}d available"})
            else:
                details.append({"constraint": "LEAD_TIME_MISS", "status": "pass"})

        # 6. Preferred status
        is_pref, _ = is_preferred_supplier(sid, cat_l1, cat_l2, effective_delivery_countries)
        result.preferred = is_pref
        if not is_pref:
            bitmask |= ConstraintFlag.NOT_PREFERRED
            details.append({"constraint": "NOT_PREFERRED", "status": "fail"})
        else:
            details.append({"constraint": "NOT_PREFERRED", "status": "pass"})

        # 7. ESG check
        esg_score = supplier.get("esg_score", 0)
        if esg_required and (esg_score is None or esg_score < 50):
            bitmask |= ConstraintFlag.ESG_FAIL
            details.append({"constraint": "ESG_FAIL", "status": "fail",
                            "reason": f"ESG score {esg_score} below minimum 50"})
        else:
            details.append({"constraint": "ESG_FAIL", "status": "pass"})

        # 8. Capacity check
        capacity = supplier.get("capacity_per_month")
        if quantity and capacity and quantity > capacity:
            bitmask |= ConstraintFlag.CAPACITY_CONCERN
            details.append({"constraint": "CAPACITY_CONCERN", "status": "fail",
                            "reason": f"Quantity {quantity} > capacity {capacity}/month"})
        else:
            details.append({"constraint": "CAPACITY_CONCERN", "status": "pass"})

        # 9. Historical performance
        perf = get_supplier_performance_summary(sid)
        if not perf["has_history"]:
            bitmask |= ConstraintFlag.NO_HISTORICAL
            details.append({"constraint": "NO_HISTORICAL", "status": "fail"})
        else:
            details.append({"constraint": "NO_HISTORICAL", "status": "pass"})

        # Check incumbent
        result.incumbent = (
            sname == incumbent_stated or
            (preferred_stated and sname == preferred_stated and incumbent_stated is None)
        )

        # Scores
        result.scores = {
            "quality_score": supplier.get("quality_score", 0),
            "risk_score": supplier.get("risk_score", 0),
            "esg_score": esg_score,
            "historical": perf,
        }

        result.failure_bitmask = int(bitmask)
        result.hard_fail = is_hard_fail(int(bitmask))
        result.constraint_details = details
        result.total_penalty = compute_penalty(int(bitmask))

        results.append(result)

    # Sort: non-hard-fail first, then by total_penalty, then by price
    results.sort(key=lambda r: (
        r.hard_fail,
        r.total_penalty,
        r.pricing.get("total_price", float("inf")) if r.pricing else float("inf"),
    ))

    return results
