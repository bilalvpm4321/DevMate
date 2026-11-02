"""Tiny SQLite data layer (swap for Supabase/Postgres by replacing this module)."""
import sqlite3
from contextlib import contextmanager

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT DEFAULT '',
    default_branch TEXT DEFAULT 'main',
    languages TEXT DEFAULT '',
    commit_sha TEXT DEFAULT '',
    file_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    project_profile TEXT DEFAULT '',
    project_summary TEXT DEFAULT '',
    readme_score INTEGER DEFAULT -1,
    readme_quality TEXT DEFAULT '',
    readme_cleaned TEXT DEFAULT '',
    analysis_report TEXT DEFAULT '',
    analysis_sha TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS code_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_repo ON code_chunks(repo_id);
CREATE TABLE IF NOT EXISTS file_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    commit_sha TEXT DEFAULT '',
    summary TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo_id, path)
);
CREATE INDEX IF NOT EXISTS idx_file_summaries_repo ON file_summaries(repo_id);
CREATE TABLE IF NOT EXISTS query_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    mode TEXT NOT NULL,
    question TEXT NOT NULL,
    file_path TEXT DEFAULT '',
    response_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo_id, commit_sha, mode, question, file_path)
);
CREATE INDEX IF NOT EXISTS idx_query_cache ON query_cache(repo_id, commit_sha, mode);
CREATE TABLE IF NOT EXISTS generated_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def db():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        # Safe migrations for existing databases
        cursor = conn.execute("PRAGMA table_info(repositories)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        new_cols = {
            "project_profile": "TEXT DEFAULT ''",
            "project_summary": "TEXT DEFAULT ''",
            "readme_score": "INTEGER DEFAULT -1",
            "readme_quality": "TEXT DEFAULT ''",
            "readme_cleaned": "TEXT DEFAULT ''",
            "analysis_report": "TEXT DEFAULT ''",
            "analysis_sha": "TEXT DEFAULT ''",
        }
        for col_name, col_def in new_cols.items():
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE repositories ADD COLUMN {col_name} {col_def}")
