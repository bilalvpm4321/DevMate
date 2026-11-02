"""DevMate API entry point:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .routers import auth, bot, chat, repos


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="DevMate API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"]
)
for module in (auth, chat, repos, bot):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "ai_configured": bool(settings.gemini_api_key or settings.openrouter_api_key),
        "primary_provider": "gemini" if settings.gemini_api_key else ("openrouter" if settings.openrouter_api_key else "none"),
        "fallback_configured": bool(settings.openrouter_api_key and settings.gemini_api_key),
    }
