"""Retrieval-augmented question answering with query routing, hybrid retrieval and profile inference."""
import json
import re
from typing import Any

from ..db import db
from . import llm, profile, prompts
from .retriever import BM25Index, get_index, tokenize

NO_MATCH = (
    "I could not find relevant code in this repository for your question. "
    "Try asking about a specific feature, component, API route, or naming a file (e.g. 'auth routes', 'database models')."
)

OVERVIEW_PATTERNS = [
    re.compile(r"""\b(what\s+(is|does)\s+(this|the)\s+(project|app|codebase|repo|repository))\b""", re.I),
    re.compile(r"""\b(purpose\s+of\s+(this|the)\s+(project|repo|codebase))\b""", re.I),
    re.compile(r"""\b(what\s+is\s+the\s+purpose)\b""", re.I),
    re.compile(r"""\b(tell\s+me\s+about\s+(this|the)\s+(project|repo|codebase))\b""", re.I),
    re.compile(r"""\b(explain\s+(this|the)\s+(project|repo|codebase|architecture))\b""", re.I),
    re.compile(r"""\b(project\s+overview|high[\s-]level\s+overview|architecture\s+overview)\b""", re.I),
    re.compile(r"""\b(tech\s+stack|technology\s+stack|technologies\s+used)\b""", re.I),
    re.compile(r"""\b(how\s+to\s+run|getting\s+started|how\s+does\s+(it|this)\s+work)\b""", re.I),
    re.compile(r"""\b(main\s+features|what\s+can\s+(it|this\s+app)\s+do)\b""", re.I),
    re.compile(r"""^(what\s+is\s+this\??|what\s+is\s+this\s+project\??|purpose\??)$""", re.I),
]


def classify_question(question: str, file_path: str | None = None) -> str:
    """Classifies question as 'file', 'overview', or 'specific'."""
    if file_path:
        return "file"
    q = question.strip()
    for pattern in OVERVIEW_PATTERNS:
        if pattern.search(q):
            return "overview"
    # Short generic prompt checks
    q_words = set(re.findall(r"\w+", q.lower()))
    if len(q_words) <= 5 and q_words.intersection({"purpose", "overview", "architecture", "stack", "features", "summary"}):
        return "overview"
    return "specific"


def _format_source(repo: dict, chunk: dict, score: float = 1.0) -> dict[str, Any]:
    ref = repo.get("commit_sha") or repo.get("default_branch") or "main"
    start = chunk.get("start_line", 1)
    end = chunk.get("end_line", start)
    return {
        "path": chunk["path"],
        "start_line": start,
        "end_line": end,
        "url": f"{repo['url']}/blob/{ref}/{chunk['path']}#L{start}-L{end}",
        "snippet": chunk.get("content", "")[:350],
        "score": round(float(score), 3),
    }


def _get_project_profile(repo: dict) -> dict[str, Any]:
    """Retrieves or builds on the fly the deterministic project profile."""
    raw = repo.get("project_profile")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass

    # Build from database chunks if missing
    with db() as conn:
        rows = conn.execute("SELECT path, content FROM code_chunks WHERE repo_id = ?", (repo["id"],)).fetchall()
        files = [(r["path"], r["content"]) for r in rows]
    prof = profile.build_project_profile(files)
    with db() as conn:
        conn.execute("UPDATE repositories SET project_profile = ? WHERE id = ?", (json.dumps(prof), repo["id"]))
    return prof


def _get_file_summaries(repo_id: int) -> dict[str, str]:
    with db() as conn:
        rows = conn.execute("SELECT path, summary FROM file_summaries WHERE repo_id = ?", (repo_id,)).fetchall()
        return {r["path"]: r["summary"] for r in rows if r["summary"]}


