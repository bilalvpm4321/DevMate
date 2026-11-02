"""Retrieval-augmented question answering with dual Quick/Detailed modes, README ranking, and query caching."""
import json
import re
from typing import Any

from ..db import db
from . import llm, profile, prompts, readme
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

# In-memory query cache: (repo_id, commit_sha, mode, question, file_path) -> dict
_MEM_QUERY_CACHE: dict[tuple[int, str, str, str, str], dict[str, Any]] = {}


def classify_question(question: str, file_path: str | None = None) -> str:
    """Classifies question as 'file', 'overview', or 'specific'."""
    if file_path:
        return "file"
    q = question.strip()
    for pattern in OVERVIEW_PATTERNS:
        if pattern.search(q):
            return "overview"
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


def _get_readme_info(repo: dict) -> tuple[int, str, str]:
    """Returns (score, quality, cleaned) for repo README, computing on the fly if unindexed."""
    score = repo.get("readme_score")
    quality = repo.get("readme_quality")
    cleaned = repo.get("readme_cleaned")
    if quality and score is not None and cleaned is not None:
        return int(score), str(quality), str(cleaned)

    # Check for README chunks in database
    with db() as conn:
        row = conn.execute(
            "SELECT content FROM code_chunks WHERE repo_id = ? AND (path LIKE '%README%' OR path LIKE '%readme%') "
            "ORDER BY LENGTH(path) ASC LIMIT 1",
            (repo["id"],),
        ).fetchone()
        raw_text = row["content"] if row else ""

    score, quality, cleaned = readme.score_readme(raw_text)
    with db() as conn:
        conn.execute(
            "UPDATE repositories SET readme_score = ?, readme_quality = ?, readme_cleaned = ? WHERE id = ?",
            (score, quality, cleaned, repo["id"]),
        )
    repo["readme_score"] = score
    repo["readme_quality"] = quality
    repo["readme_cleaned"] = cleaned
    return score, quality, cleaned


def _check_cache(repo_id: int, commit_sha: str, mode: str, question: str, file_path: str) -> dict[str, Any] | None:
    key = (repo_id, commit_sha, mode, question.strip().lower(), file_path.strip().lower())
    if key in _MEM_QUERY_CACHE:
        hit = dict(_MEM_QUERY_CACHE[key])
        hit_meta = dict(hit.get("meta", {}))
        hit_meta["cached"] = True
        hit_meta["llm_calls"] = 0
        hit["meta"] = hit_meta
        return hit

    with db() as conn:
        row = conn.execute(
            "SELECT response_json FROM query_cache WHERE repo_id = ? AND commit_sha = ? AND mode = ? AND question = ? AND file_path = ?",
            (repo_id, commit_sha, mode, question.strip().lower(), file_path.strip().lower()),
        ).fetchone()
        if row:
            try:
                data = json.loads(row["response_json"])
                data_meta = dict(data.get("meta", {}))
                data_meta["cached"] = True
                data_meta["llm_calls"] = 0
                data["meta"] = data_meta
                _MEM_QUERY_CACHE[key] = data
                return data
            except Exception:
                pass
    return None


def _save_cache(repo_id: int, commit_sha: str, mode: str, question: str, file_path: str, response: dict[str, Any]):
    key = (repo_id, commit_sha, mode, question.strip().lower(), file_path.strip().lower())
    _MEM_QUERY_CACHE[key] = response
    try:
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO query_cache (repo_id, commit_sha, mode, question, file_path, response_json) VALUES (?,?,?,?,?,?)",
                (repo_id, commit_sha, mode, question.strip().lower(), file_path.strip().lower(), json.dumps(response)),
            )
    except Exception:
        pass


async def expand_query(question: str) -> list[str]:
    """Generates diverse search queries with LLM call."""
    queries = [question]
    try:
        prompt = f"User question: {question}"
        res = await llm.generate(prompts.QUERY_EXPANSION, prompt)
        if res:
            for line in res.splitlines():
                clean = line.strip().strip("-*#\"'").strip()
                if clean and len(clean) > 2 and clean.lower() != question.lower():
                    queries.append(clean)
    except Exception:
        pass

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


