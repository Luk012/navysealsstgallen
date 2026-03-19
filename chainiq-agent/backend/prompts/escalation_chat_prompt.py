ESCALATION_CHAT_SYSTEM = """You are a procurement escalation resolution assistant. You help human reviewers resolve blocking escalations in the procurement sourcing process.

You are given:
- The escalation details (rule, trigger, who it should be escalated to)
- The conversation history so far
- The procurement request context

Your job is to:
1. Understand the human's proposed resolution or clarification
2. Assess whether the resolution adequately addresses the escalation trigger
3. Either confirm the resolution is sufficient (mark resolved) or ask targeted follow-up questions

Be concise and practical. Focus on whether the blocking issue is genuinely addressed.

IMPORTANT: Respond with ONLY a single valid JSON object. No markdown fences, no explanation, no text before or after the JSON.

{
    "response": "your message to the human",
    "resolved": false,
    "resolution_summary": "brief summary of how the escalation was resolved (only if resolved is true, else empty string)"
}"""


UNIFIED_ESCALATION_CHAT_SYSTEM = """You are a procurement escalation resolution assistant. You help human reviewers resolve ALL open escalations in a single unified conversation.

You are given:
- ALL escalations for this procurement request (both blocking and non-blocking), with their current resolution status
- The unified conversation history
- The procurement request context

Your job is to:
1. Understand the human's message — it may address one or more escalations at once
2. Identify WHICH escalation(s) the message is addressing (by ID or by context)
3. For each addressed escalation, assess whether the response adequately resolves it
4. Provide a unified response that covers all addressed escalations
5. Remind the reviewer of any still-unresolved escalations

Be concise and practical. Guide the reviewer through resolving all escalations efficiently.

IMPORTANT: Respond with ONLY a single valid JSON object. No markdown fences, no explanation, no text before or after the JSON.

{
    "response": "your unified message to the human",
    "escalation_updates": [
        {
            "escalation_id": "ESC-001",
            "resolved": false,
            "resolution_summary": "brief summary (only if resolved is true, else empty string)"
        }
    ],
    "still_unresolved": ["ESC-002", "ESC-003"]
}"""


def build_escalation_chat_user_message(
    escalation: dict,
    chat_history: list[dict],
    request_context: dict,
) -> str:
    import json

    history_text = ""
    for msg in chat_history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        history_text += f"\n[{role.upper()}]: {content}"

    return f"""ESCALATION DETAILS:
- Escalation ID: {escalation.get('escalation_id', '')}
- Rule: {escalation.get('rule', '')}
- Trigger: {escalation.get('trigger', '')}
- Escalate To: {escalation.get('escalate_to', '')}
- Blocking: {escalation.get('blocking', True)}

REQUEST CONTEXT:
{json.dumps(request_context, indent=2)}

CONVERSATION HISTORY:{history_text}

Based on the latest message from the human, assess whether this escalation can be resolved. If the human has provided sufficient justification, approval, or corrective action, mark it as resolved. If more information is needed, ask a specific follow-up question."""


def build_unified_escalation_chat_user_message(
    escalations: list[dict],
    resolutions: dict,
    chat_history: list[dict],
    request_context: dict,
) -> str:
    import json

    # Build escalation overview
    esc_overview = []
    for esc in escalations:
        esc_id = esc.get("escalation_id", "")
        res = resolutions.get(esc_id, {})
        is_resolved = res.get("resolved", False)
        esc_overview.append({
            "escalation_id": esc_id,
            "rule": esc.get("rule", ""),
            "trigger": esc.get("trigger", ""),
            "escalate_to": esc.get("escalate_to", ""),
            "blocking": esc.get("blocking", True),
            "status": "RESOLVED" if is_resolved else "UNRESOLVED",
            "resolution_summary": res.get("resolution_summary", "") if is_resolved else "",
        })

    history_text = ""
    for msg in chat_history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        history_text += f"\n[{role.upper()}]: {content}"

    unresolved = [e for e in esc_overview if e["status"] == "UNRESOLVED"]
    resolved = [e for e in esc_overview if e["status"] == "RESOLVED"]

    return f"""ALL ESCALATIONS FOR THIS REQUEST:
{json.dumps(esc_overview, indent=2)}

UNRESOLVED COUNT: {len(unresolved)}
RESOLVED COUNT: {len(resolved)}

REQUEST CONTEXT:
{json.dumps(request_context, indent=2)}

UNIFIED CONVERSATION HISTORY:{history_text}

Based on the latest message from the human, determine which escalation(s) are being addressed. Assess whether any can be resolved. If all are resolved, congratulate the reviewer. If some remain, guide them to the next unresolved escalation."""
