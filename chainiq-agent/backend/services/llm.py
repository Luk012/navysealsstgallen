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
    """Parse JSON from model output, tolerating fences and leading prose."""
    stripped = _strip_code_fence(text)
    if not stripped:
        raise ValueError("LLM returned an empty response")

    decoder = json.JSONDecoder()
    try:
        return decoder.decode(stripped)
    except json.JSONDecodeError:
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
) -> Any:
    """Call Claude API and parse the JSON response."""
    text = await call_llm(model, system, user_message, max_tokens, temperature)
    return extract_json_payload(text)
