from __future__ import annotations
import json
import logging
from typing import Any

import anthropic
from backend.config import ANTHROPIC_API_KEY, LLM_TIMEOUT_SECONDS


_client = None
logger = logging.getLogger(__name__)


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it before processing requests."
            )
        _client = anthropic.AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=LLM_TIMEOUT_SECONDS,
        )
    return _client


def _extract_text_content(response: Any) -> str:
    """Collect text across all returned content blocks."""
    text_parts: list[str] = []
    block_types: list[str] = []

    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", type(block).__name__)
        block_types.append(block_type)
        block_text = getattr(block, "text", None)
        if isinstance(block_text, str) and block_text.strip():
            text_parts.append(block_text)

    if text_parts:
        return "".join(text_parts).strip()

    stop_reason = getattr(response, "stop_reason", "unknown")
    raise RuntimeError(
        f"LLM returned no text content (stop_reason={stop_reason}, block_types={block_types})"
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_json_payload(text: str) -> Any:
    """Parse JSON from model output, tolerating fences, leading prose, and thinking blocks."""
    stripped = _strip_code_fence(text)
    if not stripped:
        raise ValueError("LLM returned an empty response")

    # Strip <thinking>...</thinking> blocks that some models emit
    import re
    stripped = re.sub(r"<thinking>.*?</thinking>", "", stripped, flags=re.DOTALL).strip()
    stripped = _strip_code_fence(stripped)

    decoder = json.JSONDecoder()

    # Try direct parse first
    try:
        return decoder.decode(stripped)
    except json.JSONDecodeError:
        pass

    # Try to find the outermost JSON object or array
    # Search for the first { or [ and find the matching closing bracket
    for idx, char in enumerate(stripped):
        if char == "{":
            # Find the last matching }
            depth = 0
            for end_idx in range(len(stripped) - 1, idx - 1, -1):
                if stripped[end_idx] == "}":
                    try:
                        candidate = stripped[idx:end_idx + 1]
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
            break
        elif char == "[":
            depth = 0
            for end_idx in range(len(stripped) - 1, idx - 1, -1):
                if stripped[end_idx] == "]":
                    try:
                        candidate = stripped[idx:end_idx + 1]
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
            break

    # Last resort: raw_decode scanning
    for idx, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[idx:])
            logger.warning("Recovered JSON payload from non-canonical LLM response")
            return payload
        except json.JSONDecodeError:
            continue

    preview = stripped[:300].replace("\n", " ")
    raise ValueError(f"LLM returned invalid JSON: {preview!r}")


async def call_llm(
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 0.0,
) -> str:
    """Call Claude API and return the text response."""
    client = get_client()
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return _extract_text_content(response)


async def call_llm_json(
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 0.0,
    max_retries: int = 2,
) -> Any:
    """Call Claude API and parse the JSON response, retrying on parse failure."""
    last_exc = None
    for attempt in range(max_retries):
        text = await call_llm(model, system, user_message, max_tokens, temperature)
        try:
            return extract_json_payload(text)
        except (ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            logger.warning(
                "JSON parse failed (attempt %d/%d): %s — response preview: %s",
                attempt + 1, max_retries, exc, text[:200],
            )
    raise last_exc
