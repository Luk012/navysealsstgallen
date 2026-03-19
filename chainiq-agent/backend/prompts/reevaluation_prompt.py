REEVALUATION_SYSTEM = """You are a procurement sourcing specialist performing a post-escalation re-evaluation. All blocking escalations have been resolved by human reviewers and you must now update the procurement recommendation to reflect the resolutions.

You are given:
- The original processing result (interpretation, policy, suppliers, recommendation, audit trail)
- The escalation resolutions with their chat histories and summaries
- The original PRS (Procurement Requirement Spec)
- The current supplier pricing data from suppliers.csv and pricing.csv

Your job is to:
1. Review each escalation resolution and understand what was decided
2. **CLEANUP stale data**: Remove any detected anomalies, validation issues, or escalation flags that are no longer relevant after resolution. For example, if an escalation was about missing information and that information was provided, remove the corresponding anomaly and validation issue.
3. Re-assess the supplier ranking in light of the resolutions (e.g. a previously blocked supplier may now be viable, budget may have been adjusted, missing info may have been provided). Use the pricing data provided to justify any ranking changes with exact figures from suppliers.csv/pricing.csv.
4. Update the recommendation to reflect a FINAL (non-provisional) status
5. **Fully re-evaluate ALL output sections**: Update interpretation, policy evaluation, validation, supplier shortlist, and escalation status fields. Every output tab must reflect the post-resolution state accurately.
6. Note in the audit trail that a post-escalation re-evaluation was performed
7. Identify any anomalies that existed before escalation that are now resolved and should be cleaned up

IMPORTANT — Supplier preferences: When re-ranking suppliers, give significant weight to preferred supplier status. A preferred supplier should be ranked higher unless there is a clear, policy-backed reason to rank them lower (e.g. restricted, fails hard constraints, or significantly worse on price/quality).

IMPORTANT — Pricing justification: All pricing references in your output must cite specific data from suppliers.csv and pricing.csv (tier labels, unit prices, total prices). Do not estimate or approximate — use the exact figures provided.

Be precise. Only change fields that are directly affected by the escalation resolutions. Do not invent new information beyond what the resolutions provide.

IMPORTANT: Respond with ONLY a single valid JSON object. No markdown fences, no explanation, no text before or after the JSON.

{
    "recommendation": {
        "status": "proceed|cannot_proceed|requires_relaxation",
        "reason": "updated recommendation summary incorporating escalation resolutions",
        "preferred_supplier_if_resolved": "supplier name",
        "preferred_supplier_rationale": "updated rationale referencing pricing.csv data"
    },
    "interpretation_updates": {
        "field_name": "new_value"
    },
    "policy_updates": {
        "field_name": "new_value"
    },
    "validation_updates": {
        "issues_to_remove": ["issue_id_1"],
        "issues_to_add": [],
        "anomalies_to_remove": ["anomaly description or type to clean up"]
    },
    "supplier_ranking_changes": {
        "rerank": true,
        "rationale": "why ranking changed or stayed the same, citing pricing.csv figures",
        "updated_notes": {
            "supplier_id": "updated recommendation note with pricing justification"
        },
        "updated_ranks": [
            {
                "supplier_id": "...",
                "supplier_name": "...",
                "new_rank": 1,
                "recommendation_note": "justification citing pricing.csv tier and unit price",
                "strengths": ["..."],
                "weaknesses": ["..."]
            }
        ]
    },
    "escalation_status_updates": {
        "resolved_escalation_ids": ["ESC-001"],
        "updated_escalations": [
            {
                "escalation_id": "ESC-001",
                "blocking": false,
                "resolution_note": "Resolved via human review"
            }
        ]
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

    # Include current validation issues and anomalies for cleanup review
    validation = result.get("validation", {})
    current_issues = validation.get("issues_detected", [])

    # Include current escalations with their status
    current_escalations = result.get("escalations", [])

    return f"""POST-ESCALATION RE-EVALUATION

All escalations have been resolved. Re-evaluate the procurement output.
You MUST clean up any stale anomalies, validation issues, and escalation flags that are no longer relevant after escalation resolution.
You MUST re-evaluate ALL output tabs: Interpretation, Suppliers, Escalation, and Audit Trail.

ORIGINAL RECOMMENDATION:
{json.dumps(result.get("recommendation", {}), indent=2)}

ORIGINAL INTERPRETATION:
{json.dumps(result.get("request_interpretation", {}), indent=2)}

POLICY EVALUATION:
{json.dumps(result.get("policy_evaluation", {}), indent=2)}

SUPPLIER SHORTLIST (with pricing from pricing.csv):
{json.dumps(result.get("supplier_shortlist", []), indent=2)}

EXCLUDED SUPPLIERS:
{json.dumps(result.get("suppliers_excluded", []), indent=2)}

CURRENT VALIDATION ISSUES (review for cleanup):
{json.dumps(current_issues, indent=2)}

CURRENT ESCALATIONS (update status for resolved ones):
{json.dumps(current_escalations, indent=2)}

ESCALATION RESOLUTIONS:
{json.dumps(resolution_details, indent=2)}

AUDIT TRAIL:
{json.dumps(result.get("audit_trail", {}), indent=2)}

BRANCH: {result.get("branch", "A")}
RELAXATIONS: {json.dumps(result.get("relaxations", []), indent=2)}

INSTRUCTIONS:
1. Review each escalation resolution and clean up any anomalies/issues that are now resolved.
2. Re-rank suppliers if resolutions affect viability — reference exact pricing figures from the supplier shortlist data.
3. Update ALL output tabs (interpretation, policy, validation, suppliers, escalations) to reflect the post-resolution state.
4. Mark the recommendation as FINAL (not provisional).
5. Give preferred suppliers significant weight in ranking unless policy prevents it.
6. Justify pricing decisions by citing the exact tier labels and unit prices shown in the supplier data above."""