async def expand_query(question: str) -> list[str]:
    """Generates 3-4 diverse search queries with synonyms and identifiers."""
    queries = [question]
    try:
        res = await llm.generate(prompts.QUERY_EXPANSION, f"User question: {question}")
        if res:
            for line in res.splitlines():
                clean = line.strip().strip("-*#\"'").strip()
                if clean and len(clean) > 2 and clean.lower() != question.lower():
                    queries.append(clean)
    except Exception:
        pass

    # Deterministic rule-based expansion fallback
    q_lower = question.lower()
    if any(k in q_lower for k in ("login", "auth", "signin", "signup", "user", "password")):
        queries.extend(["auth jwt token login session", "password bcrypt user authenticate credentials"])
    if any(k in q_lower for k in ("database", "db", "table", "schema", "model")):
        queries.extend(["database models schema connection", "sqlite postgres prisma migration create table"])
    if any(k in q_lower for k in ("route", "api", "endpoint", "url")):
        queries.extend(["api router endpoint route get post", "request handler controller"])

    return list(dict.fromkeys(queries))[:5]


def reciprocal_rank_fusion(query_results: list[list[tuple[dict, float]]], k: int = 12) -> list[tuple[dict, float, float]]:
    """Merges multiple BM25 search rankings using Reciprocal Rank Fusion (RRF)."""
    scores: dict[int, float] = {}
    chunk_map: dict[int, dict] = {}
    max_bm25_map: dict[int, float] = {}

    for ranked_list in query_results:
        for rank, (chunk, bm25_score) in enumerate(ranked_list, 1):
            cid = chunk["id"]
            chunk_map[cid] = chunk
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (60.0 + rank))
            max_bm25_map[cid] = max(max_bm25_map.get(cid, 0.0), bm25_score)

    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    return [(chunk_map[cid], scores[cid], max_bm25_map[cid]) for cid in sorted_ids[:k]]


def add_neighbour_chunks(repo_id: int, top_chunks: list[dict], max_added: int = 4) -> list[dict]:
    """Adds adjacent neighbouring chunks in the same file for contextual continuity."""
    existing_ids = {c["id"] for c in top_chunks}
    enriched = list(top_chunks)
    added = 0

    with db() as conn:
        for chunk in top_chunks[:4]:
            if added >= max_added:
                break
            prev_chunk = conn.execute(
                "SELECT * FROM code_chunks WHERE repo_id = ? AND path = ? AND end_line = ? LIMIT 1",
                (repo_id, chunk["path"], chunk["start_line"] - 1),
            ).fetchone()
            if prev_chunk and prev_chunk["id"] not in existing_ids:
                enriched.append(dict(prev_chunk))
                existing_ids.add(prev_chunk["id"])
                added += 1

            next_chunk = conn.execute(
                "SELECT * FROM code_chunks WHERE repo_id = ? AND path = ? AND start_line = ? LIMIT 1",
                (repo_id, chunk["path"], chunk["end_line"] + 1),
            ).fetchone()
            if next_chunk and next_chunk["id"] not in existing_ids:
                enriched.append(dict(next_chunk))
                existing_ids.add(next_chunk["id"])
                added += 1

    return enriched


