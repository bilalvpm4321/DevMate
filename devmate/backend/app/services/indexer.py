"""Connect a GitHub repository: download, chunk and store it."""
from ..db import db
from . import github, retriever
from .chunker import chunk_file, language_of


async def connect_repository(user_id: int, url: str) -> dict:
    owner, name = github.parse_repo_url(url)
    meta = await github.fetch_repo_meta(owner, name)
    files, sha = await github.download_files(owner, name, meta["default_branch"])
    chunks = [c for path, text in files for c in chunk_file(path, text)]
    repo_url = f"https://github.com/{owner}/{name}"
    with db() as conn:
        old = conn.execute(
            "SELECT id FROM repositories WHERE user_id = ? AND owner = ? AND name = ?", (user_id, owner, name)
        ).fetchone()
        if old:  # re-connecting refreshes the knowledge base
            conn.execute("DELETE FROM repositories WHERE id = ?", (old["id"],))
            retriever.invalidate(old["id"])
        cur = conn.execute(
            "INSERT INTO repositories (user_id, owner, name, url, description, default_branch, languages,"
            " commit_sha, file_count, chunk_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, owner, name, repo_url, meta["description"], meta["default_branch"], meta["languages"],
             sha, len(files), len(chunks)),
        )
        repo_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO code_chunks (repo_id, path, language, start_line, end_line, content) VALUES (?,?,?,?,?,?)",
            [(repo_id, c.path, c.language, c.start_line, c.end_line, c.content) for c in chunks],
        )
        return dict(conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())
