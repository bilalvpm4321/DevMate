"""Shared helpers for the Discord and Telegram bots."""
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
BOT_API_KEY = os.getenv("BOT_API_KEY", "")

ERROR_RE = re.compile(
    r"(Traceback \(most recent call last\)|\b\w+(Error|Exception):|Cannot read propert|is not a function|syntax error at or near)"
)


def looks_like_error(text: str) -> bool:
    return bool(ERROR_RE.search(text))


async def _post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{BACKEND_URL}/api{path}", json=payload, headers={"X-Bot-Key": BOT_API_KEY}
        )
    if resp.status_code != 200:
        detail = resp.json().get("detail", "Something went wrong.") if resp.headers.get("content-type", "").startswith("application/json") else "Something went wrong."
        return {"error": detail}
    return resp.json()


async def ask(platform: str, community_id: str, message: str) -> str:
    data = await _post("/bot/ask", {"platform": platform, "community_id": community_id, "message": message})
    if "error" in data:
        return f"⚠️ {data['error']}"
    text = data["reply"]
    if data.get("sources"):
        text += "\n\n**Sources**\n" + "\n".join(
            f"[{s['path']}:{s['start_line']}-{s['end_line']}](<{s['url']}>)" for s in data["sources"][:4]
        )
    return text


async def link_repo(platform: str, community_id: str, url: str) -> str:
    data = await _post("/bot/link", {"platform": platform, "community_id": community_id, "repo_url": url})
    if "error" in data:
        return f"⚠️ {data['error']}"
    return f"✅ Connected **{data['repo']}** ({data['files']} files indexed). Ask me anything about it."


def split_message(text: str, limit: int) -> list[str]:
    """Split on paragraph/line boundaries so long answers fit platform message limits."""
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            parts.append(current)
            current = ""
        current += line[:limit]
    return parts + [current] if current else parts
