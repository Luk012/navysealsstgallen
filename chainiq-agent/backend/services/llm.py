from __future__ import annotations
import json
import anthropic
from backend.config import ANTHROPIC_API_KEY, LLM_TIMEOUT_SECONDS


_client = None


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
    return response.content[0].text


async def call_llm_json(
    model: str,
    system: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 0.0,
) -> dict:
    """Call Claude API and parse the JSON response."""
    text = await call_llm(model, system, user_message, max_tokens, temperature)
    # Extract JSON from response (handle markdown code blocks)
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())
