"""The only module that talks to DeepSeek.

Every model call goes through call_json(), which asks for a JSON object,
retries once if DeepSeek returns empty or invalid JSON, and reports where
the answer came from so the interaction log can record it.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from .config import get_settings


class LLMError(Exception):
    """DeepSeek could not be reached or did not return usable JSON.

    detail holds what the interaction log needs to diagnose it (never shown to the student)."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


# Tests replace this with a fake client; the app uses the OpenAI SDK.
_client_factory: Callable[[], Any] | None = None


def set_client_factory(factory: Callable[[], Any] | None) -> None:
    global _client_factory
    _client_factory = factory


def _make_client():
    if _client_factory is not None:
        return _client_factory()
    s = get_settings()
    if not s.api_key:
        raise LLMError("No DEEPSEEK_API_KEY set. Add your key to .env.")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise LLMError("The 'openai' package is not installed (pip install -r requirements.txt).") from exc
    return OpenAI(api_key=s.api_key, base_url=s.base_url)


def call_json(purpose: str, messages: list[dict], max_tokens: int = 1500) -> tuple[dict, dict]:
    """Send one chat request that must return a JSON object.

    Returns (data, meta); meta is written to the interaction log.
    """
    s = get_settings()
    client = _make_client()
    data = None
    attempts = 0
    finish_reasons: list[str] = []
    content = ""
    t0 = time.perf_counter()
    # DeepSeek's JSON mode can occasionally return empty content, so retry once.
    for _ in range(2):
        attempts += 1
        try:
            resp = client.chat.completions.create(
                model=s.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                **({"extra_body": s.extra_body} if s.extra_body else {}),
            )
        except Exception as exc:  # network, auth, rate limit ...
            raise LLMError(f"DeepSeek request failed: {exc}") from exc
        choice = resp.choices[0]
        finish_reasons.append(str(getattr(choice, "finish_reason", None)))
        content = (choice.message.content or "").strip()
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                break
            data = None
        except json.JSONDecodeError:
            data = None
    latency_ms = int((time.perf_counter() - t0) * 1000)
    if data is None:
        detail = {"finish_reasons": finish_reasons, "chars": len(content), "tail": content[-200:]}
        if "length" in finish_reasons:
            raise LLMError("DeepSeek's reply was cut off before the JSON was complete.", detail)
        raise LLMError("DeepSeek did not return valid JSON after 2 attempts.", detail)
    return data, {"model": s.model, "latency_ms": latency_ms, "attempts": attempts,
                  "finish_reason": finish_reasons[-1]}
