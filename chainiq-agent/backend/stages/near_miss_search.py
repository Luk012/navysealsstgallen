from __future__ import annotations
import json
from backend.models.prs import PRS
from backend.models.constraint import SupplierConstraintResult, is_hard_fail
from backend.services.llm import call_llm_json
from backend.config import MODEL_RANKING
from backend.prompts.near_miss_prompt import NEAR_MISS_SYSTEM, build_near_miss_user_message


async def run_near_miss_search(
    prs: PRS,
    all_supplier_results: list[SupplierConstraintResult],
    passing_supplier_ids: list[str],
    emit=None,
) -> dict:
    """Find near-miss suppliers that almost meet the spec with slight relaxations."""
    # Filter to soft-fail-only suppliers not already in the passing set
    soft_fail = []
    for s in all_supplier_results:
        if s.supplier_id in passing_supplier_ids:
            continue
        if is_hard_fail(s.failure_bitmask):
            continue
        if s.failure_bitmask == 0:
            continue  # Already passes, just not in the set
        soft_fail.append(s)

    if not soft_fail:
        if emit:
            await emit(
                event_type="near_miss_complete",
                stage="near_miss",
                message="No near-miss candidates found",
                payload={"near_miss_suppliers": []},
            )
        return {"near_miss_suppliers": []}

    # Prepare supplier data for LLM
    scored = []
    for s in soft_fail[:10]:  # Cap at 10
        scored.append({
            "supplier_id": s.supplier_id,
            "supplier_name": s.supplier_name,
            "preferred": s.preferred,
            "incumbent": s.incumbent,
            "pricing": s.pricing,
            "scores": s.scores,
            "covers_delivery_country": s.covers_delivery_country,
            "constraint_details": s.constraint_details,
            "total_penalty": s.total_penalty,
        })

    prs_dict = json.loads(prs.model_dump_json())
    user_msg = build_near_miss_user_message(prs_dict, scored, passing_supplier_ids)

    result = await call_llm_json(MODEL_RANKING, NEAR_MISS_SYSTEM, user_msg)

    if emit:
        await emit(
            event_type="near_miss_complete",
            stage="near_miss",
            message=f"Found {len(result.get('near_miss_suppliers', []))} near-miss options",
            payload=result,
        )

    return result
