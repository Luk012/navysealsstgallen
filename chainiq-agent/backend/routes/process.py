from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from backend.data_loader import data_store
from backend.models.prs import PRS
from backend.models.output import ProcessingResult
from backend.stages.stage1_intake import run_stage1
from backend.stages.stage3_mastermind import run_stage2_3_loop
from backend.stages.stage4_matching import run_stage4
from backend.stages.branch_a_ranking import run_branch_a
from backend.stages.branch_b_relaxation import greedy_relax
from backend.stages.near_miss_search import run_near_miss_search
from backend.services.policy_engine import get_approval_threshold
from backend.services.policy_verifier import verify_all_policies
from backend.services.historical import get_historical_awards
from backend.services.prs_utils import coerce_number

router = APIRouter()

# Cache results in memory
_results_cache: dict[str, dict] = {}
_job_status: dict[str, dict] = {}
_processing_tasks: dict[str, asyncio.Task] = {}
_job_events: dict[str, list[dict]] = {}
_job_subscribers: dict[str, set[asyncio.Queue]] = {}


@router.post("/process/{request_id}")
async def process_request(request_id: str):
    """Start processing a request in the background."""
    request = data_store.requests_by_id.get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

    return await _ensure_processing_started(request_id, request)


@router.websocket("/ws/process/{request_id}")
async def process_request_ws(websocket: WebSocket, request_id: str):
    """Replay and stream live processing events for a request."""
    await websocket.accept()

    request = data_store.requests_by_id.get(request_id)
    if not request:
        await websocket.send_json(
            _build_event(
                request_id,
                event_type="status",
                stage="pipeline",
                status="failed",
                message=f"Request {request_id} not found",
                payload={"error": f"Request {request_id} not found"},
            )
        )
        await websocket.close(code=4404)
        return

    queue: asyncio.Queue = asyncio.Queue()
    _job_subscribers.setdefault(request_id, set()).add(queue)

    try:
        for event in _job_events.get(request_id, []):
            await websocket.send_json(event)

        status = await _ensure_processing_started(request_id, request)
        if status.get("status") == "completed":
            if request_id in _results_cache and not any(
                event.get("event_type") == "final_result"
                for event in _job_events.get(request_id, [])
            ):
                await websocket.send_json(
                    _build_event(
                        request_id,
                        event_type="final_result",
                        stage="pipeline",
                        message="Returning cached processing result",
                        payload=_results_cache[request_id],
                    )
                )
            await websocket.close()
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                current_status = _job_status.get(
                    request_id,
                    {"request_id": request_id, "status": "not_started"},
                )
                await websocket.send_json(
                    _build_event(
                        request_id,
                        event_type="heartbeat",
                        stage="pipeline",
                        status=current_status.get("status"),
                        message="Processing is still running",
                    )
                )
                if current_status.get("status") in {"completed", "failed"}:
                    await websocket.close()
                    return
                continue

            await websocket.send_json(event)
            if event.get("event_type") == "status" and event.get("status") in {"completed", "failed"}:
                await websocket.close()
                return
    except WebSocketDisconnect:
        return
    finally:
        subscribers = _job_subscribers.get(request_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                _job_subscribers.pop(request_id, None)


@router.get("/results/{request_id}")
async def get_result(request_id: str):
    """Get cached result or current job status."""
    if request_id not in _results_cache:
        return _job_status.get(
            request_id,
            {"request_id": request_id, "status": "not_started"},
        )
    return _results_cache[request_id]


@router.get("/events/{request_id}")
async def get_events(request_id: str):
    """Get cached processing events for a request (for live reasoning replay)."""
    events = _job_events.get(request_id, [])
    status = _job_status.get(request_id, {}).get("status", "not_started")
    return {
        "request_id": request_id,
        "status": status,
        "events": events,
    }


async def _ensure_processing_started(request_id: str, request: dict) -> dict:
    """Start a job once and return its current status payload."""
    if request_id in _results_cache:
        status = _job_status.get(request_id) or _build_job_status(
            request_id=request_id,
            status="completed",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        _job_status[request_id] = status
        return status

    current_status = _job_status.get(request_id, {})
    if current_status.get("status") in {"queued", "processing"}:
        return current_status

    _job_events[request_id] = []
    status = _build_job_status(
        request_id=request_id,
        status="queued",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    _job_status[request_id] = status
    await _emit_event(
        request_id,
        event_type="status",
        stage="pipeline",
        status="queued",
        message="Request queued for processing",
    )
    _processing_tasks[request_id] = asyncio.create_task(
        _process_request_in_background(request_id, request)
    )
    return status


async def _process_request_in_background(request_id: str, request: dict):
    """Run the pipeline and capture completion or failure for polling clients."""
    status = _job_status.get(request_id, {})
    status["status"] = "processing"
    _job_status[request_id] = status
    await _emit_event(
        request_id,
        event_type="status",
        stage="pipeline",
        status="processing",
        message="Pipeline execution started",
    )

    async def emit(**event):
        await _emit_event(request_id, **event)

    try:
        result = await _run_pipeline(request, emit=emit)
        _results_cache[request_id] = result
        _job_status[request_id] = {
            **status,
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        await _emit_event(
            request_id,
            event_type="final_result",
            stage="pipeline",
            message="Processing completed. Final result is ready.",
            payload=result,
        )
        await _emit_event(
            request_id,
            event_type="status",
            stage="pipeline",
            status="completed",
            message="Pipeline execution completed",
        )
    except Exception as e:
        _job_status[request_id] = {
            **status,
            "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }
        await _emit_event(
            request_id,
            event_type="status",
            stage="pipeline",
            status="failed",
            message="Pipeline execution failed",
            payload={"error": str(e)},
        )
    finally:
        _processing_tasks.pop(request_id, None)


async def _run_pipeline(request: dict, emit=None) -> dict:
    """Execute the full 4-stage pipeline."""
    request_id = request["request_id"]

    # Stage 1: Intake & Extraction
    if emit:
        await emit(
            event_type="stage_update",
            stage="stage1",
            message="Starting Stage 1: Intake and extraction",
        )
    prs = await run_stage1(request, emit=emit)

    # Stages 2-3: Reasoning + Mastermind loop
    if emit:
        await emit(
            event_type="stage_update",
            stage="stage2",
            message="Starting Stage 2/3 reasoning loop",
        )
    prs, commit_log, analysis = await run_stage2_3_loop(prs, emit=emit)

    # Stage 4: Supplier matching
    if emit:
        await emit(
            event_type="stage_update",
            stage="stage4",
            message="Starting Stage 4: Supplier matching",
        )
    supplier_results = run_stage4(prs)
    passing = [s for s in supplier_results if not s.hard_fail]
    if emit:
        await emit(
            event_type="supplier_summary",
            stage="stage4",
            message="Supplier constraint evaluation completed",
            payload=_summarize_supplier_results(supplier_results, passing),
        )

    # Determine K (min quotes required)
    currency = prs.currency.value or "EUR"
    estimated_value = coerce_number(prs.estimated_total_value.value)
    if estimated_value is None:
        estimated_value = coerce_number(prs.budget_amount.value, default=0)
    threshold = get_approval_threshold(currency, float(estimated_value or 0))
    k = threshold.get("min_supplier_quotes", 3) if threshold else 3

    branch = "A" if len(passing) >= k else "B"
    relaxations = []

    # Prepare branch-specific ranking coroutine
    ranking_suppliers = passing
    if branch == "A":
        if emit:
            await emit(
                event_type="stage_update",
                stage="branch_a",
                message=f"Branch A selected with {len(passing)} viable suppliers",
                payload={"required_quotes": k, "passing_suppliers": len(passing)},
            )
    else:
        if emit:
            await emit(
                event_type="stage_update",
                stage="branch_b",
                message="Not enough viable suppliers. Applying constraint relaxation.",
                payload={"required_quotes": k, "passing_suppliers": len(passing)},
            )
        eligible, relaxations_applied = greedy_relax(
            [s for s in supplier_results],
            k=k,
        )
        relaxations = relaxations_applied
        ranking_suppliers = eligible
        if emit:
            await emit(
                event_type="relaxations",
                stage="branch_b",
                message="Constraint relaxation completed",
                payload={
                    "relaxations": relaxations,
                    "eligible_suppliers": [s.supplier_id for s in eligible],
                },
            )

    # Run verification, ranking, and near-miss in parallel (they are independent)
    if emit:
        await emit(
            event_type="stage_update",
            stage="verification",
            message="Starting policy verification, ranking, and near-miss search in parallel",
        )

    async def _do_ranking():
        if not ranking_suppliers:
            return {}
        return await run_branch_a(prs, ranking_suppliers, emit=emit)

    async def _do_near_miss():
        if emit:
            await emit(
                event_type="stage_update",
                stage="near_miss",
                message="Searching for near-miss supplier options outside spec",
            )
        return await run_near_miss_search(
            prs, supplier_results,
            [s.supplier_id for s in passing],
            emit=emit,
        )

    verification_report, ranking_result, near_miss_result = await asyncio.gather(
        verify_all_policies(prs, supplier_results),
        _do_ranking(),
        _do_near_miss(),
    )

    if emit:
        await emit(
            event_type="verification_complete",
            stage="verification",
            message="Policy verification completed",
            payload=verification_report.summary(),
        )

    # Build output
    result = _build_output(
        request_id, prs, commit_log, analysis,
        supplier_results, passing, ranking_result,
        branch, relaxations, threshold, verification_report,
        near_miss_result,
    )
    if emit:
        await emit(
            event_type="summary",
            stage="pipeline",
            message="Final recommendation assembled",
            payload={
                "branch": branch,
                "recommendation": result.get("recommendation", {}),
                "escalations": result.get("escalations", []),
            },
        )
    return result


def _build_output(
    request_id, prs, commit_log, analysis,
    supplier_results, passing, ranking_result,
    branch, relaxations, threshold, verification_report=None,
    near_miss_result=None,
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

    # Add issues from analysis anomalies, filtering out stale ones
    if analysis.get("anomalies"):
        issue_counter = len(validation["issues_detected"]) + 1
        for anomaly in analysis["anomalies"]:
            desc = anomaly.get("description", "").lower()
            # Skip anomalies that claim fields are empty when they are actually populated
            skip = False
            if "empty" in desc or "not populated" in desc or "not specified" in desc:
                # Check if the field referenced is actually populated in the PRS
                field_checks = {
                    "category_l1": prs.category_l1.value,
                    "category_l2": prs.category_l2.value,
                    "currency": prs.currency.value,
                    "budget_amount": prs.budget_amount.value,
                    "quantity": prs.quantity.value,
                }
                for field_name, field_val in field_checks.items():
                    if field_name in desc and field_val:
                        skip = True
                        break
            if skip:
                continue
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
        "verification_report": (
            {
                "summary": verification_report.summary(),
                "results": [r.model_dump() for r in verification_report.results],
            }
            if verification_report
            else {}
        ),
    }

    # Supplier shortlist from ranking — split into standard/expedited shipping variants
    shipping_variants = []
    ranked = ranking_result.get("ranked_suppliers", [])
    for rs in ranked[:6]:  # Consider up to 6 ranked to fill 3 spec-satisfying slots
        match = next(
            (s for s in supplier_results if s.supplier_id == rs.get("supplier_id")),
            None,
        )
        base = {
            "supplier_id": rs.get("supplier_id", ""),
            "supplier_name": rs.get("supplier_name", ""),
            "preferred": match.preferred if match else False,
            "incumbent": match.incumbent if match else False,
            "recommendation_note": rs.get("recommendation_note", ""),
            "option_type": "spec_satisfying",
        }
        if match and match.pricing:
            p = match.pricing
            base.update({
                "pricing_tier_applied": p.get("tier_label", ""),
                "pricing_model": p.get("pricing_model", ""),
                "pricing_id": p.get("pricing_id", ""),
                "pricing_data_source": "pricing.csv",
                "quality_score": match.scores.get("quality_score", 0),
                "risk_score": match.scores.get("risk_score", 0),
                "esg_score": match.scores.get("esg_score", 0),
                "policy_compliant": not match.hard_fail,
                "covers_delivery_country": match.covers_delivery_country,
            })
            # Standard shipping variant
            std = dict(base)
            std["shipping_type"] = "standard"
            std["unit_price"] = p.get("unit_price", 0)
            std["total_price"] = p.get("total_price", 0)
            std["lead_time_days"] = p.get("standard_lead_time_days", 0)
            std["currency"] = prs.currency.value or "EUR"
            std["standard_lead_time_days"] = p.get("standard_lead_time_days", 0)
            std["expedited_lead_time_days"] = p.get("expedited_lead_time_days", 0)
            std["expedited_unit_price"] = p.get("expedited_unit_price", 0)
            std["expedited_total"] = p.get("expedited_total", 0)
            shipping_variants.append(std)

            # Expedited shipping variant (only if expedited data exists)
            exp_price = p.get("expedited_unit_price", 0)
            exp_lead = p.get("expedited_lead_time_days", 0)
            if exp_price and exp_lead:
                exp = dict(base)
                exp["shipping_type"] = "expedited"
                exp["unit_price"] = exp_price
                exp["total_price"] = p.get("expedited_total", 0) or (exp_price * (coerce_number(prs.quantity.value, default=0) or 0))
                exp["lead_time_days"] = exp_lead
                exp["currency"] = prs.currency.value or "EUR"
                exp["standard_lead_time_days"] = p.get("standard_lead_time_days", 0)
                exp["expedited_lead_time_days"] = exp_lead
                exp["expedited_unit_price"] = exp_price
                exp["expedited_total"] = exp["total_price"]
                shipping_variants.append(exp)
        elif match:
            base.update({
                "quality_score": match.scores.get("quality_score", 0),
                "risk_score": match.scores.get("risk_score", 0),
                "esg_score": match.scores.get("esg_score", 0),
                "policy_compliant": not match.hard_fail,
                "covers_delivery_country": match.covers_delivery_country,
                "shipping_type": "standard",
                "lead_time_days": 0,
                "currency": prs.currency.value or "EUR",
            })
            shipping_variants.append(base)

    # ── Hard constraint: exactly 3 spec-satisfying options (if 3 exist) ──
    spec_satisfying = []
    seen_combos = set()
    for v in shipping_variants:
        combo = (v["supplier_id"], v.get("shipping_type", "standard"))
        if combo not in seen_combos and len(spec_satisfying) < 3:
            seen_combos.add(combo)
            v["rank"] = len(spec_satisfying) + 1
            spec_satisfying.append(v)

    # Collect IDs already used by spec-satisfying options
    spec_supplier_ids = {v["supplier_id"] for v in spec_satisfying}

    # ── Hard constraint: exactly 2 constraint-relaxing options ──
    # Source 1: LLM near-miss results (richest data — includes gap descriptions)
    near_miss_list = (near_miss_result or {}).get("near_miss_suppliers", [])
    constraint_relaxing = []
    used_relaxed_ids = set()

    for nm in near_miss_list:
        if len(constraint_relaxing) >= 2:
            break
        nm_sid = nm.get("supplier_id", "")
        if nm_sid in spec_supplier_ids or nm_sid in used_relaxed_ids:
            continue
        used_relaxed_ids.add(nm_sid)
        constraint_relaxing.append(
            _build_relaxed_entry_from_near_miss(
                nm, supplier_results, prs, len(spec_satisfying) + len(constraint_relaxing) + 1,
            )
        )

    # Source 2: Deterministic soft-fail suppliers (fallback when LLM near-miss
    # didn't return enough). Sorted by total_penalty so the "closest" soft-fail
    # suppliers are chosen first.
    if len(constraint_relaxing) < 2:
        soft_fail_candidates = sorted(
            [
                s for s in supplier_results
                if not s.hard_fail
                and s.failure_bitmask != 0
                and s.supplier_id not in spec_supplier_ids
                and s.supplier_id not in used_relaxed_ids
            ],
            key=lambda s: s.total_penalty,
        )
        for sf in soft_fail_candidates:
            if len(constraint_relaxing) >= 2:
                break
            used_relaxed_ids.add(sf.supplier_id)
            constraint_relaxing.append(
                _build_relaxed_entry_from_constraint_result(
                    sf, prs, len(spec_satisfying) + len(constraint_relaxing) + 1,
                )
            )

    # Combine all options and compute comparative advantages
    supplier_shortlist = spec_satisfying + constraint_relaxing
    _compute_comparative_advantages(supplier_shortlist)

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
        "escalation_resolutions": {},
        "recommendation": recommendation,
        "audit_trail": audit_trail,
        "branch": branch,
        "relaxations": relaxations,
        "near_miss_suppliers": (near_miss_result or {}).get("near_miss_suppliers", []),
        "prs": json.loads(prs.model_dump_json()),
    }


def _build_relaxed_entry_from_near_miss(nm, supplier_results, prs, rank):
    """Build a constraint-relaxing shortlist entry from an LLM near-miss result."""
    from backend.models.constraint import ConstraintFlag

    nm_sid = nm.get("supplier_id", "")
    nm_match = next(
        (s for s in supplier_results if s.supplier_id == nm_sid), None,
    )
    relaxed_reqs = nm.get("relaxed_requirements", [])
    constraints_relaxed_labels = [
        r.get("requirement", "unknown") + ": " + r.get("gap_description", "")
        for r in relaxed_reqs
    ]
    entry = {
        "rank": rank,
        "supplier_id": nm_sid,
        "supplier_name": nm.get("supplier_name", ""),
        "preferred": nm_match.preferred if nm_match else False,
        "incumbent": nm_match.incumbent if nm_match else False,
        "recommendation_note": nm.get("overall_near_miss_rationale", ""),
        "option_type": "constraint_relaxing",
        "constraints_relaxed": constraints_relaxed_labels,
        "relaxed_requirements": relaxed_reqs,
        "recommended_action": nm.get("recommended_action", ""),
        "shipping_type": "standard",
        "currency": prs.currency.value or "EUR",
    }
    if nm_match and nm_match.pricing:
        p = nm_match.pricing
        entry.update({
            "pricing_tier_applied": p.get("tier_label", ""),
            "unit_price": p.get("unit_price", 0),
            "total_price": p.get("total_price", 0),
            "lead_time_days": p.get("standard_lead_time_days", 0),
            "standard_lead_time_days": p.get("standard_lead_time_days", 0),
            "expedited_lead_time_days": p.get("expedited_lead_time_days", 0),
            "expedited_unit_price": p.get("expedited_unit_price", 0),
            "expedited_total": p.get("expedited_total", 0),
            "quality_score": nm_match.scores.get("quality_score", 0),
            "risk_score": nm_match.scores.get("risk_score", 0),
            "esg_score": nm_match.scores.get("esg_score", 0),
            "policy_compliant": not nm_match.hard_fail,
            "covers_delivery_country": nm_match.covers_delivery_country,
            "pricing_model": p.get("pricing_model", ""),
            "pricing_id": p.get("pricing_id", ""),
            "pricing_data_source": "pricing.csv",
        })
    elif nm_match:
        entry.update({
            "quality_score": nm_match.scores.get("quality_score", 0),
            "risk_score": nm_match.scores.get("risk_score", 0),
            "esg_score": nm_match.scores.get("esg_score", 0),
            "policy_compliant": not nm_match.hard_fail,
            "covers_delivery_country": nm_match.covers_delivery_country,
            "lead_time_days": 0,
        })
    return entry


def _build_relaxed_entry_from_constraint_result(sf, prs, rank):
    """Build a constraint-relaxing shortlist entry from a deterministic
    SupplierConstraintResult that failed only soft constraints.

    This is the fallback when the LLM near-miss search didn't return enough
    suppliers. We derive the relaxed-constraint descriptions directly from
    the bitmask and constraint_details.
    """
    from backend.models.constraint import ConstraintFlag
    from backend.stages.branch_b_relaxation import _describe_relaxation

    # Identify which soft constraints failed
    failed_details = [
        d for d in sf.constraint_details if d.get("status") == "fail"
    ]
    constraints_relaxed_labels = []
    relaxed_reqs = []
    for d in failed_details:
        constraint_name = d.get("constraint", "")
        reason = d.get("reason", "")
        # Build a human-readable label
        try:
            flag = ConstraintFlag[constraint_name]
            description = _describe_relaxation(flag)
        except (KeyError, ValueError):
            description = f"Relax {constraint_name}"
        constraints_relaxed_labels.append(
            f"{constraint_name}: {reason}" if reason else constraint_name
        )
        relaxed_reqs.append({
            "requirement": constraint_name.lower().replace("_", " "),
            "original_value": "as specified",
            "supplier_value": reason or "does not meet requirement",
            "gap_description": reason or description,
            "risk_assessment": "Medium — requires human review",
        })

    entry = {
        "rank": rank,
        "supplier_id": sf.supplier_id,
        "supplier_name": sf.supplier_name,
        "preferred": sf.preferred,
        "incumbent": sf.incumbent,
        "recommendation_note": (
            f"Nearly meets specification. Soft constraints not satisfied: "
            f"{', '.join(c.get('constraint', '') for c in failed_details)}. "
            f"Penalty score: {sf.total_penalty}."
        ),
        "option_type": "constraint_relaxing",
        "constraints_relaxed": constraints_relaxed_labels,
        "relaxed_requirements": relaxed_reqs,
        "recommended_action": "Review the listed constraint gaps and approve if acceptable.",
        "shipping_type": "standard",
        "currency": prs.currency.value or "EUR",
    }
    if sf.pricing:
        p = sf.pricing
        entry.update({
            "pricing_tier_applied": p.get("tier_label", ""),
            "unit_price": p.get("unit_price", 0),
            "total_price": p.get("total_price", 0),
            "lead_time_days": p.get("standard_lead_time_days", 0),
            "standard_lead_time_days": p.get("standard_lead_time_days", 0),
            "expedited_lead_time_days": p.get("expedited_lead_time_days", 0),
            "expedited_unit_price": p.get("expedited_unit_price", 0),
            "expedited_total": p.get("expedited_total", 0),
            "quality_score": sf.scores.get("quality_score", 0),
            "risk_score": sf.scores.get("risk_score", 0),
            "esg_score": sf.scores.get("esg_score", 0),
            "policy_compliant": not sf.hard_fail,
            "covers_delivery_country": sf.covers_delivery_country,
            "pricing_model": p.get("pricing_model", ""),
            "pricing_id": p.get("pricing_id", ""),
            "pricing_data_source": "pricing.csv",
        })
    else:
        entry.update({
            "quality_score": sf.scores.get("quality_score", 0),
            "risk_score": sf.scores.get("risk_score", 0),
            "esg_score": sf.scores.get("esg_score", 0),
            "policy_compliant": not sf.hard_fail,
            "covers_delivery_country": sf.covers_delivery_country,
            "lead_time_days": 0,
        })
    return entry


def _compute_comparative_advantages(options: list[dict]):
    """Compute comparative 'why consider' text for each option based on actual data."""
    if not options:
        return

    # Collect metrics across all options for comparison
    prices = [o.get("total_price", float("inf")) for o in options]
    lead_times = [o.get("lead_time_days", float("inf")) for o in options]
    quality_scores = [o.get("quality_score", 0) for o in options]
    risk_scores = [o.get("risk_score", 100) for o in options]
    esg_scores = [o.get("esg_score", 0) for o in options]

    min_price = min(prices) if prices else 0
    min_lead = min(lead_times) if lead_times else 0
    max_quality = max(quality_scores) if quality_scores else 0
    min_risk = min(risk_scores) if risk_scores else 0
    max_esg = max(esg_scores) if esg_scores else 0

    for i, opt in enumerate(options):
        advantages = []
        price = opt.get("total_price", float("inf"))
        lead = opt.get("lead_time_days", float("inf"))
        quality = opt.get("quality_score", 0)
        risk = opt.get("risk_score", 100)
        esg = opt.get("esg_score", 0)
        currency = opt.get("currency", "EUR")
        shipping = opt.get("shipping_type", "standard")

        # Check each dimension
        if price <= min_price and price > 0:
            advantages.append(f"Lowest cost ({currency} {price:,.2f})")
        elif price > 0 and min_price > 0:
            pct_diff = ((price - min_price) / min_price) * 100
            if pct_diff <= 5:
                advantages.append(f"Near-lowest cost (+{pct_diff:.0f}% vs cheapest)")

        if lead <= min_lead and lead > 0:
            advantages.append(f"Fastest delivery ({lead}d {shipping})")
        elif lead > 0 and min_lead > 0:
            diff = lead - min_lead
            if diff <= 5:
                advantages.append(f"Near-fastest delivery (+{diff}d vs quickest)")

        if quality >= max_quality and quality > 0:
            advantages.append(f"Highest quality score ({quality}/100)")
        elif quality > 0 and quality >= max_quality - 5:
            advantages.append(f"Strong quality ({quality}/100)")

        if risk <= min_risk:
            advantages.append(f"Lowest risk ({risk}/100)")

        if esg >= max_esg and esg > 0:
            advantages.append(f"Best ESG rating ({esg}/100)")
        elif esg > 0 and esg >= max_esg - 5:
            advantages.append(f"Strong ESG ({esg}/100)")

        if opt.get("preferred"):
            advantages.append("Preferred supplier")

        if opt.get("incumbent"):
            advantages.append("Incumbent — proven track record")

        if shipping == "expedited":
            std_options = [o for o in options if o.get("supplier_id") == opt["supplier_id"] and o.get("shipping_type") == "standard"]
            if std_options:
                std_lead = std_options[0].get("lead_time_days", 0)
                if std_lead and lead < std_lead:
                    advantages.append(f"{std_lead - lead}d faster than standard shipping")

        # Handle constraint-relaxing options
        if opt.get("option_type") == "constraint_relaxing":
            relaxed = opt.get("constraints_relaxed", [])
            if relaxed:
                advantages.append(f"Requires relaxing: {'; '.join(relaxed[:2])}")

        # Construct the final why_consider line
        if advantages:
            opt["why_consider"] = ". ".join(advantages[:3])
        else:
            opt["why_consider"] = f"{shipping.capitalize()} shipping option"


def _build_job_status(
    request_id: str,
    status: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
) -> dict:
    return {
        "request_id": request_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
    }


def _build_event(
    request_id: str,
    event_type: str,
    stage: str,
    message: str,
    status: str | None = None,
    iteration: int | None = None,
    payload=None,
) -> dict:
    event = {
        "request_id": request_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "message": message,
    }
    if status is not None:
        event["status"] = status
    if iteration is not None:
        event["iteration"] = iteration
    if payload is not None:
        event["payload"] = payload
    return event


async def _emit_event(
    request_id: str,
    event_type: str,
    stage: str,
    message: str,
    status: str | None = None,
    iteration: int | None = None,
    payload=None,
) -> dict:
    event = _build_event(
        request_id=request_id,
        event_type=event_type,
        stage=stage,
        message=message,
        status=status,
        iteration=iteration,
        payload=payload,
    )
    _job_events.setdefault(request_id, []).append(event)
    for subscriber in list(_job_subscribers.get(request_id, set())):
        subscriber.put_nowait(event)
    return event


def _summarize_supplier_results(supplier_results, passing) -> dict:
    return {
        "total_candidates": len(supplier_results),
        "passing_suppliers": len(passing),
        "hard_fail_suppliers": len([s for s in supplier_results if s.hard_fail]),
        "top_candidates": [
            {
                "supplier_id": s.supplier_id,
                "supplier_name": s.supplier_name,
                "hard_fail": s.hard_fail,
                "total_penalty": s.total_penalty,
                "total_price": s.pricing.get("total_price") if s.pricing else None,
            }
            for s in supplier_results[:5]
        ],
    }
