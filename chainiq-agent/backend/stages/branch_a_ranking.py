from __future__ import annotations
import json
from backend.models.prs import PRS
from backend.models.constraint import SupplierConstraintResult
from backend.services.llm import call_llm_json
from backend.services.historical import get_historical_awards
from backend.config import MODEL_RANKING
from backend.prompts.stage4_prompt import STAGE4_SYSTEM, build_stage4_user_message


async def run_branch_a(
    prs: PRS,
    passing_suppliers: list[SupplierConstraintResult],
    emit=None,
) -> dict:
    """Branch A: Rank viable suppliers and produce recommendation."""
    # Prepare scored supplier data for LLM
    scored = []
    for s in passing_suppliers[:10]:  # Top 10 max
        entry = {
            "supplier_id": s.supplier_id,
            "supplier_name": s.supplier_name,
            "preferred": s.preferred,
            "incumbent": s.incumbent,
            "pricing": s.pricing,
            "scores": s.scores,
            "covers_delivery_country": s.covers_delivery_country,
            "constraint_details": s.constraint_details,
            "total_penalty": s.total_penalty,
        }
        scored.append(entry)

    # Historical context
    historical = get_historical_awards(prs.request_id)

    prs_dict = json.loads(prs.model_dump_json())
    user_msg = build_stage4_user_message(prs_dict, scored, historical)

    result = await call_llm_json(MODEL_RANKING, STAGE4_SYSTEM, user_msg)
    if emit:
        await emit(
            event_type="ranking",
            stage="branch_a",
            message=f"Ranked {len(result.get('ranked_suppliers', []))} viable suppliers",
            payload=result,
        )
    return result
