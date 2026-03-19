NEAR_MISS_SYSTEM = """You are a procurement near-miss analyst. Given a finalized PRS and suppliers that failed one or more soft constraints, identify suppliers that are "near-miss" options -- they almost satisfy the requirements and could be viable if the requester accepts specific trade-offs.

IMPORTANT: These suppliers do NOT fully satisfy the specification. You must:
1. Clearly state which requirement(s) each supplier does NOT meet
2. Quantify the gap (e.g., "12% over budget", "5 days past deadline")
3. Explain why this supplier might still be worth considering despite the gap
4. Assess the risk of accepting each trade-off
5. Suggest a concrete action the requester could take to approve the option

Be honest and conservative. Do not oversell near-miss options. The human reviewer must have full transparency to make an informed decision.

Respond with a single JSON object (no markdown)."""


def build_near_miss_user_message(
    prs_dict: dict,
    soft_fail_suppliers: list[dict],
    passing_supplier_ids: list[str],
) -> str:
    import json
    return f"""Identify near-miss supplier options from the soft-fail suppliers below.
These suppliers failed one or more soft constraints but did NOT fail any hard constraints.
They are NOT in the current viable set.

FINALIZED PRS:
{json.dumps(prs_dict, indent=2)}

ALREADY VIABLE SUPPLIER IDS (do not include these):
{json.dumps(passing_supplier_ids, indent=2)}

SOFT-FAIL SUPPLIERS (failed soft constraints only):
{json.dumps(soft_fail_suppliers, indent=2)}

For each near-miss supplier, analyze the gap between requirements and what the supplier offers.

Respond with:
{{
    "near_miss_suppliers": [
        {{
            "supplier_id": "...",
            "supplier_name": "...",
            "relaxed_requirements": [
                {{
                    "requirement": "name of the requirement not met (e.g. budget, lead_time, esg)",
                    "original_value": "what the PRS requires",
                    "supplier_value": "what the supplier offers",
                    "gap_description": "quantified gap (e.g. '12% over budget', '5 days late')",
                    "risk_assessment": "Low/Medium/High risk with brief explanation"
                }}
            ],
            "overall_near_miss_rationale": "why this supplier is still worth considering",
            "recommended_action": "specific action for the reviewer (e.g. 'Approve if budget can be increased by 12%')"
        }}
    ]
}}

Only include suppliers where the gap is reasonably small and the trade-off is worth presenting to a human reviewer. Do not include suppliers with large gaps that are clearly not viable."""
