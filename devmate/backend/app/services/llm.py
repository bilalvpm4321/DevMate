"""LLM access (Google Gemini REST API) with an offline fallback so the app always runs."""
import httpx
from fastapi import HTTPException

from ..config import settings

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

OFFLINE_NOTICE = (
    "> **Offline mode:** no `GEMINI_API_KEY` is set, so DevMate cannot call an AI model yet. "
    "Add a free key to your `.env` file to get full answers."
)


async def generate(system: str, prompt: str, history: list[dict] | None = None) -> str:
    """Return the model's reply. `history` items look like {"role": "user"|"assistant", "content": str}."""
    if not settings.gemini_api_key:
        return ""
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
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                _URL.format(model=settings.gemini_model),
                params={"key": settings.gemini_api_key},
                json=body,
            )
            # If configured model is deprecated or not found (404), fallback to gemini-3.5-flash-lite
            if resp.status_code == 404 and settings.gemini_model != "gemini-3.5-flash-lite":
                resp = await client.post(
                    _URL.format(model="gemini-3.5-flash-lite"),
                    params={"key": settings.gemini_api_key},
                    json=body,
                )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach the AI service: {exc}") from exc
    if resp.status_code != 200:
        err_msg = ""
        try:
            err_msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            pass
        raise HTTPException(
            502, f"AI service error ({resp.status_code}): {err_msg or 'Check your API key and model name.'}"
        )
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        raise HTTPException(502, "The AI service returned an empty response. Try rephrasing your question.")
