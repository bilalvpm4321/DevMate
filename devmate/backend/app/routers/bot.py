"""Endpoints used by the Discord and Telegram bots. Each community gets an isolated knowledge base."""
from fastapi import APIRouter, Header, HTTPException

from ..config import settings
from ..db import db
from ..schemas import BotAskRequest, BotLinkRequest
from ..security import hash_password
from ..services import indexer, llm, prompts, rag
from ..services.errors import detect_error
from .chat import build_prompt, offline_reply

router = APIRouter(prefix="/bot", tags=["bots"])


def _check_key(key: str | None) -> None:
    if not settings.bot_api_key:
        raise HTTPException(503, "Bots are disabled: set BOT_API_KEY in .env.")
    if key != settings.bot_api_key:
        raise HTTPException(401, "Invalid bot key.")


def _community_user(platform: str, community_id: str) -> int:
    """One synthetic user per community keeps repositories and knowledge isolated."""
    email = f"{platform}-{community_id}@bot.local"
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            return row["id"]
        return conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (?,?,?)",
            (email, f"{platform} community {community_id}", hash_password(email + settings.jwt_secret)),
        ).lastrowid


@router.post("/link")
async def link(body: BotLinkRequest, x_bot_key: str | None = Header(None)):
    _check_key(x_bot_key)
    repo = await indexer.connect_repository(_community_user(body.platform, body.community_id), body.repo_url)
    return {"repo": f"{repo['owner']}/{repo['name']}", "files": repo["file_count"], "chunks": repo["chunk_count"]}


@router.post("/ask")
async def ask(body: BotAskRequest, x_bot_key: str | None = Header(None)):
    _check_key(x_bot_key)
    user_id = _community_user(body.platform, body.community_id)
    with db() as conn:
        repo = conn.execute(
            "SELECT * FROM repositories WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    if repo and not detect_error(body.message):
        return await rag.answer(dict(repo), body.message)
    prompt, detected = build_prompt(body.message, "debug" if detect_error(body.message) else "chat")
    system = prompts.MODES["debug" if detected else "chat"] + " Keep the answer under 1500 characters."
    return {"reply": await llm.generate(system, prompt) or offline_reply(detected), "sources": []}
