"""On-prem LLM client: thin OpenAI-compatible httpx wrapper.
Works with Ollama (http://localhost:11434/v1) and vLLM out of the box;
any compatible endpoint is a config value (plan section 6.7)."""
from __future__ import annotations

import httpx

from ..config import settings


class LLMUnavailable(Exception):
    pass


def model_size_b(model: str | None) -> float | None:
    """Rough parameter-count hint parsed from names like 'qwen3:0.6b'."""
    import re
    if not model:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", model)
    return float(m.group(1)) if m else None


def chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    temperature: float = 0.2,
    base_url: str | None = None,
    model: str | None = None,
    tool_choice: str | None = None,
) -> dict:
    """Non-streaming completion. Raises LLMUnavailable on connection errors."""
    url = (base_url or settings.ai_base_url).rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": model or settings.ai_model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            timeout=settings.ai_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPError) as e:
        raise LLMUnavailable(str(e)) from e


def probe(base_url: str | None = None, model: str | None = None) -> dict:
    """Check that a local model endpoint is reachable and pick a usable model.

    Falls back to the first installed model when the configured one is missing,
    so a partially set-up Ollama still powers the agent instead of degrading
    silently to the offline analyst while the badge says "online".
    """
    base = (base_url or settings.ai_base_url).rstrip("/")
    target = model or settings.ai_model
    try:
        r = httpx.get(f"{base}/models", timeout=5.0)
        r.raise_for_status()
        models = [m.get("id", "") for m in r.json().get("data", [])]
        # Ollama lists e.g. "qwen2.5:32b-instruct"; tolerate partial match
        found = any(target in m or m in target for m in models) if models else True
        effective = target if found or not models else models[0]
        size = model_size_b(effective)
        mode = ("llm" if size is None or size >= settings.ai_min_model_b
                else "deterministic")
        return {"available": True, "models": models[:20],
                "target_model": effective, "model_found": found,
                "configured_model": target, "mode": mode,
                "min_model_b": settings.ai_min_model_b}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e), "target_model": target}
