"""Request / response models."""
from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["chat", "explain", "debug", "review", "tests", "optimize"]


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    mode: Mode = "chat"
    conversation_id: int | None = None


class RepoConnectRequest(BaseModel):
    url: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    file_path: str | None = None


class BotLinkRequest(BaseModel):
    platform: Literal["discord", "telegram"]
    community_id: str
    repo_url: str


class BotAskRequest(BaseModel):
    platform: Literal["discord", "telegram"]
    community_id: str
    message: str = Field(min_length=1, max_length=8000)
