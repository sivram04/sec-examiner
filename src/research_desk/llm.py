"""Single entry point for LLM calls. Point LLM_BASE_URL at the Project 1 gateway later.

Free tiers enforce requests-per-minute limits, so calls are paced client-side
(LLM_MIN_INTERVAL seconds apart), and 429/5xx responses are retried with backoff that honours
Retry-After. Every call's latency and token usage is appended to `USAGE` for cost logs.
"""
import re
import threading
import time

import httpx

from .config import settings

RETRY_STATUS = {429, 500, 502, 503, 504}
USAGE: list[dict] = []
_lock = threading.Lock()
_last_call = 0.0


def _pace() -> None:
    global _last_call
    with _lock:
        wait = _last_call + settings.llm_min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    if h := resp.headers.get("retry-after"):
        try:
            return float(h)
        except ValueError:
            pass
    # Gemini puts the hint in the body: "retryDelay": "17s"
    if m := re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', resp.text):
        return float(m.group(1)) + 1
    return min(90.0, 5.0 * 2 ** attempt)


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.0,
         retries: int = 8) -> str:
    model = model or settings.llm_model
    for attempt in range(retries + 1):
        _pace()
        t0 = time.time()
        try:
            resp = httpx.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={"model": model, "messages": messages, "temperature": temperature},
                timeout=120,
            )
        except httpx.TransportError:  # dropped/reset connections happen on free tiers too
            if attempt == retries:
                raise
            time.sleep(min(90.0, 5.0 * 2 ** attempt))
            continue
        if resp.status_code in RETRY_STATUS and attempt < retries:
            time.sleep(_retry_after(resp, attempt))
            continue
        resp.raise_for_status()
        body = resp.json()
        u = body.get("usage") or {}
        USAGE.append({"model": model, "secs": round(time.time() - t0, 2),
                      "prompt_tokens": u.get("prompt_tokens"),
                      "completion_tokens": u.get("completion_tokens")})
        return body["choices"][0]["message"]["content"] or ""
    raise RuntimeError("unreachable")
