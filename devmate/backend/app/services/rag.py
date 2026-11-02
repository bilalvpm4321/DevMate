"""Retrieval-augmented question answering over an indexed repository."""
from ..db import db
from . import llm, prompts
from .retriever import get_index

NO_MATCH = (
    "I could not find code in this repository that matches your question. "
    "Try naming a file, function or feature (for example, “login route” or “database connection”)."
)


def get_repo(repo_id: int) -> dict:
    with db() as conn:
        return dict(conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())


def _source(repo: dict, chunk: dict, score: float) -> dict:
    ref = repo["commit_sha"] or repo["default_branch"]
    return {
        "path": chunk["path"], "start_line": chunk["start_line"], "end_line": chunk["end_line"],
        "url": f"{repo['url']}/blob/{ref}/{chunk['path']}#L{chunk['start_line']}-L{chunk['end_line']}",
        "snippet": chunk["content"][:400], "score": round(score, 2),
    }


def retrieve(repo: dict, query: str, file_path: str | None = None, k: int = 6) -> list[tuple[dict, float]]:
    index = get_index(repo["id"])
    if file_path:
        rows = [(r, 1.0) for r in index.rows if r["path"] == file_path][:12]
        return rows
    return index.search(query, k)


def format_context(results: list[tuple[dict, float]]) -> str:
    return "\n\n".join(
        f"[{i}] {c['path']} (lines {c['start_line']}-{c['end_line']})\n```{c['language']}\n{c['content']}\n```"
        for i, (c, _) in enumerate(results, 1)
    )


async def answer(repo: dict, question: str, file_path: str | None = None, system: str = prompts.REPO) -> dict:
    results = retrieve(repo, question, file_path)
    if not results:
        return {"reply": NO_MATCH, "sources": []}
    sources = [_source(repo, c, s) for c, s in results]
    prompt = (
        f"Repository: {repo['owner']}/{repo['name']} — {repo['description']}\n"
        f"Languages: {repo['languages']}\n\nCode excerpts:\n{format_context(results)}\n\nQuestion: {question}"
    )
    reply = await llm.generate(system, prompt)
    if not reply:
        reply = (llm.OFFLINE_NOTICE + "\n\nHere are the most relevant code locations I found:\n"
                 + "\n".join(f"- `{s['path']}` lines {s['start_line']}-{s['end_line']}" for s in sources))
    return {"reply": reply, "sources": sources}


def build_overview(repo: dict) -> str:
    """Compact context for README generation: file tree, manifests and key code areas."""
    index = get_index(repo["id"])
    paths = sorted({r["path"] for r in index.rows})
    manifests = [r for r in index.rows if r["path"].split("/")[-1].lower() in
                 ("readme.md", "package.json", "requirements.txt", "pyproject.toml", "dockerfile", ".env.example")]
    parts = ["File tree:\n" + "\n".join(paths[:200])]
    seen = set()
    for row in manifests[:6]:
        seen.add(row["id"])
        parts.append(f"--- {row['path']} ---\n{row['content']}")
    for topic in ("main entry point application start", "api routes endpoints", "database models config",
                  "authentication login"):
        for row, _ in index.search(topic, 2):
            if row["id"] not in seen:
                seen.add(row["id"])
                parts.append(f"--- {row['path']} (lines {row['start_line']}-{row['end_line']}) ---\n{row['content']}")
    return "\n\n".join(parts)[:30000]
