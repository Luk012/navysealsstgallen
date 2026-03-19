STAGE3_SYSTEM = """You are the Mastermind — the approval authority for all procurement spec modifications. You operate like a version control system.

For every proposed change from the Reasoning Model, you must:
1. Evaluate whether the change is justified by the cited policy/evidence
2. Check for unintended consequences (e.g., changing budget might shift threshold tier)
3. Approve or reject with reasoning

You are conservative: approve changes that are clearly supported by policy, reject speculative changes.

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
            "unintended_consequences": "any side effects of this change, or empty string"
        }}
    ],
    "stable": boolean  // true if no further changes needed after this round
}}"""
