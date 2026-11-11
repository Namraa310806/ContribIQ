"""Minimal OpenAI-compatible chat helper — one configured endpoint for all LLM calls.

Env:
  LLM_API_KEY   — required; any OpenAI-compatible provider key (OpenAI, OpenRouter,
                  Groq, Together, a local vLLM/Ollama server, etc.)
  LLM_BASE_URL  — default https://api.openai.com/v1
  LLM_MODEL     — default gpt-4o-mini

Callers treat failures as "LLM unavailable" and fall back to heuristics/templates,
so `chat` may raise — never call it outside a try/except.
"""

import os
from typing import Optional

import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def is_configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


async def chat(system: str, user: str, *, model: Optional[str] = None, timeout: float = 60.0) -> str:
    """Single-turn chat completion; returns the assistant message content."""
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not set")
    base = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""
