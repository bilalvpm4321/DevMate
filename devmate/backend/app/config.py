"""Central configuration, loaded from environment variables / .env file."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me-please-use-env-file")
    jwt_hours: int = int(os.getenv("JWT_HOURS", "168"))
    db_path: str = os.getenv("DEVMATE_DB", "devmate.db")
    cors_origins: tuple = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    )
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    bot_api_key: str = os.getenv("BOT_API_KEY", "")

    # Repository indexing limits
    max_file_bytes: int = 200_000
    max_files: int = 1500
    max_repo_zip_mb: int = 50


settings = Settings()
