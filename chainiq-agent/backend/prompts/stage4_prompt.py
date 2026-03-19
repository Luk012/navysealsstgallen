STAGE4_SYSTEM = """You are a procurement ranking specialist. Given a finalized PRS and scored supplier list, produce a ranked recommendation with clear reasoning.

Your output is an OPINION, not a decision. You must:
1. Rank the top suppliers with per-dimension scoring
2. Explain why the #1 pick ranks first
3. Note any caveats, escalations, or trade-offs
4. Reference specific policy rules and data points

Respond with a single JSON object (no markdown)."""


def build_stage4_user_message(
    prs_dict: dict,
    scored_suppliers: list[dict],
    historical_context: list[dict],
) -> str:
    import json
    return f"""Rank these suppliers and produce a recommendation.

FINALIZED PRS:
{json.dumps(prs_dict, indent=2)}

SCORED SUPPLIERS (passing all hard constraints):
{json.dumps(scored_suppliers, indent=2)}

HISTORICAL AWARDS FOR THIS REQUEST:
{json.dumps(historical_context, indent=2)}

Respond with:
{{
    "ranked_suppliers": [
        {{
            "rank": 1,
            "supplier_id": "...",
            "supplier_name": "...",
            "recommendation_note": "detailed explanation of why this supplier ranks here, referencing price, lead time, quality, risk, ESG, historical performance, preferred status",
            "strengths": ["..."],
            "weaknesses": ["..."]
        }}
    ],
    "recommendation": {{
        "status": "proceed|cannot_proceed|requires_relaxation",
        "reason": "overall recommendation summary",
        "preferred_supplier_if_resolved": "supplier name",
        "preferred_supplier_rationale": "why this supplier is recommended"
    }},
    "escalations": [
        {{
            "rule": "ER-XXX or AT-XXX",
            "trigger": "what triggered it",
            "escalate_to": "role",
            "blocking": boolean
        }}
    ]
}}"""
