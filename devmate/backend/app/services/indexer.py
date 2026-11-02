"""Connect a GitHub repository: download, chunk, profile, score README and store it."""
import json

from ..db import db
from . import github, profile, readme, retriever
from .chunker import chunk_file


def _process_readme(files: list[tuple[str, str]]) -> tuple[int, str, str]:
    """Finds root README and monorepo READMEs in /backend and /frontend, then scores and cleans."""
    readmes = readme.extract_readmes(files)
    root_text = ""
    for rname in ("readme.md", "readme.rst", "readme.txt", "readme"):
        for p, txt in readmes.items():
            if p.lower() == rname:
                root_text = txt
                break
        if root_text:
            break

    extra_parts = []
    for p, txt in readmes.items():
        p_lower = p.lower()
        if (p_lower.startswith("backend/") or p_lower.startswith("frontend/")) and txt != root_text:
            extra_parts.append(f"\n\n## {p}\n\n{txt}")

    combined_readme = (root_text + "".join(extra_parts)) if root_text else "".join(extra_parts)
    return readme.score_readme(combined_readme)


async def connect_repository(user_id: int, url: str) -> dict:
    owner, name = github.parse_repo_url(url)
    meta = await github.fetch_repo_meta(owner, name)
    files, sha = await github.download_files(owner, name, meta["default_branch"])
    chunks = [c for path, text in files for c in chunk_file(path, text)]
    repo_url = f"https://github.com/{owner}/{name}"

    # Build deterministic project profile
    proj_profile = profile.build_project_profile(files)
    profile_json = json.dumps(proj_profile)

    # Score and clean README
    readme_score, readme_quality, readme_cleaned = _process_readme(files)

    with db() as conn:
        old = conn.execute(
            "SELECT id FROM repositories WHERE user_id = ? AND owner = ? AND name = ?", (user_id, owner, name)
        ).fetchone()
        if old:  # re-connecting refreshes the knowledge base
            conn.execute("DELETE FROM repositories WHERE id = ?", (old["id"],))
            conn.execute("DELETE FROM file_summaries WHERE repo_id = ?", (old["id"],))
            conn.execute("DELETE FROM query_cache WHERE repo_id = ?", (old["id"],))
            retriever.invalidate(old["id"])

        cur = conn.execute(
            "INSERT INTO repositories (user_id, owner, name, url, description, default_branch, languages,"
            " commit_sha, file_count, chunk_count, project_profile, readme_score, readme_quality, readme_cleaned) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, owner, name, repo_url, meta["description"], meta["default_branch"], meta["languages"],
             sha, len(files), len(chunks), profile_json, readme_score, readme_quality, readme_cleaned),
        )
        repo_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO code_chunks (repo_id, path, language, start_line, end_line, content) VALUES (?,?,?,?,?,?)",
            [(repo_id, c.path, c.language, c.start_line, c.end_line, c.content) for c in chunks],
        )
        retriever.invalidate(repo_id)
        result = dict(conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())

    return result


async def reindex_repository(repo_id: int, user_id: int) -> dict:
    """Rebuilds chunks, deterministic profile and README score for an existing repository."""
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

    # Re-score README
    readme_score, readme_quality, readme_cleaned = _process_readme(files)

    with db() as conn:
        conn.execute("DELETE FROM code_chunks WHERE repo_id = ?", (repo_id,))
        conn.execute("DELETE FROM file_summaries WHERE repo_id = ?", (repo_id,))
        conn.execute("DELETE FROM query_cache WHERE repo_id = ?", (repo_id,))
        retriever.invalidate(repo_id)

        conn.execute(
            "UPDATE repositories SET description = ?, languages = ?, commit_sha = ?, file_count = ?, "
            "chunk_count = ?, project_profile = ?, project_summary = '', "
            "readme_score = ?, readme_quality = ?, readme_cleaned = ?, analysis_report = NULL, analysis_sha = NULL "
            "WHERE id = ?",
            (meta.get("description", repo["description"]), meta.get("languages", repo["languages"]),
             sha, len(files), len(chunks), profile_json,
             readme_score, readme_quality, readme_cleaned, repo_id),
        )
        conn.executemany(
            "INSERT INTO code_chunks (repo_id, path, language, start_line, end_line, content) VALUES (?,?,?,?,?,?)",
            [(repo_id, c.path, c.language, c.start_line, c.end_line, c.content) for c in chunks],
        )
        updated = dict(conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())

    return updated
