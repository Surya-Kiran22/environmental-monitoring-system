"""Optional LLM adapter (Anthropic / OpenAI / Gemini) over plain HTTPS.

The LLM only writes *interpretation* text from structured facts that the deterministic tools already
computed. It never supplies limits, numbers or decisions. If no provider is configured, or a call fails,
callers fall back to deterministic templates — the pipeline never depends on the LLM to run.
"""
from __future__ import annotations

import httpx

from .. import config


def enabled() -> bool:
    return (config.LLM_PROVIDER == "anthropic" and bool(config.ANTHROPIC_API_KEY)) or \
           (config.LLM_PROVIDER == "openai" and bool(config.OPENAI_API_KEY)) or \
           (config.LLM_PROVIDER == "gemini" and bool(config.GEMINI_API_KEY))


def generate(system: str, user: str, max_tokens: int = 400) -> str | None:
    if not enabled():
        return None
    try:
        if config.LLM_PROVIDER == "anthropic":
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=30, headers={
                "x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": config.LLM_MODEL or "claude-sonnet-5-5", "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"]).strip()
        if config.LLM_PROVIDER == "openai":
            r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=30,
                           headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                           json={"model": config.LLM_MODEL or "gpt-4o-mini", "max_tokens": max_tokens,
                                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        if config.LLM_PROVIDER == "gemini":
            model = config.LLM_MODEL or "gemini-2.0-flash"
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.GEMINI_API_KEY}",
                           timeout=30, json={"systemInstruction": {"parts": [{"text": system}]},
                                             "contents": [{"parts": [{"text": user}]}]})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:  # noqa: BLE001 - any provider failure falls back to templates
        return None
    return None
