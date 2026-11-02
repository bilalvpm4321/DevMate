from fastapi import APIRouter, Depends, HTTPException

from ..db import db
from ..schemas import AskRequest, RepoConnectRequest
from ..security import current_user
from ..services import analyzer, github, indexer, llm, prompts, rag, retriever

router = APIRouter(prefix="/repos", tags=["repositories"])


def own_repo(repo_id: int, user: dict) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM repositories WHERE id = ? AND user_id = ?", (repo_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Repository not found. Connect it first.")
    return dict(row)


@router.get("")
def list_repos(user: dict = Depends(current_user)):
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM repositories WHERE user_id = ? ORDER BY id DESC", (user["id"],))]


@router.post("")
async def connect(body: RepoConnectRequest, user: dict = Depends(current_user)):
    return await indexer.connect_repository(user["id"], body.url)


@router.delete("/{repo_id}")
def delete(repo_id: int, user: dict = Depends(current_user)):
    own_repo(repo_id, user)
    with db() as conn:
        conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    retriever.invalidate(repo_id)
    return {"ok": True}


@router.post("/{repo_id}/reindex")
async def reindex(repo_id: int, user: dict = Depends(current_user)):
    own_repo(repo_id, user)
    return await indexer.reindex_repository(repo_id, user["id"])


@router.get("/{repo_id}/files")
def files(repo_id: int, user: dict = Depends(current_user)):
    own_repo(repo_id, user)
    with db() as conn:
        rows = conn.execute(
            "SELECT path, language, MAX(end_line) AS lines FROM code_chunks WHERE repo_id = ? "
            "GROUP BY path ORDER BY path", (repo_id,))
        return [dict(r) for r in rows]


@router.post("/{repo_id}/ask")
async def ask(repo_id: int, body: AskRequest, user: dict = Depends(current_user)):
    return await rag.answer(own_repo(repo_id, user), body.question, body.file_path, mode=body.mode)


@router.post("/{repo_id}/analyze")
async def analyze(repo_id: int, refresh: bool = False, user: dict = Depends(current_user)):
    repo = own_repo(repo_id, user)
    return await analyzer.run_detailed_analysis(repo, refresh=refresh)


@router.get("/{repo_id}/analyze/status")
def analyze_status(repo_id: int, user: dict = Depends(current_user)):
    own_repo(repo_id, user)
    return analyzer.get_analysis_status(repo_id)


@router.post("/{repo_id}/docs")
async def generate_docs(repo_id: int, user: dict = Depends(current_user)):
    repo = own_repo(repo_id, user)
    prompt = f"Repository: {repo['owner']}/{repo['name']} — {repo['description']}\n\n{rag.build_overview(repo)}"
    content = await llm.generate(prompts.DOCS, prompt)
    if not content:
        content = (f"# {repo['name']}\n\n{repo['description']}\n\n{llm.OFFLINE_NOTICE}\n\n## Project structure\n\n"
                   + "\n".join(f"- `{f['path']}`" for f in files(repo_id, user)[:60]))
    with db() as conn:
        conn.execute("INSERT INTO generated_docs (repo_id, content) VALUES (?,?)", (repo_id, content))
    return {"markdown": content}


@router.get("/{repo_id}/issues")
async def issues(repo_id: int, label: str | None = None, user: dict = Depends(current_user)):
    repo = own_repo(repo_id, user)
    items = await github.fetch_issues(repo["owner"], repo["name"], label)
    return sorted(items, key=lambda i: not i["beginner_friendly"])


@router.post("/{repo_id}/issues/{number}/explain")
async def explain_issue(repo_id: int, number: int, user: dict = Depends(current_user)):
    repo = own_repo(repo_id, user)
    issue = await github.fetch_issue(repo["owner"], repo["name"], number)
    question = f"Issue #{number}: {issue['title']}\n\n{(issue.get('body') or '')[:1500]}"
    return await rag.answer(repo, question, system=prompts.ISSUE)
