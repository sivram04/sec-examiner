"""Single entry point for LLM calls. Point LLM_BASE_URL at the Project 1 gateway later."""
import httpx

from .config import settings


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.0) -> str:
    resp = httpx.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": model or settings.llm_model, "messages": messages,
              "temperature": temperature},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
