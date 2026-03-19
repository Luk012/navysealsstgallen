REEVALUATION_SYSTEM = """You are a procurement sourcing specialist performing a post-escalation re-evaluation. All blocking escalations have been resolved by human reviewers and you must now update the procurement recommendation to reflect the resolutions.

You are given:
- The original processing result (interpretation, policy, suppliers, recommendation, audit trail)
- The escalation resolutions with their chat histories and summaries
- The original PRS (Procurement Requirement Spec)

Your job is to:
1. Review each escalation resolution and understand what was decided
2. Re-assess the supplier ranking in light of the resolutions (e.g. a previously blocked supplier may now be viable, budget may have been adjusted, missing info may have been provided)
3. Update the recommendation to reflect a FINAL (non-provisional) status
4. Update any interpretation, policy evaluation, or validation fields that changed due to resolutions
5. Note in the audit trail that a post-escalation re-evaluation was performed

Be precise. Only change fields that are directly affected by the escalation resolutions. Do not invent new information beyond what the resolutions provide.

Respond with a single JSON object (no markdown):
{
    "recommendation": {
        "status": "proceed|cannot_proceed|requires_relaxation",
        "reason": "updated recommendation summary incorporating escalation resolutions",
        "preferred_supplier_if_resolved": "supplier name",
        "preferred_supplier_rationale": "updated rationale"
    },
    "interpretation_updates": {
        "field_name": "new_value"
    },
    "policy_updates": {
        "field_name": "new_value"
    },
    "validation_updates": {
        "issues_to_remove": ["issue_id_1"],
        "issues_to_add": []
    },
    "supplier_ranking_changes": {
        "rerank": true/false,
        "rationale": "why ranking changed or stayed the same",
        "updated_notes": {
            "supplier_id": "updated recommendation note"
        }
    },
    "audit_note": "brief description of what changed during re-evaluation"
}"""


def build_reevaluation_user_message(
    result: dict,
    escalation_resolutions: dict,
) -> str:
    import json

    # Build resolution summaries
    resolution_details = []
    for esc in result.get("escalations", []):
        esc_id = esc.get("escalation_id", "")
        res = escalation_resolutions.get(esc_id, {})
        resolution_details.append({
            "escalation_id": esc_id,
            "rule": esc.get("rule", ""),
            "trigger": esc.get("trigger", ""),
            "blocking": esc.get("blocking", False),
            "resolved": res.get("resolved", False),
            "resolution_summary": res.get("resolution_summary", ""),
            "chat_history": res.get("chat_history", []),
        })

    return f"""POST-ESCALATION RE-EVALUATION

All escalations have been resolved. Re-evaluate the procurement output.

ORIGINAL RECOMMENDATION:
{json.dumps(result.get("recommendation", {}), indent=2)}

ORIGINAL INTERPRETATION:
{json.dumps(result.get("request_interpretation", {}), indent=2)}

POLICY EVALUATION:
{json.dumps(result.get("policy_evaluation", {}), indent=2)}

SUPPLIER SHORTLIST:
{json.dumps(result.get("supplier_shortlist", []), indent=2)}

ESCALATION RESOLUTIONS:
{json.dumps(resolution_details, indent=2)}

BRANCH: {result.get("branch", "A")}
RELAXATIONS: {json.dumps(result.get("relaxations", []), indent=2)}

Based on the escalation resolutions, update the recommendation and any affected fields. The recommendation should now be FINAL (not provisional)."""
