from fastapi import APIRouter, Depends, HTTPException

from ..db import db
from ..schemas import ChatRequest
from ..security import current_user
from ..services import llm, prompts
from ..services.errors import detect_error

router = APIRouter(tags=["chat"])


def build_prompt(message: str, mode: str) -> tuple[str, object]:
    """Return (prompt, detected_error). Adds a hint to the prompt when an error is recognised."""
    detected = detect_error(message) if mode in ("debug", "chat") else None
    prompt = message
    if detected:
        prompt += f"\n\n(Detected: {detected.language} {detected.error_type}. Hint: {detected.hint})"
    return prompt, detected


def offline_reply(detected) -> str:
    text = llm.OFFLINE_NOTICE
    if detected:
        text += f"\n\n**Detected:** {detected.language} · `{detected.error_type}`\n\n{detected.hint}"
    return text


@router.post("/chat")
async def chat(body: ChatRequest, user: dict = Depends(current_user)):
    with db() as conn:
        if body.conversation_id:
            conv = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND user_id = ?", (body.conversation_id, user["id"])
            ).fetchone()
            if not conv:
                raise HTTPException(404, "Conversation not found.")
            conv_id = conv["id"]
        else:
            title = body.message.strip().splitlines()[0][:60]
            conv_id = conn.execute(
                "INSERT INTO conversations (user_id, title, mode) VALUES (?,?,?)", (user["id"], title, body.mode)
            ).lastrowid
        history = [
            dict(r) for r in conn.execute(
                "SELECT role, content FROM (SELECT * FROM messages WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT 10) ORDER BY id", (conv_id,))
        ]

    prompt, detected = build_prompt(body.message, body.mode)
    reply = await llm.generate(prompts.MODES[body.mode], prompt, history) or offline_reply(detected)

    with db() as conn:
        conn.executemany(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
            [(conv_id, "user", body.message), (conv_id, "assistant", reply)],
        )
    return {
        "conversation_id": conv_id,
        "reply": reply,
        "detected_error": detected and {"language": detected.language, "type": detected.error_type},
    }


@router.get("/conversations")
def conversations(user: dict = Depends(current_user)):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, title, mode, created_at FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/conversations/{conv_id}/messages")
def messages(conv_id: int, user: dict = Depends(current_user)):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])).fetchone():
            raise HTTPException(404, "Conversation not found.")
        rows = conn.execute("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conv_id,))
        return [dict(r) for r in rows]
