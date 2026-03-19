from __future__ import annotations
import json
from backend.models.prs import PRS, PRSField
from backend.models.commit_log import CommitLog
from backend.services.llm import call_llm_json
from backend.services.prs_utils import normalize_prs_field_value
from backend.data_loader import data_store
from backend.config import MODEL_MASTERMIND, MAX_ITERATIONS
from backend.prompts.stage3_prompt import STAGE3_SYSTEM, build_stage3_user_message
from backend.stages.stage2_reasoning import run_stage2


async def run_stage2_3_loop(prs: PRS, emit=None) -> tuple[PRS, CommitLog, dict]:
    """Run the Stage 2 -> Stage 3 iteration loop until stable."""
    commit_log = CommitLog(request_id=prs.request_id)
    last_analysis = {}

    for iteration in range(MAX_ITERATIONS):
        commit_log.iteration_count = iteration + 1

        # Stage 2: Reasoning
        stage2_result = await run_stage2(prs)
        last_analysis = stage2_result.get("analysis", {})
        proposed_changes = stage2_result.get("proposed_changes", [])

        if emit:
            await emit(
                event_type="analysis",
                stage="stage2",
                iteration=iteration + 1,
                message=f"Stage 2 reasoning completed for iteration {iteration + 1}",
                payload={
                    "analysis": last_analysis,
                    "proposed_changes": proposed_changes,
                },
            )

        if not proposed_changes:
            commit_log.stable = True
            if emit:
                await emit(
                    event_type="stage_update",
                    stage="stage2",
                    iteration=iteration + 1,
                    message="No further PRS changes proposed. Stage 2/3 loop is stable.",
                )
            break

        # Stage 3: Mastermind approval
        prs_dict = json.loads(prs.model_dump_json())
        policies_summary = _build_policies_summary()

        stage3_result = await call_llm_json(
            MODEL_MASTERMIND,
            STAGE3_SYSTEM,
            build_stage3_user_message(proposed_changes, prs_dict, policies_summary),
        )

        decisions = stage3_result.get("decisions", [])
        if emit:
            await emit(
                event_type="decisions",
                stage="stage3",
                iteration=iteration + 1,
                message=f"Stage 3 reviewed {len(decisions)} proposed changes",
                payload={"decisions": decisions},
            )
        applied_any = False

        for decision in decisions:
            field_path = decision.get("field_path", "")
            approved = decision.get("approved", False)

            # Find the matching proposed change
            matching_change = next(
                (c for c in proposed_changes if c.get("field_path") == field_path),
                None,
            )
            if not matching_change:
                continue

            if approved:
                old_value = matching_change.get("current_value")
                new_value = matching_change.get("proposed_value")

                # Apply the change to the PRS
                _apply_change(prs, field_path, new_value)
                applied_any = True

                commit_log.add_commit(
                    stage="stage2",
                    iteration=iteration + 1,
                    field_path=field_path,
                    old_value=old_value,
                    new_value=new_value,
                    justification=matching_change.get("justification", ""),
                    approval_status="approved",
                    approval_rationale=decision.get("rationale", ""),
                )
            else:
                commit_log.add_commit(
                    stage="stage2",
                    iteration=iteration + 1,
                    field_path=field_path,
                    old_value=matching_change.get("current_value"),
                    new_value=matching_change.get("proposed_value"),
                    justification=matching_change.get("justification", ""),
                    approval_status="rejected",
                    approval_rationale=decision.get("rationale", ""),
                )

        if not applied_any:
            commit_log.stable = True
            if emit:
                await emit(
                    event_type="stage_update",
                    stage="stage3",
                    iteration=iteration + 1,
                    message="No approved changes were applied. Stage 2/3 loop is stable.",
                )
            break

        if stage3_result.get("stable", False):
            commit_log.stable = True
            if emit:
                await emit(
                    event_type="stage_update",
                    stage="stage3",
                    iteration=iteration + 1,
                    message="Mastermind marked the PRS as stable.",
                )
            break

    return prs, commit_log, last_analysis


def _apply_change(prs: PRS, field_path: str, new_value):
    """Apply a change to the PRS field."""
    field_name = field_path.split(".")[0]
    normalized_value = normalize_prs_field_value(field_name, new_value)
    if hasattr(prs, field_name):
        field = getattr(prs, field_name)
        if isinstance(field, PRSField):
            field.value = normalized_value
            field.source = "derived"
        elif field_name == "issues" and isinstance(normalized_value, list):
            prs.issues = normalized_value
        else:
            setattr(prs, field_name, normalized_value)


def _build_policies_summary() -> str:
    """Build a concise policies summary for the Mastermind."""
    thresholds = data_store.approval_thresholds
    summary_parts = ["APPROVAL THRESHOLDS:"]
    for t in thresholds:
        max_a = t["max_amount"]
        max_str = f"{max_a:,.2f}" if max_a and max_a < 999999999 else "unlimited"
        summary_parts.append(
            f"  {t['threshold_id']}: {t['currency']} {t['min_amount']:,.2f}–{max_str} "
            f"| {t['min_supplier_quotes']} quotes | managed by {', '.join(t['managed_by'])}"
        )

    summary_parts.append("\nRESTRICTED SUPPLIERS:")
    for r in data_store.restricted_suppliers:
        summary_parts.append(
            f"  {r['supplier_id']} ({r['supplier_name']}): {r['category_l1']}/{r.get('category_l2', '*')} "
            f"scope={r['restriction_scope']} — {r['restriction_reason']}"
        )

    return "\n".join(summary_parts)
