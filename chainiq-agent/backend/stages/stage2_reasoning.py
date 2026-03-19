from __future__ import annotations
import json
from backend.models.prs import PRS
from backend.services.llm import call_llm_json
from backend.services.prs_utils import coerce_number
from backend.services.policy_engine import (
    get_approval_threshold, is_preferred_supplier, check_supplier_restriction,
    get_category_rules, get_geography_rules,
)
from backend.services.pricing_engine import get_best_pricing_for_supplier, get_min_total_cost
from backend.services.supplier_filter import get_candidate_suppliers
from backend.data_loader import data_store
from backend.config import MODEL_REASONING, COUNTRY_TO_REGION
from backend.prompts.stage2_prompt import STAGE2_SYSTEM, build_stage2_user_message


async def run_stage2(prs: PRS) -> dict:
    """Stage 2: Policy reasoning, anomaly detection, and proposed changes."""
    cat_l1 = prs.category_l1.value or ""
    cat_l2 = prs.category_l2.value or ""
    currency = prs.currency.value or "EUR"
    quantity = coerce_number(prs.quantity.value, default=0) or 0
    budget = coerce_number(prs.budget_amount.value)
    delivery_countries = prs.delivery_countries.value or []

    # Pre-compute pricing context (LLM should NOT do math)
    pricing_context = _build_pricing_context(
        cat_l1, cat_l2, delivery_countries, currency, quantity
    )

    # Pre-compute supplier context
    candidates = get_candidate_suppliers(cat_l1, cat_l2)
    supplier_context = []
    for s in candidates:
        sid = s["supplier_id"]
        is_pref, _ = is_preferred_supplier(sid, cat_l1, cat_l2, delivery_countries)
        is_restricted, restriction_reason = check_supplier_restriction(
            sid, cat_l1, cat_l2, delivery_countries,
            coerce_number(pricing_context.get("min_total_cost"), default=0) or 0, currency
        )
        supplier_context.append({
            "supplier_id": sid,
            "supplier_name": s["supplier_name"],
            "preferred": is_pref,
            "restricted": is_restricted,
            "restriction_reason": restriction_reason,
            "quality_score": s.get("quality_score"),
            "risk_score": s.get("risk_score"),
            "esg_score": s.get("esg_score"),
            "capacity_per_month": s.get("capacity_per_month"),
            "data_residency_supported": s.get("data_residency_supported"),
            "covers_delivery": all(c in s.get("service_regions_list", []) for c in delivery_countries),
        })

    # Build PRS dict for LLM
    prs_dict = json.loads(prs.model_dump_json())

    # Prepare policies summary (only relevant sections)
    policies_for_llm = {
        "approval_thresholds": data_store.approval_thresholds,
        "restricted_suppliers": data_store.restricted_suppliers,
        "category_rules": get_category_rules(cat_l1, cat_l2),
        "geography_rules": get_geography_rules(delivery_countries),
        "escalation_rules": data_store.escalation_rules,
    }

    user_msg = build_stage2_user_message(
        prs_dict, policies_for_llm, pricing_context, supplier_context
    )
    result = await call_llm_json(MODEL_REASONING, STAGE2_SYSTEM, user_msg)
    return result


def _build_pricing_context(
    cat_l1: str, cat_l2: str,
    delivery_countries: list[str], currency: str, quantity: int,
) -> dict:
    """Pre-compute all pricing data so the LLM doesn't need to do math."""
    if not quantity or not delivery_countries:
        return {"note": "quantity or delivery_countries not specified — pricing unconstrained"}

    region = COUNTRY_TO_REGION.get(delivery_countries[0], "EU") if delivery_countries else "EU"

    min_result = get_min_total_cost(cat_l1, cat_l2, region, currency, quantity)
    context = {
        "quantity": quantity,
        "currency": currency,
        "region": region,
    }

    if min_result:
        context["min_total_cost"] = min_result[0]
        context["min_cost_supplier_id"] = min_result[1]
    else:
        context["min_total_cost"] = None
        context["note"] = "No pricing found for this category/region/currency/quantity"

    # Per-supplier pricing
    candidates = get_candidate_suppliers(cat_l1, cat_l2)
    supplier_pricing = []
    for s in candidates:
        pricing = get_best_pricing_for_supplier(
            s["supplier_id"], cat_l1, cat_l2, delivery_countries, currency, quantity
        )
        if pricing:
            supplier_pricing.append({
                "supplier_id": s["supplier_id"],
                "supplier_name": s["supplier_name"],
                **pricing,
            })
    context["supplier_pricing"] = supplier_pricing

    return context
