STAGE3_SYSTEM = """You are the Mastermind — the approval authority for all procurement spec modifications. You operate like a version control system.

For every proposed change from the Reasoning Model, you must:
1. Evaluate whether the change is justified by the cited policy/evidence
2. Check for unintended consequences (e.g., changing budget might shift threshold tier)
3. Approve or reject with reasoning

You are conservative: approve changes that are clearly supported by policy, reject speculative changes.

When approving a change, you may optionally set a confidence_override (0.0-1.0) if the new value's certainty differs from the original. For example, a value derived from policy inference should have lower confidence than one explicitly stated by the requester.

Respond with a single JSON object (no markdown)."""


def build_stage3_user_message(
    proposed_changes: list[dict],
    prs_dict: dict,
    policies_summary: str,
) -> str:
    import json
    return f"""Review these proposed PRS modifications and approve or reject each one.

PROPOSED CHANGES:
{json.dumps(proposed_changes, indent=2)}

CURRENT PRS STATE:
{json.dumps(prs_dict, indent=2)}

POLICY SUMMARY:
{policies_summary}

For each proposed change, respond with:
{{
    "decisions": [
        {{
            "field_path": "the field being changed",
            "approved": boolean,
            "rationale": "why approved or rejected, referencing specific evidence or policy rules",
            "unintended_consequences": "any side effects of this change, or empty string",
            "confidence_override": null or float  // optional: set if this change warrants a different confidence level, null to keep automatic
        }}
    ],
    "stable": boolean  // true if no further changes needed after this round
}}"""