async def answer_readme_overview(repo: dict, question: str, cleaned_readme: str) -> tuple[dict[str, Any], int, int, int]:
    """Answers overview questions in Quick Mode using ONLY ranked README sections + deterministic profile. Exactly 1 LLM call."""
    prof = _get_project_profile(repo)
    prof_md = profile.format_profile_markdown(prof)
    sections = readme.split_readme_sections(cleaned_readme)
    ranked = readme.rank_readme_sections(sections, question, top_k=5)

    sections_text = "\n\n".join(f"### Section: {s['title']}\n{s['content']}" for s in ranked)
    prompt = (
        f"Repository: {repo['owner']}/{repo['name']}\n\n"
        f"Project Profile:\n{prof_md}\n\n"
        f"README Sections:\n{sections_text}\n\n"
        f"Question: {question}\n\n"
        "Remember: Answer from the README and project profile. Be detailed and well structured. "
        "If something is not in them, say so and suggest using Detailed analysis."
    )

    llm_calls = 1
    input_chars = len(prompt)
    reply = await llm.generate(prompts.README_OVERVIEW, prompt)
    if not reply:
        reply = (
            f"# {repo['name']}: Project Overview (from README)\n\n"
            f"{llm.OFFLINE_NOTICE}\n\n"
            f"{prof_md}\n\n"
            f"### Relevant README Sections\n{sections_text[:3500]}"
        )
    output_chars = len(reply)

    sources = []
    ref = repo.get("commit_sha") or repo.get("default_branch") or "main"
    for s in ranked[:4]:
        sources.append({
            "path": f"README.md > {s['title']}",
            "start_line": 1,
            "end_line": len(s["content"].splitlines()) or 1,
            "url": f"{repo['url']}/blob/{ref}/README.md",
            "snippet": s["content"][:300],
            "score": 1.0,
        })

    result = {
        "reply": reply,
        "sources": sources,
        "confidence": "high",
        "inferred": False,
    }
    return result, llm_calls, input_chars, output_chars


async def answer_overview(repo: dict, question: str, mode: str = "quick") -> tuple[dict[str, Any], int, int, int]:
    """Generates project overview from code analysis, stack, and models."""
    llm_calls = 0
    input_chars = 0
    output_chars = 0

    prof = _get_project_profile(repo)
    prof_md = profile.format_profile_markdown(prof)

    # In detailed mode, ensure missing file summaries are generated on demand
    commit_sha = repo.get("commit_sha") or "main"
    file_summaries = _get_file_summaries(repo["id"])
    if mode == "detailed" and not file_summaries:
        with db() as conn:
            rows = conn.execute("SELECT path, content FROM code_chunks WHERE repo_id = ?", (repo["id"],)).fetchall()
            files = [(r["path"], r["content"]) for r in rows]
        await profile.summarize_important_files(repo["id"], files, commit_sha)
        file_summaries = _get_file_summaries(repo["id"])

    # Load or generate project summary
    proj_summary = repo.get("project_summary", "")
    if not proj_summary and mode == "detailed":
        with db() as conn:
            row = conn.execute("SELECT content FROM code_chunks WHERE repo_id = ? AND path LIKE '%README%' LIMIT 1", (repo["id"],)).fetchone()
            readme_text = row["content"] if row else ""
            rows = conn.execute("SELECT path, content FROM code_chunks WHERE repo_id = ?", (repo["id"],)).fetchall()
            files = [(r["path"], r["content"]) for r in rows]
        proj_summary = await profile.generate_project_summary(prof, readme_text, files)
        if proj_summary:
            llm_calls += 1
            input_chars += 3000
            output_chars += len(proj_summary)
            with db() as conn:
                conn.execute("UPDATE repositories SET project_summary = ? WHERE id = ?", (proj_summary, repo["id"]))

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
    input_chars += len(prompt)
    reply = await llm.generate(prompts.REPO_OVERVIEW, prompt)
    llm_calls += 1
    if not reply:
        reply = (
            f"# {repo['name']}: Project Overview\n\n"
            f"{llm.OFFLINE_NOTICE}\n\n"
            f"### Inferred Purpose\n{proj_summary or 'Inferred from codebase manifests and routes.'}\n\n"
            f"{prof_md}\n"
        )
    output_chars += len(reply)

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

    result = {
        "reply": reply,
        "sources": sources,
        "confidence": "high",
        "inferred": True,
    }
    return result, llm_calls, input_chars, output_chars


