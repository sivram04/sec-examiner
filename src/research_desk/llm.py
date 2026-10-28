"""Single entry point for LLM calls. Point LLM_BASE_URL at the Project 1 gateway later.

Free tiers return 429 (rate limit) and 503 (overloaded) routinely, so those are retried with
exponential backoff; every call's latency and token usage is appended to `USAGE` for cost logs.
"""
import time

import httpx

from .config import settings

RETRY_STATUS = {429, 500, 502, 503, 504}
USAGE: list[dict] = []


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.0,
         retries: int = 5) -> str:
    model = model or settings.llm_model
    for attempt in range(retries + 1):
        t0 = time.time()
        resp = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": model, "messages": messages, "temperature": temperature},
            timeout=120,
        )
        if resp.status_code in RETRY_STATUS and attempt < retries:
            time.sleep(min(60, 2 ** attempt * 2))
            continue
        resp.raise_for_status()
        body = resp.json()
        u = body.get("usage") or {}
        USAGE.append({"model": model, "secs": round(time.time() - t0, 2),
                      "prompt_tokens": u.get("prompt_tokens"),
                      "completion_tokens": u.get("completion_tokens")})
        return body["choices"][0]["message"]["content"] or ""
    raise RuntimeError("unreachable")
