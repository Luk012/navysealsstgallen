"""Prompt for batched qualitative policy verification (Phase 3).

This prompt is used when deterministic and gate checks have identified
rules that require LLM interpretation. All applicable qualitative and
gated semi-deterministic rules are bundled into a single LLM call.
"""

VERIFICATION_SYSTEM_PROMPT = """\
You are a procurement policy compliance auditor. Your task is to evaluate
whether a procurement request complies with a set of policy rules.

For each rule provided, determine compliance based ONLY on evidence found
in the request text and structured fields. Be conservative: if evidence
is absent or ambiguous, mark as non-compliant with lower confidence.

Return ONLY a JSON array with no additional text. Each element must have:
- "rule_id": string — the rule identifier
- "compliant": boolean — true if the request meets the rule, false otherwise
- "confidence": float 0.0-1.0 — how confident you are in this judgment
- "reasoning": string — brief explanation (1-2 sentences) citing evidence or lack thereof
- "evidence_found": string — direct quote from request text if applicable, or "none"

Confidence guidelines:
- 0.9-1.0: Clear, explicit evidence in request text
- 0.7-0.89: Strong implication but not explicitly stated
- 0.5-0.69: Ambiguous or indirect evidence
- 0.0-0.49: No evidence found, defaulting to non-compliant
"""


def build_verification_user_message(
    request_text: str,
    prs_summary: dict,
    rules_to_evaluate: list[dict],
) -> str:
    """Build the user message for the batched verification LLM call.

    Args:
        request_text: Original procurement request text.
        prs_summary: Key structured fields from the PRS.
        rules_to_evaluate: List of dicts, each with:
            - rule_id: str
            - rule_text: str
            - section: str (category_rules, geography_rules, escalation_rules)
            - deterministic_context: str (what the gate check already determined)
            - question: str (specific question for the LLM)
    """
    import json

    prs_block = json.dumps(prs_summary, indent=2, default=str)
    rules_block = json.dumps(rules_to_evaluate, indent=2, default=str)

    return f"""\
## Procurement Request

### Original Request Text
{request_text}

### Structured Fields (extracted from request)
{prs_block}

## Policy Rules to Evaluate
{rules_block}

Evaluate each rule and return a JSON array. Remember:
- Base your judgment on evidence in the request text and structured fields
- If no evidence is found for a requirement, mark compliant=false with low confidence
- Be specific about what evidence you found or did not find
"""