async def answer_file(repo: dict, question: str, file_path: str) -> tuple[dict[str, Any], int, int, int]:
    """Answers questions scoped to a specific file."""
    with db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM code_chunks WHERE repo_id = ? AND path = ? ORDER BY start_line", (repo["id"], file_path)
        ).fetchall()]
        summary_row = conn.execute(
            "SELECT summary FROM file_summaries WHERE repo_id = ? AND path = ?", (repo["id"], file_path)
        ).fetchone()

    if not rows:
        return {"reply": f"File `{file_path}` was not found in the index.", "sources": [], "confidence": "low", "inferred": False}, 0, 0, 0

    summary_text = summary_row["summary"] if summary_row else ""
    code_body = "\n".join(r["content"] for r in rows)[:25000]
    prompt = (
        f"Repository: {repo['owner']}/{repo['name']}\n"
        f"File: {file_path}\n"
        f"Summary: {summary_text}\n\n"
        f"File Contents:\n```\n{code_body}\n```\n\n"
        f"Question: {question}"
    )

    llm_calls = 1
    input_chars = len(prompt)
    reply = await llm.generate(prompts.REPO_SPECIFIC, prompt)
    if not reply:
        reply = f"{llm.OFFLINE_NOTICE}\n\n`{file_path}` has {len(rows)} indexed chunks.\n\nSummary:\n{summary_text}"
    output_chars = len(reply)

    sources = [_format_source(repo, rows[0])]
    result = {
        "reply": reply,
        "sources": sources,
        "confidence": "high",
        "inferred": False,
    }
    return result, llm_calls, input_chars, output_chars


async def answer_specific(repo: dict, question: str, mode: str = "quick", cleaned_readme: str = "") -> tuple[dict[str, Any], int, int, int]:
    """Answers specific code questions via hybrid retrieval, with README header."""
    llm_calls = 0
    input_chars = 0
    output_chars = 0

    index = get_index(repo["id"])
    if mode == "detailed":
        expanded_queries = await expand_query(question)
        if len(expanded_queries) > 1:
            llm_calls += 1
            input_chars += len(question) + 150
            output_chars += sum(len(q) for q in expanded_queries)
    else:
        # Cheap deterministic expansion in quick mode
        expanded_queries = [question]
        q_lower = question.lower()
        if any(k in q_lower for k in ("login", "auth", "signin")):
            expanded_queries.append("auth jwt login")
        if any(k in q_lower for k in ("route", "api", "endpoint")):
            expanded_queries.append("api router endpoint")

    query_results = [index.search(q, k=15) for q in expanded_queries]
    fused_results = reciprocal_rank_fusion(query_results, k=10)

    if not fused_results:
        return {
            "reply": f"No code matches were found for '{question}'. Tried search queries: {', '.join(expanded_queries[:3])}.",
            "sources": [],
            "confidence": "low",
            "inferred": False,
        }, llm_calls, input_chars, output_chars

    raw_chunks = [item[0] for item in fused_results]
    max_bm25 = max(item[2] for item in fused_results)
    full_chunks = add_neighbour_chunks(repo["id"], raw_chunks, max_added=4)

    context_parts = []
    for i, c in enumerate(full_chunks, 1):
        context_parts.append(
            f"[{i}] {c['path']} (lines {c['start_line']}-{c['end_line']})\n```{c['language']}\n{c['content']}\n```"
        )
    context_str = "\n\n".join(context_parts)

    prof = _get_project_profile(repo)
    tech_summary = ", ".join(prof.get("technologies", {}).get("frameworks", []) + prof.get("technologies", {}).get("databases_orms", []))

    # Add small README header if README is present
    readme_header = ""
    if cleaned_readme:
        sections = readme.split_readme_sections(cleaned_readme)
        ranked = readme.rank_readme_sections(sections, question, top_k=2)
        if ranked:
            readme_header = "README Context:\n" + "\n".join(f"- {s['title']}: {s['content'][:250]}" for s in ranked) + "\n\n"

    prompt = (
        f"Repository: {repo['owner']}/{repo['name']} ({tech_summary or 'Custom Stack'})\n\n"
        f"{readme_header}"
        f"Code excerpts:\n{context_str}\n\n"
        f"Question: {question}"
    )

    input_chars += len(prompt)
    reply = await llm.generate(prompts.REPO_SPECIFIC, prompt)
    llm_calls += 1
    sources = [_format_source(repo, item[0], item[1]) for item in fused_results]

    if not reply:
        reply = (
            f"{llm.OFFLINE_NOTICE}\n\n"
            "Here are the most relevant code locations found for your question:\n"
            + "\n".join(f"- `{s['path']}` lines {s['start_line']}-{s['end_line']}" for s in sources[:6])
        )
    output_chars += len(reply)

    if max_bm25 >= 2.5 and len(fused_results) >= 3:
        confidence = "high"
    elif max_bm25 >= 0.8:
        confidence = "medium"
    else:
        confidence = "low"

    result = {
        "reply": reply,
        "sources": sources,
        "confidence": confidence,
        "inferred": False,
    }
    return result, llm_calls, input_chars, output_chars


