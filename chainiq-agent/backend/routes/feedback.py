from __future__ import annotations
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.routes.process import _results_cache, _run_pipeline
from backend.data_loader import data_store
from backend.services.llm import call_llm_json
from backend.config import MODEL_REASONING
from backend.prompts.escalation_chat_prompt import (
    ESCALATION_CHAT_SYSTEM,
    UNIFIED_ESCALATION_CHAT_SYSTEM,
    build_escalation_chat_user_message,
    build_unified_escalation_chat_user_message,
)
from backend.prompts.reevaluation_prompt import (
    REEVALUATION_SYSTEM,
    build_reevaluation_user_message,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class FeedbackRequest(BaseModel):
    feedback_text: str
    accepted_relaxations: list[str] = []
    rejected_relaxations: list[str] = []


class ChatMessageRequest(BaseModel):
    message: str


class NearMissDecisionRequest(BaseModel):
    decision: str  # "approved" or "rejected"


async def _call_feedback_llm_json(operation: str, system: str, user_msg: str):
    try:
        response = await call_llm_json(MODEL_REASONING, system, user_msg)
        if not isinstance(response, dict):
            raise ValueError(f"Expected JSON object, received {type(response).__name__}")
        return response
    except Exception as exc:
        import traceback
        traceback.print_exc()
        logger.exception("LLM %s failed", operation)
        raise HTTPException(
            status_code=502,
            detail=f"LLM {operation} failed: {type(exc).__name__}: {exc}",
        ) from exc


@router.post("/feedback/{request_id}")
async def submit_feedback(request_id: str, feedback: FeedbackRequest):
    """Submit user feedback for Branch B relaxation and re-process."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    previous = _results_cache[request_id]
    if previous.get("branch") != "B":
        raise HTTPException(status_code=400, detail="Feedback only applicable for Branch B results.")

    request = data_store.requests_by_id.get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

    result = await _run_pipeline(request)
    result["user_feedback"] = feedback.model_dump()
    _results_cache[request_id] = result
    return result


@router.post("/escalation/{request_id}/{escalation_id}/chat")
async def escalation_chat(request_id: str, escalation_id: str, body: ChatMessageRequest):
    """Send a chat message to resolve an escalation."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    result = _results_cache[request_id]
    escalations = result.get("escalations", [])
    escalation = next((e for e in escalations if e.get("escalation_id") == escalation_id), None)
    if not escalation:
        raise HTTPException(status_code=404, detail=f"Escalation {escalation_id} not found")

    # Initialize resolutions dict if needed
    resolutions = result.setdefault("escalation_resolutions", {})
    resolution = resolutions.get(escalation_id, {
        "escalation_id": escalation_id,
        "resolved": False,
        "chat_history": [],
        "resolution_summary": "",
    })

    # Append human message
    now = datetime.now(timezone.utc).isoformat()
    resolution["chat_history"].append({
        "role": "human",
        "content": body.message,
        "timestamp": now,
    })

    # Build request context for LLM
    request_context = {
        "request_interpretation": result.get("request_interpretation", {}),
        "recommendation": result.get("recommendation", {}),
    }

    # Call LLM for response
    user_msg = build_escalation_chat_user_message(
        escalation, resolution["chat_history"], request_context,
    )
    llm_response = await _call_feedback_llm_json(
        "escalation chat",
        ESCALATION_CHAT_SYSTEM,
        user_msg,
    )

    # Append system response
    resolution["chat_history"].append({
        "role": "system",
        "content": llm_response.get("response", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if llm_response.get("resolved", False):
        resolution["resolved"] = True
        resolution["resolution_summary"] = llm_response.get("resolution_summary", "")

    resolutions[escalation_id] = resolution
    return resolution


@router.post("/escalation/{request_id}/{escalation_id}/resolve")
async def escalation_resolve(request_id: str, escalation_id: str):
    """Manually mark an escalation as resolved."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    result = _results_cache[request_id]
    escalations = result.get("escalations", [])
    escalation = next((e for e in escalations if e.get("escalation_id") == escalation_id), None)
    if not escalation:
        raise HTTPException(status_code=404, detail=f"Escalation {escalation_id} not found")

    resolutions = result.setdefault("escalation_resolutions", {})
    resolution = resolutions.get(escalation_id, {
        "escalation_id": escalation_id,
        "resolved": False,
        "chat_history": [],
        "resolution_summary": "",
    })
    resolution["resolved"] = True
    resolution["resolution_summary"] = "Manually resolved by reviewer"
    resolutions[escalation_id] = resolution
    return resolution


@router.post("/escalation/{request_id}/chat-unified")
async def escalation_chat_unified(request_id: str, body: ChatMessageRequest):
    """Send a chat message to the unified escalation chat interface."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    result = _results_cache[request_id]
    escalations = result.get("escalations", [])
    if not escalations:
        raise HTTPException(status_code=400, detail="No escalations to discuss.")

    resolutions = result.setdefault("escalation_resolutions", {})

    # Ensure all escalations have resolution entries
    for esc in escalations:
        esc_id = esc.get("escalation_id", "")
        if esc_id not in resolutions:
            resolutions[esc_id] = {
                "escalation_id": esc_id,
                "resolved": False,
                "chat_history": [],
                "resolution_summary": "",
            }

    # Get or initialize unified chat history
    unified_key = "_unified_chat_history"
    unified_history = result.setdefault(unified_key, [])

    # Append human message
    now = datetime.now(timezone.utc).isoformat()
    unified_history.append({
        "role": "human",
        "content": body.message,
        "timestamp": now,
    })

    # Build request context
    request_context = {
        "request_interpretation": result.get("request_interpretation", {}),
        "recommendation": result.get("recommendation", {}),
    }

    # Call LLM with unified context
    user_msg = build_unified_escalation_chat_user_message(
        escalations, resolutions, unified_history, request_context,
    )
    llm_response = await _call_feedback_llm_json(
        "unified escalation chat",
        UNIFIED_ESCALATION_CHAT_SYSTEM,
        user_msg,
    )

    # Append assistant response
    unified_history.append({
        "role": "system",
        "content": llm_response.get("response", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Apply per-escalation updates from the LLM
    for update in llm_response.get("escalation_updates", []):
        esc_id = update.get("escalation_id", "")
        if esc_id in resolutions and update.get("resolved", False):
            resolutions[esc_id]["resolved"] = True
            resolutions[esc_id]["resolution_summary"] = update.get("resolution_summary", "")
            # Copy relevant chat context into the per-escalation history
            resolutions[esc_id]["chat_history"] = list(unified_history)

    # Check if all escalations are now resolved
    all_resolved = all(
        resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
        for esc in escalations
    )

    return {
        "chat_history": unified_history,
        "escalation_resolutions": resolutions,
        "all_resolved": all_resolved,
        "still_unresolved": llm_response.get("still_unresolved", []),
    }


@router.post("/escalation/{request_id}/reevaluate")
async def escalation_reevaluate(request_id: str):
    """Re-evaluate all output tabs after all escalations are resolved."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    result = _results_cache[request_id]
    escalations = result.get("escalations", [])
    resolutions = result.get("escalation_resolutions", {})

    if not escalations:
        raise HTTPException(status_code=400, detail="No escalations to re-evaluate against.")

    # Verify all escalations are resolved
    for esc in escalations:
        esc_id = esc.get("escalation_id", "")
        if not resolutions.get(esc_id, {}).get("resolved", False):
            raise HTTPException(
                status_code=400,
                detail=f"Escalation {esc_id} is not yet resolved. Resolve all escalations first.",
            )

    # Call LLM to re-evaluate
    user_msg = build_reevaluation_user_message(result, resolutions)
    llm_response = await _call_feedback_llm_json(
        "post-escalation re-evaluation",
        REEVALUATION_SYSTEM,
        user_msg,
    )

    # ── Apply recommendation update ──
    if llm_response.get("recommendation"):
        result["recommendation"] = llm_response["recommendation"]

    # ── Apply interpretation updates ──
    for field, value in llm_response.get("interpretation_updates", {}).items():
        if field in result.get("request_interpretation", {}):
            result["request_interpretation"][field] = value

    # ── Apply policy updates ──
    for field, value in llm_response.get("policy_updates", {}).items():
        if field in result.get("policy_evaluation", {}):
            result["policy_evaluation"][field] = value

    # ── Apply validation updates & anomaly cleanup ──
    val_updates = llm_response.get("validation_updates", {})
    if val_updates.get("issues_to_remove"):
        remove_ids = set(val_updates["issues_to_remove"])
        issues = result.get("validation", {}).get("issues_detected", [])
        result["validation"]["issues_detected"] = [
            i for i in issues if i.get("issue_id") not in remove_ids
        ]
    for new_issue in val_updates.get("issues_to_add", []):
        result.setdefault("validation", {}).setdefault("issues_detected", []).append(new_issue)

    # Clean up stale anomalies that were resolved by escalation
    anomalies_to_remove = val_updates.get("anomalies_to_remove", [])
    if anomalies_to_remove:
        remove_set = set(a.lower() for a in anomalies_to_remove)
        issues = result.get("validation", {}).get("issues_detected", [])
        result["validation"]["issues_detected"] = [
            i for i in issues
            if not any(
                rem in (i.get("description", "").lower() + " " + i.get("type", "").lower())
                for rem in remove_set
            )
        ]
        # Also clean anomalies from PRS if present
        prs = result.get("prs", {})
        if prs.get("detected_anomalies") and prs["detected_anomalies"].get("value"):
            prs_anomalies = prs["detected_anomalies"]["value"]
            if isinstance(prs_anomalies, list):
                prs["detected_anomalies"]["value"] = [
                    a for a in prs_anomalies
                    if not any(
                        rem in (str(a).lower())
                        for rem in remove_set
                    )
                ]

    # ── Apply supplier ranking changes (full re-rank support) ──
    ranking_changes = llm_response.get("supplier_ranking_changes", {})

    # If LLM provided updated_ranks, rebuild the shortlist with new ordering
    if ranking_changes.get("updated_ranks"):
        updated_ranks = ranking_changes["updated_ranks"]
        existing_shortlist = {s.get("supplier_id"): s for s in result.get("supplier_shortlist", [])}
        new_shortlist = []
        for rank_entry in updated_ranks:
            sid = rank_entry.get("supplier_id", "")
            existing = existing_shortlist.get(sid, {})
            # Merge: keep pricing/scores from original, update rank and notes
            merged = {**existing}
            merged["rank"] = rank_entry.get("new_rank", existing.get("rank", 0))
            merged["supplier_id"] = sid
            merged["supplier_name"] = rank_entry.get("supplier_name", existing.get("supplier_name", ""))
            merged["recommendation_note"] = rank_entry.get("recommendation_note", existing.get("recommendation_note", ""))
            if rank_entry.get("strengths"):
                merged["strengths"] = rank_entry["strengths"]
            if rank_entry.get("weaknesses"):
                merged["weaknesses"] = rank_entry["weaknesses"]
            new_shortlist.append(merged)
        if new_shortlist:
            result["supplier_shortlist"] = sorted(new_shortlist, key=lambda s: s.get("rank", 999))

    # Also apply updated_notes if provided (for cases without full re-rank)
    elif ranking_changes.get("updated_notes"):
        for supplier in result.get("supplier_shortlist", []):
            sid = supplier.get("supplier_id", "")
            if sid in ranking_changes["updated_notes"]:
                supplier["recommendation_note"] = ranking_changes["updated_notes"][sid]

    # ── Update escalation statuses ──
    esc_status_updates = llm_response.get("escalation_status_updates", {})
    if esc_status_updates.get("updated_escalations"):
        esc_lookup = {e.get("escalation_id"): e for e in result.get("escalations", [])}
        for update in esc_status_updates["updated_escalations"]:
            esc_id = update.get("escalation_id", "")
            if esc_id in esc_lookup:
                esc_lookup[esc_id]["blocking"] = update.get("blocking", False)
                esc_lookup[esc_id]["resolution_note"] = update.get("resolution_note", "")
                esc_lookup[esc_id]["resolved"] = True

    # ── Add re-evaluation to audit trail ──
    audit = result.setdefault("audit_trail", {})
    reeval_commit_id = f"REEVAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    audit.setdefault("commit_log", []).append({
        "commit_id": reeval_commit_id,
        "stage": "post_escalation_reevaluation",
        "iteration": 0,
        "field_path": "recommendation",
        "old_value": "provisional",
        "new_value": "final",
        "justification": llm_response.get("audit_note", "Post-escalation re-evaluation"),
        "approval_status": "approved",
        "approval_rationale": "All escalations resolved by authorized reviewers",
    })

    # Record cleanup actions in audit trail
    if anomalies_to_remove:
        audit["commit_log"].append({
            "commit_id": f"{reeval_commit_id}-CLEANUP",
            "stage": "post_escalation_cleanup",
            "iteration": 0,
            "field_path": "validation.issues_detected",
            "old_value": f"{len(anomalies_to_remove)} stale anomalies",
            "new_value": "cleaned up",
            "justification": f"Removed resolved anomalies: {', '.join(anomalies_to_remove)}",
            "approval_status": "approved",
            "approval_rationale": "Anomalies resolved via escalation process",
        })

    # Force-clean any remaining validation issues whose action_required references
    # escalation, since all escalations are now resolved.
    remaining_issues = result.get("validation", {}).get("issues_detected", [])
    if remaining_issues:
        cleaned = []
        for issue in remaining_issues:
            action = (issue.get("action_required") or "").lower()
            desc = (issue.get("description") or "").lower()
            # Keep only issues unrelated to escalation resolution
            is_escalation_related = any(
                kw in action or kw in desc
                for kw in ["escalat", "review", "clarif", "confirm", "approv", "missing", "resolve"]
            )
            if not is_escalation_related:
                cleaned.append(issue)
        result["validation"]["issues_detected"] = cleaned

    # Mark as re-evaluated
    result["reevaluated"] = True
    result["reevaluated_at"] = datetime.now(timezone.utc).isoformat()

    _results_cache[request_id] = result
    return result


@router.post("/near-miss/{request_id}/{supplier_id}/decide")
async def near_miss_decide(request_id: str, supplier_id: str, body: NearMissDecisionRequest):
    """Approve or reject a near-miss supplier option."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'rejected'")

    result = _results_cache[request_id]
    near_miss = result.get("near_miss_suppliers", [])
    supplier = next((s for s in near_miss if s.get("supplier_id") == supplier_id), None)
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Near-miss supplier {supplier_id} not found")

    supplier["human_decision"] = body.decision
    return supplier