async def answer_overview(repo: dict, question: str) -> dict[str, Any]:
    """Generates a comprehensive project overview inferred from code, stack, and models."""
    prof = _get_project_profile(repo)
    prof_md = profile.format_profile_markdown(prof)
    file_summaries = _get_file_summaries(repo["id"])

    # Load project summary if already stored, or generate
    proj_summary = repo.get("project_summary", "")
    if not proj_summary:
        with db() as conn:
            row = conn.execute("SELECT content FROM code_chunks WHERE repo_id = ? AND path LIKE '%README%' LIMIT 1", (repo["id"],)).fetchone()
            readme_text = row["content"] if row else ""
            rows = conn.execute("SELECT path, content FROM code_chunks WHERE repo_id = ?", (repo["id"],)).fetchall()
            files = [(r["path"], r["content"]) for r in rows]
        proj_summary = await profile.generate_project_summary(prof, readme_text, files)
        if proj_summary:
            with db() as conn:
                conn.execute("UPDATE repositories SET project_summary = ? WHERE id = ?", (proj_summary, repo["id"]))

    # Key file summaries block
    top_summaries = []
    for path, smry in list(file_summaries.items())[:25]:
        top_summaries.append(f"- `{path}`: {smry}")

    context_blocks = [
        f"Repository: {repo['owner']}/{repo['name']}",
        f"Description: {repo.get('description') or 'No description provided.'}",
        "",
        prof_md,
    ]
    if proj_summary:
        context_blocks.append(f"### High-Level Inferred Summary:\n{proj_summary}")
    if top_summaries:
        context_blocks.append("### Key File Purposes:\n" + "\n".join(top_summaries))

    prompt = (
        f"{chr(10).join(context_blocks)}\n\n"
        f"User Question: {question}\n\n"
        "Remember to strictly follow the 8-section answer structure. Infer purpose from dependencies, routes, and models."
    )

    reply = await llm.generate(prompts.REPO_OVERVIEW, prompt)
    if not reply:
        # High quality deterministic offline fallback
        reply = (
            f"# {repo['name']}: Project Overview\n\n"
            f"{llm.OFFLINE_NOTICE}\n\n"
            f"### Inferred Purpose\n{proj_summary}\n\n"
            f"{prof_md}\n"
        )

    # Collect authoritative sources for overview
    sources: list[dict[str, Any]] = []
    key_paths = (
        prof.get("manifests", [])
        + prof.get("entry_points", [])
        + [r["file"] for r in prof.get("api_routes", [])[:5]]
        + [m["file"] for m in prof.get("db_models", [])[:5]]
    )
    seen_paths = set()
    ref = repo.get("commit_sha") or repo.get("default_branch") or "main"

    with db() as conn:
        for p in key_paths:
            if p in seen_paths:
                continue
            seen_paths.add(p)
            row = conn.execute(
                "SELECT path, MIN(start_line) as start_line, MAX(end_line) as end_line, content FROM code_chunks "
                "WHERE repo_id = ? AND path = ? GROUP BY path", (repo["id"], p)
            ).fetchone()
            if row:
                sources.append({
                    "path": row["path"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "url": f"{repo['url']}/blob/{ref}/{row['path']}#L{row['start_line']}-L{row['end_line']}",
                    "snippet": file_summaries.get(row["path"], row["content"][:300]),
                    "score": 1.0,
                })
            if len(sources) >= 8:
                break

    return {
        "reply": reply,
        "sources": sources,
        "confidence": "high",
        "inferred": True,
    }


async def answer_file(repo: dict, question: str, file_path: str) -> dict[str, Any]:
    """Answers questions scoped to a specific file with its full chunks and summary."""
    with db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM code_chunks WHERE repo_id = ? AND path = ? ORDER BY start_line", (repo["id"], file_path)
        ).fetchall()]
        summary_row = conn.execute(
            "SELECT summary FROM file_summaries WHERE repo_id = ? AND path = ?", (repo["id"], file_path)
        ).fetchone()

    if not rows:
        return {"reply": f"File `{file_path}` was not found in the index.", "sources": [], "confidence": "low", "inferred": False}

    summary_text = summary_row["summary"] if summary_row else ""
    code_body = "\n".join(r["content"] for r in rows)[:25000]
    prompt = (
        f"Repository: {repo['owner']}/{repo['name']}\n"
        f"File: {file_path}\n"
        f"Summary: {summary_text}\n\n"
        f"File Contents:\n```\n{code_body}\n```\n\n"
        f"Question: {question}"
    )

    reply = await llm.generate(prompts.REPO_SPECIFIC, prompt)
    if not reply:
        reply = f"{llm.OFFLINE_NOTICE}\n\n`{file_path}` has {len(rows)} indexed chunks.\n\nSummary:\n{summary_text}"

    sources = [_format_source(repo, rows[0])]
    return {
        "reply": reply,
        "sources": sources,
        "confidence": "high",
        "inferred": False,
    }