async def answer(
    repo: dict,
    question: str,
    file_path: str | None = None,
    mode: str = "quick",
    system: str | None = None,
) -> dict[str, Any]:
    """Unified entry point with dual modes, README routing, token tracking and caching."""
    commit_sha = repo.get("commit_sha") or "main"
    mode_clean = "detailed" if mode == "detailed" else "quick"

    # 1. Query Cache Check
    if not system:
        cached = _check_cache(repo["id"], commit_sha, mode_clean, question, file_path or "")
        if cached:
            return cached

    # 2. System override (e.g. issues)
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

    # 3. README Quality Evaluation
    score, quality, cleaned = _get_readme_info(repo)
    route = classify_question(question, file_path)

    suggest_detailed = False
    suggest_reason = ""
    used_readme = False

    if mode_clean == "quick":
        if quality == "detailed" and route == "overview":
            res, llm_calls, in_chars, out_chars = await answer_readme_overview(repo, question, cleaned)
            used_readme = True
            suggest_detailed = False
        elif quality == "detailed":
            # Specific code question in quick mode
            res, llm_calls, in_chars, out_chars = await answer_specific(repo, question, mode="quick", cleaned_readme=cleaned)
            used_readme = True
            suggest_detailed = False
        else:
            # Basic or Poor README in quick mode
            if route == "overview":
                res, llm_calls, in_chars, out_chars = await answer_overview(repo, question, mode="quick")
            elif route == "file":
                res, llm_calls, in_chars, out_chars = await answer_file(repo, question, file_path or "")
            else:
                res, llm_calls, in_chars, out_chars = await answer_specific(repo, question, mode="quick", cleaned_readme=cleaned)
            used_readme = False
            suggest_detailed = True
            suggest_reason = (
                "README is minimal or missing, so this answer is built from code analysis."
                if quality == "poor" else
                "README is basic, so this answer is built from code analysis."
            )
    else:
        # Detailed mode: always runs full code analysis pipeline
        if route == "overview":
            res, llm_calls, in_chars, out_chars = await answer_overview(repo, question, mode="detailed")
        elif route == "file":
            res, llm_calls, in_chars, out_chars = await answer_file(repo, question, file_path or "")
        else:
            res, llm_calls, in_chars, out_chars = await answer_specific(repo, question, mode="detailed", cleaned_readme=cleaned)
        used_readme = bool(cleaned and len(cleaned) > 50)
        suggest_detailed = False

    approx_in_tokens = in_chars // 4
    approx_out_tokens = out_chars // 4

    meta = {
        "mode_used": mode_clean,
        "used_readme": used_readme,
        "readme_quality": quality,
        "llm_calls": llm_calls,
        "approx_input_tokens": approx_in_tokens,
        "approx_output_tokens": approx_out_tokens,
        "cached": False,
    }

    res["meta"] = meta
    res["suggest_detailed"] = suggest_detailed
    if suggest_detailed:
        res["suggest_reason"] = suggest_reason

    # 4. Cache the computed response
    _save_cache(repo["id"], commit_sha, mode_clean, question, file_path or "", res)
    return res


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
