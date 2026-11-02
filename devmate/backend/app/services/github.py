"""GitHub REST API helpers (public repositories)."""
import io
import re
import zipfile

import httpx
from fastapi import HTTPException

from ..config import settings
from .chunker import should_index

_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
API = "https://api.github.com"


def parse_repo_url(url: str) -> tuple[str, str]:
    match = _URL_RE.match(url.strip())
    if not match:
        raise HTTPException(400, "Enter a GitHub repository URL like https://github.com/owner/project.")
    return match.group(1), match.group(2)


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "DevMate"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def _get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    try:
        resp = await client.get(url, headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach GitHub: {exc}") from exc
    if resp.status_code == 404:
        raise HTTPException(404, "Repository not found. DevMate supports public repositories only.")
    if resp.status_code in (403, 429):
        raise HTTPException(429, "GitHub rate limit reached. Add GITHUB_TOKEN to .env or try again later.")
    if resp.status_code >= 400:
        raise HTTPException(502, f"GitHub returned an error ({resp.status_code}).")
    return resp


async def fetch_repo_meta(owner: str, name: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        meta = (await _get(client, f"{API}/repos/{owner}/{name}")).json()
        langs = (await _get(client, f"{API}/repos/{owner}/{name}/languages")).json()
    return {
        "description": meta.get("description") or "",
        "default_branch": meta.get("default_branch", "main"),
        "languages": ", ".join(list(langs)[:6]),
    }


async def download_files(owner: str, name: str, ref: str) -> tuple[list[tuple[str, str]], str]:
    """Download the repo zip and return ([(path, text)], short_commit_sha)."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await _get(client, f"{API}/repos/{owner}/{name}/zipball/{ref}")
    if len(resp.content) > settings.max_repo_zip_mb * 1024 * 1024:
        raise HTTPException(413, f"Repository is larger than {settings.max_repo_zip_mb} MB.")
    files: list[tuple[str, str]] = []
    sha = ""
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            root, _, path = info.filename.partition("/")
            sha = sha or root.rsplit("-", 1)[-1]
            if not path or info.file_size > settings.max_file_bytes or not should_index(path):
                continue
            try:
                files.append((path, archive.read(info).decode("utf-8")))
            except UnicodeDecodeError:
                continue  # binary file
            if len(files) >= settings.max_files:
                break
    return files, sha


async def fetch_issues(owner: str, name: str, label: str | None = None) -> list[dict]:
    params = {"state": "open", "per_page": 30}
    if label:
        params["labels"] = label
    async with httpx.AsyncClient(timeout=30) as client:
        data = (await _get(client, f"{API}/repos/{owner}/{name}/issues", params=params)).json()
    return [
        {
            "number": i["number"], "title": i["title"], "url": i["html_url"],
            "labels": [l["name"] for l in i.get("labels", [])],
            "beginner_friendly": any(l["name"].lower() in ("good first issue", "help wanted") for l in i.get("labels", [])),
            "body": (i.get("body") or "")[:1500],
        }
        for i in data if "pull_request" not in i
    ]


async def fetch_issue(owner: str, name: str, number: int) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        return (await _get(client, f"{API}/repos/{owner}/{name}/issues/{number}")).json()