async def answer_specific(repo: dict, question: str) -> dict[str, Any]:
    """Answers specific questions via query expansion, reciprocal rank fusion and continuity expansion."""
    index = get_index(repo["id"])
    expanded_queries = await expand_query(question)

    query_results = [index.search(q, k=15) for q in expanded_queries]
    fused_results = reciprocal_rank_fusion(query_results, k=10)

    if not fused_results:
        return {
            "reply": f"No code matches were found for '{question}'. Tried search queries: {', '.join(expanded_queries[:3])}.",
            "sources": [],
            "confidence": "low",
            "inferred": False,
        }

    raw_chunks = [item[0] for item in fused_results]
    max_bm25 = max(item[2] for item in fused_results)

    # Add neighbouring continuity chunks
    full_chunks = add_neighbour_chunks(repo["id"], raw_chunks, max_added=4)

    # Build context excerpts
    context_parts = []
    for i, c in enumerate(full_chunks, 1):
        context_parts.append(
            f"[{i}] {c['path']} (lines {c['start_line']}-{c['end_line']})\n```{c['language']}\n{c['content']}\n```"
        )
    context_str = "\n\n".join(context_parts)

    # Add compact macro profile header
    prof = _get_project_profile(repo)
    tech_summary = ", ".join(prof.get("technologies", {}).get("frameworks", []) + prof.get("technologies", {}).get("databases_orms", []))

    prompt = (
        f"Repository: {repo['owner']}/{repo['name']} ({tech_summary or 'Custom Stack'})\n\n"
        f"Code excerpts:\n{context_str}\n\n"
        f"Question: {question}"
    )

    reply = await llm.generate(prompts.REPO_SPECIFIC, prompt)
    sources = [_format_source(repo, item[0], item[1]) for item in fused_results]

    if not reply:
        reply = (
            f"{llm.OFFLINE_NOTICE}\n\n"
            "Here are the most relevant code locations found for your question:\n"
            + "\n".join(f"- `{s['path']}` lines {s['start_line']}-{s['end_line']}" for s in sources[:6])
        )

    # Confidence scoring
    if max_bm25 >= 2.5 and len(fused_results) >= 3:
        confidence = "high"
    elif max_bm25 >= 0.8:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "reply": reply,
        "sources": sources,
        "confidence": confidence,
        "inferred": False,
    }


async def answer(
    repo: dict,
    question: str,
    file_path: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    """Unified entry point for answering questions with intelligent routing."""
    # Custom system override (e.g. issues)
    if system and system == prompts.ISSUE:
        index = get_index(repo["id"])
        results = index.search(question, k=8)
        if not results:
            return {"reply": NO_MATCH, "sources": [], "confidence": "low", "inferred": False}
        sources = [_format_source(repo, c, s) for c, s in results]
        context = "\n\n".join(f"[{i}] {c['path']} (lines {c['start_line']}-{c['end_line']})\n```{c['language']}\n{c['content']}\n```"
                              for i, (c, _) in enumerate(results, 1))
        prompt = f"Repository: {repo['owner']}/{repo['name']}\n\nExcerpts:\n{context}\n\nIssue Details:\n{question}"
        reply = await llm.generate(system, prompt)
        return {"reply": reply or "Offline mode: review code references.", "sources": sources, "confidence": "high", "inferred": False}

    route = classify_question(question, file_path)
    if route == "overview":
        return await answer_overview(repo, question)
    elif route == "file":
        return await answer_file(repo, question, file_path or "")
    else:
        return await answer_specific(repo, question)


def build_overview(repo: dict) -> str:
    """Builds comprehensive context for README generation."""
    prof = _get_project_profile(repo)
    prof_md = profile.format_profile_markdown(prof)
    index = get_index(repo["id"])

    manifests = [r for r in index.rows if r["path"].split("/")[-1].lower() in
                 ("readme.md", "package.json", "requirements.txt", "pyproject.toml", "dockerfile", ".env.example")]
    parts = [prof_md]
    for row in manifests[:6]:
        parts.append(f"--- {row['path']} ---\n{row['content']}")
    for topic in ("main entry point", "api routes", "database models", "auth"):
        for row, _ in index.search(topic, 2):
            parts.append(f"--- {row['path']} (lines {row['start_line']}-{row['end_line']}) ---\n{row['content']}")
    return "\n\n".join(parts)[:30000]
