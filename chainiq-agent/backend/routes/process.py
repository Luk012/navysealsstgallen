from __future__ import annotations
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from backend.data_loader import data_store
from backend.models.prs import PRS
from backend.models.output import ProcessingResult
from backend.stages.stage1_intake import run_stage1
from backend.stages.stage3_mastermind import run_stage2_3_loop
from backend.stages.stage4_matching import run_stage4
from backend.stages.branch_a_ranking import run_branch_a
from backend.stages.branch_b_relaxation import greedy_relax
from backend.services.policy_engine import get_approval_threshold
from backend.services.historical import get_historical_awards

router = APIRouter()

# Cache results in memory
_results_cache: dict[str, dict] = {}


@router.post("/process/{request_id}")
async def process_request(request_id: str):
    """Process a single request through the full pipeline."""
    request = data_store.requests_by_id.get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

    try:
        result = await _run_pipeline(request)
        _results_cache[request_id] = result
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results/{request_id}")
async def get_result(request_id: str):
    """Get cached processing result."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="Result not found. Process the request first.")
    return _results_cache[request_id]


async def _run_pipeline(request: dict) -> dict:
    """Execute the full 4-stage pipeline."""
    request_id = request["request_id"]

    # Stage 1: Intake & Extraction
    prs = await run_stage1(request)

    # Stages 2-3: Reasoning + Mastermind loop
    prs, commit_log, analysis = await run_stage2_3_loop(prs)

    # Stage 4: Supplier matching
    supplier_results = run_stage4(prs)

    # Determine K (min quotes required)
    currency = prs.currency.value or "EUR"
    estimated_value = prs.estimated_total_value.value
    if estimated_value is None and prs.budget_amount.value:
        estimated_value = prs.budget_amount.value
    if estimated_value is None:
        estimated_value = 0
    threshold = get_approval_threshold(currency, float(estimated_value))
    k = threshold.get("min_supplier_quotes", 3) if threshold else 3

    # Count passing suppliers (no hard fails)
    passing = [s for s in supplier_results if not s.hard_fail]

    branch = "A" if len(passing) >= k else "B"
    relaxations = []
    ranking_result = {}

    if branch == "A":
        ranking_result = await run_branch_a(prs, passing)
    else:
        eligible, relaxations_applied = greedy_relax(
            [s for s in supplier_results],  # Copy list
            k=k,
        )
        relaxations = relaxations_applied
        if eligible:
            ranking_result = await run_branch_a(prs, eligible)

    # Build output
    return _build_output(
        request_id, prs, commit_log, analysis,
        supplier_results, passing, ranking_result,
        branch, relaxations, threshold,
    )


def _build_output(
    request_id, prs, commit_log, analysis,
    supplier_results, passing, ranking_result,
    branch, relaxations, threshold,
) -> dict:
    """Assemble the final output matching example_output.json format."""
    # Request interpretation
    interpretation = {
        "category_l1": prs.category_l1.value,
        "category_l2": prs.category_l2.value,
        "quantity": prs.quantity.value,
        "unit_of_measure": prs.unit_of_measure.value,
        "budget_amount": prs.budget_amount.value,
        "currency": prs.currency.value,
        "delivery_country": (prs.delivery_countries.value or [None])[0],
        "required_by_date": prs.required_by_date.value,
        "days_until_required": prs.days_until_required.value,
        "data_residency_required": prs.data_residency_required.value,
        "esg_requirement": prs.esg_requirement.value,
        "preferred_supplier_stated": prs.preferred_supplier_stated.value,
        "incumbent_supplier": prs.incumbent_supplier.value,
        "requester_instruction": prs.requester_instruction.value,
    }

    # Validation
    validation = {
        "completeness": prs.completeness_status.value or "pass",
        "issues_detected": prs.issues if prs.issues else [],
    }

    # Add issues from analysis anomalies
    if analysis.get("anomalies"):
        issue_counter = len(validation["issues_detected"]) + 1
        for anomaly in analysis["anomalies"]:
            validation["issues_detected"].append({
                "issue_id": f"V-{issue_counter:03d}",
                "severity": anomaly.get("severity", "medium"),
                "type": anomaly.get("type", "other"),
                "description": anomaly.get("description", ""),
                "action_required": anomaly.get("action_required", ""),
            })
            issue_counter += 1

    # Policy evaluation
    policy_eval = {
        "approval_threshold": analysis.get("threshold_analysis", {}),
        "preferred_supplier": analysis.get("preferred_supplier_analysis", {}),
        "restricted_suppliers": {},
        "category_rules_applied": analysis.get("category_rules_triggered", []),
        "geography_rules_applied": analysis.get("geography_rules_triggered", []),
    }

    # Supplier shortlist from ranking
    supplier_shortlist = []
    ranked = ranking_result.get("ranked_suppliers", [])
    for i, rs in enumerate(ranked[:3]):
        # Find the matching supplier result for detailed data
        match = next(
            (s for s in supplier_results if s.supplier_id == rs.get("supplier_id")),
            None,
        )
        entry = {
            "rank": i + 1,
            "supplier_id": rs.get("supplier_id", ""),
            "supplier_name": rs.get("supplier_name", ""),
            "preferred": match.preferred if match else False,
            "incumbent": match.incumbent if match else False,
            "recommendation_note": rs.get("recommendation_note", ""),
        }
        if match and match.pricing:
            p = match.pricing
            entry.update({
                "pricing_tier_applied": p.get("tier_label", ""),
                "unit_price": p.get("unit_price", 0),
                "total_price": p.get("total_price", 0),
                "currency": prs.currency.value or "EUR",
                "standard_lead_time_days": p.get("standard_lead_time_days", 0),
                "expedited_lead_time_days": p.get("expedited_lead_time_days", 0),
                "expedited_unit_price": p.get("expedited_unit_price", 0),
                "expedited_total": p.get("expedited_total", 0),
            })
        if match:
            entry.update({
                "quality_score": match.scores.get("quality_score", 0),
                "risk_score": match.scores.get("risk_score", 0),
                "esg_score": match.scores.get("esg_score", 0),
                "policy_compliant": not match.hard_fail,
                "covers_delivery_country": match.covers_delivery_country,
            })
        supplier_shortlist.append(entry)

    # Excluded suppliers
    excluded = []
    for s in supplier_results:
        if s.hard_fail:
            reasons = [d["reason"] for d in s.constraint_details if d.get("status") == "fail" and d.get("reason")]
            excluded.append({
                "supplier_id": s.supplier_id,
                "supplier_name": s.supplier_name,
                "reason": "; ".join(reasons) if reasons else "Hard constraint failure",
            })

    # Escalations
    escalations = ranking_result.get("escalations", [])
    for i, esc in enumerate(escalations):
        esc["escalation_id"] = f"ESC-{i+1:03d}"

    # Recommendation
    recommendation = ranking_result.get("recommendation", {
        "status": "cannot_proceed" if branch == "B" else "proceed",
        "reason": "",
    })

    # Audit trail
    policies_checked = set()
    if analysis.get("threshold_analysis", {}).get("applicable_threshold"):
        policies_checked.add(analysis["threshold_analysis"]["applicable_threshold"])
    for rule in analysis.get("category_rules_triggered", []):
        if rule.get("applies"):
            policies_checked.add(rule["rule_id"])
    for rule in analysis.get("geography_rules_triggered", []):
        if rule.get("applies"):
            policies_checked.add(rule["rule_id"])
    for esc in analysis.get("escalation_triggers", []):
        if esc.get("triggered"):
            policies_checked.add(esc["rule_id"])

    # Historical awards
    hist = get_historical_awards(request_id)
    hist_note = ""
    if hist:
        awarded = [h for h in hist if h.get("awarded") in (True, "True")]
        if awarded:
            top = awarded[0]
            hist_note = (
                f"Historical: {top.get('supplier_name', 'Unknown')} was previously awarded "
                f"(rank {top.get('award_rank', 'N/A')}). "
                f"{'Escalation was required.' if top.get('escalation_required') in (True, 'True') else ''}"
            )

    audit_trail = {
        "policies_checked": sorted(policies_checked),
        "supplier_ids_evaluated": [s.supplier_id for s in supplier_results],
        "data_sources_used": ["requests.json", "suppliers.csv", "pricing.csv", "policies.json"],
        "historical_awards_consulted": bool(hist),
        "historical_award_note": hist_note,
        "commit_log": [c.model_dump() for c in commit_log.commits],
    }

    return {
        "request_id": request_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "request_interpretation": interpretation,
        "validation": validation,
        "policy_evaluation": policy_eval,
        "supplier_shortlist": supplier_shortlist,
        "suppliers_excluded": excluded,
        "escalations": escalations,
        "recommendation": recommendation,
        "audit_trail": audit_trail,
        "branch": branch,
        "relaxations": relaxations,
        "prs": json.loads(prs.model_dump_json()),
    }
