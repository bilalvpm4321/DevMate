"""Multi-provider LLM service with Google Gemini as primary and OpenRouter as automatic fallback."""
import logging
from typing import Any

import httpx
from fastapi import HTTPException

from ..config import settings

logger = logging.getLogger("devmate.llm")

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

OFFLINE_NOTICE = (
    "> **Offline mode:** no `GEMINI_API_KEY` or `OPENROUTER_API_KEY` is set, so DevMate cannot call an AI model yet. "
    "Add an API key to your `.env` file to get full answers."
)


def _extract_gemini_text(data: dict[str, Any]) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        return ""


def _extract_openrouter_text(data: dict[str, Any]) -> str:
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


async def _call_gemini(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    prompt: str,
    history: list[dict] | None = None,
) -> tuple[int, str, str]:
    """Calls Google Generative Language REST API. Returns (status_code, text, error_msg)."""
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in (history or [])
    ]
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192},
    }

    try:
        resp = await client.post(
            _GEMINI_URL.format(model=model),
            params={"key": settings.gemini_api_key},
            json=body,
        )
    except httpx.HTTPError as exc:
        return 0, "", f"Gemini connection error: {exc}"

    if resp.status_code == 200:
        text = _extract_gemini_text(resp.json())
        return 200, text, ""

    # Parse error detail
    err_msg = ""
    try:
        err_msg = resp.json().get("error", {}).get("message", "")
    except Exception:
        err_msg = resp.text[:200]
    return resp.status_code, "", err_msg


async def _call_openrouter(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    prompt: str,
    history: list[dict] | None = None,
) -> tuple[int, str, str]:
    """Calls OpenRouter Chat Completions endpoint. Returns (status_code, text, error_msg)."""
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "https://github.com/bilalvpm4321/DevMate",
        "X-Title": "DevMate",
        "Content-Type": "application/json",
    }

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    for m in (history or []):
        messages.append({
            "role": "assistant" if m["role"] == "assistant" else "user",
            "content": m["content"],
        })
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8192,
    }

    try:
        resp = await client.post(_OPENROUTER_URL, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return 0, "", f"OpenRouter connection error: {exc}"

    if resp.status_code == 200:
        text = _extract_openrouter_text(resp.json())
        return 200, text, ""

    err_msg = ""
    try:
        err_msg = resp.json().get("error", {}).get("message", "")
    except Exception:
        err_msg = resp.text[:200]
    return resp.status_code, "", err_msg


async def generate(system: str, prompt: str, history: list[dict] | None = None) -> str:
    """Dispatches generation to Gemini, seamlessly falling back to OpenRouter upon rate limits or failures."""
    has_gemini = bool(settings.gemini_api_key)
    has_openrouter = bool(settings.openrouter_api_key)

    if not has_gemini and not has_openrouter:
        return ""

    async with httpx.AsyncClient(timeout=90) as client:
        # 1. Primary: Google Gemini
        if has_gemini:
            status, text, err = await _call_gemini(client, settings.gemini_model, system, prompt, history)
            if status == 200 and text:
                return text

            # If model was deprecated/not found, retry once with gemini-3.5-flash-lite
            if status == 404 and settings.gemini_model != "gemini-3.5-flash-lite":
                status, text, err = await _call_gemini(client, "gemini-3.5-flash-lite", system, prompt, history)
                if status == 200 and text:
                    return text

            # Check if Gemini hit rate limits, quota limits, overload, or connection errors
            is_limit_or_error = (
                status in (429, 500, 502, 503, 504, 404, 0)
                or "quota" in err.lower()
                or "resource_exhausted" in err.lower()
                or "rate" in err.lower()
            )

            if is_limit_or_error and has_openrouter:
                logger.warning(
                    "Gemini API limit/failure encountered (status=%s, msg='%s'). "
                    "Flipping to OpenRouter fallback (%s)...",
                    status, err, settings.openrouter_model,
                )
                print(f"[LLM] Gemini limit reached (status {status}). Activating OpenRouter fallback ({settings.openrouter_model})...")

                or_status, or_text, or_err = await _call_openrouter(
                    client, settings.openrouter_model, system, prompt, history
                )
                if or_status == 200 and or_text:
                    return or_text

                # If primary model failed on OpenRouter, attempt openrouter/auto
                if or_status != 200 and settings.openrouter_model != "openrouter/auto":
                    or_status, or_text, or_err = await _call_openrouter(
                        client, "openrouter/auto", system, prompt, history
                    )
                    if or_status == 200 and or_text:
                        return or_text

                raise HTTPException(
                    502,
                    f"AI service error: Gemini limit hit ({status}: {err}), and OpenRouter fallback failed ({or_status}: {or_err}).",
                )

            # OpenRouter is not configured, report Gemini error directly
            raise HTTPException(502, f"AI service error ({status}): {err or 'Check your API key and model name.'}")

        # 2. Standalone OpenRouter (when Gemini key is omitted)
        if has_openrouter:
            or_status, or_text, or_err = await _call_openrouter(
                client, settings.openrouter_model, system, prompt, history
            )
            if or_status == 200 and or_text:
                return or_text
            raise HTTPException(502, f"OpenRouter AI error ({or_status}): {or_err}")

    return ""
