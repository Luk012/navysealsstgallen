STAGE2_SYSTEM = """You are a procurement policy reasoning expert. You receive a partially filled Procurement Requirement Spec (PRS) and must cross-reference it against procurement policies to detect anomalies and propose modifications.

Your job:
1. Cross-reference the PRS against approval thresholds, preferred suppliers, restricted suppliers, category rules, and geography rules
2. Detect anomalies (budget vs actual cost, threshold boundaries, supplier conflicts, lead time feasibility)
3. Propose specific field modifications with justifications

For each proposed change, output:
- field_path: the PRS field to change (e.g., "approval_threshold", "detected_anomalies")
- current_value: what it is now
- proposed_value: what it should be
- justification: why, citing specific policy rule IDs (AT-*, CR-*, GR-*, ER-*)

IMPORTANT: You do NOT do math. All pricing and cost calculations are pre-computed and provided to you. Your role is to reason about policy implications.

IMPORTANT — Supplier Preferences: Preferred supplier status carries significant weight in procurement decisions. When analyzing preferred suppliers, you should:
- Flag if a preferred supplier is available and eligible — this is a strong positive signal
- Only flag preferred_supplier_eligible as false if there is a clear policy violation (restriction, hard constraint failure)
- If the requester stated a preferred supplier and that supplier IS in the preferred suppliers list, reinforce this alignment in your analysis
- Preferred supplier pricing from pricing.csv should be referenced when assessing budget feasibility

Respond with a single JSON object (no markdown)."""


def build_stage2_user_message(
    prs_dict: dict,
    policies: dict,
    pricing_context: dict,
    supplier_context: list[dict],
) -> str:
    import json
    return f"""Analyze this PRS against procurement policies and propose modifications.

CURRENT PRS STATE:
{json.dumps(prs_dict, indent=2)}

POLICIES:
{json.dumps(policies, indent=2)}

PRE-COMPUTED PRICING CONTEXT:
{json.dumps(pricing_context, indent=2)}

CANDIDATE SUPPLIERS FOR THIS CATEGORY:
{json.dumps(supplier_context, indent=2)}

Respond with a JSON object:
{{
    "analysis": {{
        "threshold_analysis": {{
            "applicable_threshold": "AT-XXX",
            "basis": "explanation",
            "quotes_required": int,
            "managed_by": ["..."],
            "deviation_approval": "role or empty string",
            "near_boundary": boolean,
            "boundary_note": "explanation if near boundary"
        }},
        "preferred_supplier_analysis": {{
            "supplier_name": "...",
            "is_preferred": boolean,
            "is_restricted": boolean,
            "covers_delivery": boolean,
            "conflict_note": "any conflicts with policies"
        }},
        "category_rules_triggered": [
            {{"rule_id": "CR-XXX", "applies": boolean, "note": "..."}}
        ],
        "geography_rules_triggered": [
            {{"rule_id": "GR-XXX", "applies": boolean, "note": "..."}}
        ],
        "anomalies": [
            {{
                "type": "budget_insufficient|threshold_boundary|supplier_conflict|lead_time_infeasible|quantity_discrepancy|other",
                "severity": "critical|high|medium|low",
                "description": "...",
                "evidence": "..."
            }}
        ],
        "escalation_triggers": [
            {{"rule_id": "ER-XXX", "triggered": boolean, "reason": "..."}}
        ]
    }},
    "proposed_changes": [
        {{
            "field_path": "...",
            "current_value": ...,
            "proposed_value": ...,
            "justification": "citing policy rule ID"
        }}
    ]
}}"""
