"""Connect a GitHub repository: download, chunk, profile, summarize and store it."""
import asyncio
import json

from ..db import db
from . import github, profile, retriever
from .chunker import chunk_file


async def _background_summarize(repo_id: int, proj_profile: dict, files: list[tuple[str, str]], sha: str):
    """Non-blocking background step: generates file summaries and project summary."""
    try:
        await profile.summarize_important_files(repo_id, files, sha)
        readme_text = next((text for path, text in files if path.lower() in ("readme.md", "readme")), None)
        summary = await profile.generate_project_summary(proj_profile, readme_text, files)
        if summary:
            with db() as conn:
                conn.execute("UPDATE repositories SET project_summary = ? WHERE id = ?", (summary, repo_id))
    except Exception:
        pass


async def connect_repository(user_id: int, url: str) -> dict:
    owner, name = github.parse_repo_url(url)
    meta = await github.fetch_repo_meta(owner, name)
    files, sha = await github.download_files(owner, name, meta["default_branch"])
    chunks = [c for path, text in files for c in chunk_file(path, text)]
    repo_url = f"https://github.com/{owner}/{name}"

    # Build deterministic project profile
    proj_profile = profile.build_project_profile(files)
    profile_json = json.dumps(proj_profile)

    with db() as conn:
        old = conn.execute(
            "SELECT id FROM repositories WHERE user_id = ? AND owner = ? AND name = ?", (user_id, owner, name)
        ).fetchone()
        if old:  # re-connecting refreshes the knowledge base
            conn.execute("DELETE FROM repositories WHERE id = ?", (old["id"],))
            conn.execute("DELETE FROM file_summaries WHERE repo_id = ?", (old["id"],))
            retriever.invalidate(old["id"])

        cur = conn.execute(
            "INSERT INTO repositories (user_id, owner, name, url, description, default_branch, languages,"
            " commit_sha, file_count, chunk_count, project_profile) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, owner, name, repo_url, meta["description"], meta["default_branch"], meta["languages"],
             sha, len(files), len(chunks), profile_json),
        )
        repo_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO code_chunks (repo_id, path, language, start_line, end_line, content) VALUES (?,?,?,?,?,?)",
            [(repo_id, c.path, c.language, c.start_line, c.end_line, c.content) for c in chunks],
        )
        retriever.invalidate(repo_id)
        result = dict(conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())

    # Trigger async summarization in background without blocking indexing
    asyncio.create_task(_background_summarize(repo_id, proj_profile, files, sha))
    return result


async def reindex_repository(repo_id: int, user_id: int) -> dict:
    """Rebuilds chunks, deterministic profile and file summaries for an existing repository."""
    with db() as conn:
        repo = conn.execute(
            "SELECT * FROM repositories WHERE id = ? AND user_id = ?", (repo_id, user_id)
        ).fetchone()
    if not repo:
        raise ValueError("Repository not found")

    owner, name = repo["owner"], repo["name"]
    meta = await github.fetch_repo_meta(owner, name)
    files, sha = await github.download_files(owner, name, meta.get("default_branch") or repo["default_branch"])
    chunks = [c for path, text in files for c in chunk_file(path, text)]
    proj_profile = profile.build_project_profile(files)
    profile_json = json.dumps(proj_profile)

    with db() as conn:
        conn.execute("DELETE FROM code_chunks WHERE repo_id = ?", (repo_id,))
        conn.execute("DELETE FROM file_summaries WHERE repo_id = ?", (repo_id,))
        retriever.invalidate(repo_id)

        conn.execute(
            "UPDATE repositories SET description = ?, languages = ?, commit_sha = ?, file_count = ?, "
            "chunk_count = ?, project_profile = ?, project_summary = '' WHERE id = ?",
            (meta.get("description", repo["description"]), meta.get("languages", repo["languages"]),
             sha, len(files), len(chunks), profile_json, repo_id),
        )
        conn.executemany(
            "INSERT INTO code_chunks (repo_id, path, language, start_line, end_line, content) VALUES (?,?,?,?,?,?)",
            [(repo_id, c.path, c.language, c.start_line, c.end_line, c.content) for c in chunks],
        )
        updated = dict(conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())

    # Launch background summarization
    asyncio.create_task(_background_summarize(repo_id, proj_profile, files, sha))
    return updated
