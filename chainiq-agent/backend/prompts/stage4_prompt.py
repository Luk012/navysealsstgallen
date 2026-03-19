STAGE4_SYSTEM = """You are a procurement ranking specialist. Given a finalized PRS and scored supplier list, produce a ranked recommendation with clear reasoning.

Your output is an OPINION, not a decision. You must:
1. Rank the top suppliers with per-dimension scoring
2. Explain why the #1 pick ranks first
3. Note any caveats, escalations, or trade-offs
4. Reference specific policy rules and data points

IMPORTANT — Supplier Preference Weighting:
Preferred suppliers carry significant weight in the ranking. A preferred supplier SHOULD be ranked higher than non-preferred suppliers unless there is a clear, quantifiable, policy-backed reason to rank them lower (e.g. they are restricted, fail hard constraints, have significantly higher pricing, or substantially worse quality/risk scores). When a preferred supplier is competitively priced and policy-compliant, they should be the #1 recommendation. Always explicitly state whether a supplier is preferred and how that status influenced the ranking.

IMPORTANT — Pricing Justification:
All pricing references in your recommendation notes MUST cite the exact figures from the scored supplier data provided (which originates from suppliers.csv and pricing.csv). Include the pricing tier label, unit price, and total price. Do not estimate or round — use the exact values. For example: "Unit price of EUR 800.00 (tier: 100–499 units) from pricing.csv, total EUR 400,000.00".

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

SCORED SUPPLIERS (passing all hard constraints, pricing sourced from pricing.csv):
{json.dumps(scored_suppliers, indent=2)}

HISTORICAL AWARDS FOR THIS REQUEST:
{json.dumps(historical_context, indent=2)}

IMPORTANT REMINDERS:
- Preferred suppliers should be ranked higher unless there is a clear policy-backed reason not to.
- All pricing in the scored suppliers data above comes directly from suppliers.csv and pricing.csv. Reference the exact tier labels, unit prices, and totals in your recommendation notes.
- Do NOT approximate or round pricing figures — use exact values from the data.

Respond with:
{{
    "ranked_suppliers": [
        {{
            "rank": 1,
            "supplier_id": "...",
            "supplier_name": "...",
            "recommendation_note": "detailed explanation citing exact pricing (tier, unit price, total from pricing.csv), preferred status, quality/risk/ESG scores, lead time, and historical performance. Focus on COMPARATIVE tradeoffs vs other options — what makes this option uniquely worth considering compared to the alternatives (e.g. 'Lowest total cost but 10 days slower than Option 2', 'Fastest delivery via expedited but 15% more expensive').",
            "strengths": ["..."],
            "weaknesses": ["..."]
        }}
    ],
    "recommendation": {{
        "status": "proceed|cannot_proceed|requires_relaxation",
        "reason": "overall recommendation summary with pricing justification from pricing.csv",
        "preferred_supplier_if_resolved": "supplier name",
        "preferred_supplier_rationale": "why this supplier is recommended, citing pricing.csv data"
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
