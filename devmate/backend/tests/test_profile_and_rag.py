"""Tests for deterministic project profiling, question routing, structural chunking and reindexing."""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import github
from app.services.chunker import chunk_file
from app.services.profile import build_project_profile
from app.services.rag import answer, classify_question, expand_query
from app.services.retriever import BM25Index, get_index

NO_README_REPO: dict[str, str] = {
    "package.json": json.dumps({
        "name": "fullstack-demo",
        "scripts": {"dev": "next dev", "build": "next build"},
        "dependencies": {
            "next": "^14.0.0",
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
            "@prisma/client": "^5.0.0",
        },
    }),
    "backend/requirements.txt": "fastapi>=0.110.0\nuvicorn>=0.29.0\npydantic>=2.6\nPyJWT>=2.8\nsqlalchemy>=2.0\n",
    "backend/app/main.py": (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.get('/api/health')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n\n"
        "@app.post('/api/items')\n"
        "def create_item(name: str):\n"
        "    return {'item': name}\n"
    ),
    "backend/app/models.py": (
        "class User(Base):\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    email = Column(String)\n\n"
        "class Item(Base):\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    title = Column(String)\n"
    ),
    "backend/app/auth.py": (
        "import jwt\n\n"
        "def authenticate_user(username, password):\n"
        "    if username and password:\n"
        "        token = jwt.encode({'sub': username}, 'secret', algorithm='HS256')\n"
        "        return token\n"
        "    return None\n"
    ),
    "frontend/src/App.tsx": (
        "export default function App() {\n"
        "    return <div>Fullstack App</div>;\n"
        "}\n"
    ),
    ".env.example": "DATABASE_URL=postgresql://localhost:5432/mydb\nJWT_SECRET=supersecret\n",
}


def test_deterministic_profile_detects_stack_and_routes():
    files = list(NO_README_REPO.items())
    prof = build_project_profile(files)

    # Frameworks
    frameworks = prof["technologies"].get("frameworks", [])
    assert "FastAPI" in frameworks
    assert "React" in frameworks or "Next.js" in frameworks

    # Database & ORMs
    dbs = prof["technologies"].get("databases_orms", [])
    assert "SQLAlchemy" in dbs or "Prisma" in dbs

    # Auth
    auth = prof["technologies"].get("auth", [])
    assert "JWT" in auth

    # Routes
    route_paths = [r["route"] for r in prof["api_routes"]]
    assert any("/api/health" in r for r in route_paths)
    assert any("/api/items" in r for r in route_paths)

    # Models
    model_names = [m["name"] for m in prof["db_models"]]
    assert "User" in model_names
    assert "Item" in model_names

    # Entry points
    assert any("main.py" in e for e in prof["entry_points"])

    # Environment variables (names only, no values)
    assert "DATABASE_URL" in prof["env_vars"]
    assert "JWT_SECRET" in prof["env_vars"]


def test_question_routing_classification():
    # Overview queries
    assert classify_question("What is the purpose of this project?") == "overview"
    assert classify_question("What does this project do?") == "overview"
    assert classify_question("Explain the architecture") == "overview"
    assert classify_question("Tell me about the tech stack") == "overview"
    assert classify_question("How does this work?") == "overview"
    assert classify_question("How to run this repository") == "overview"

    # Specific queries
    assert classify_question("Where is authenticate_user defined?") == "specific"
    assert classify_question("How does login work?") == "specific"
    assert classify_question("Show me the database connection logic") == "specific"

    # File queries
    assert classify_question("Explain this", file_path="backend/app/main.py") == "file"


@pytest.mark.anyio
async def test_query_expansion_finds_auth_terms():
    queries = await expand_query("how does login work")
    joined = " ".join(queries).lower()
    assert any(term in joined for term in ("auth", "jwt", "token", "password", "session", "credentials"))


@pytest.mark.anyio
async def test_overview_answer_on_repo_without_readme(monkeypatch):
    from app.db import init_db
    init_db()

    async def fake_meta(owner, name):
        return {"description": "A fullstack demo", "default_branch": "main", "languages": "Python, TypeScript"}

    async def fake_download(owner, name, ref):
        return list(NO_README_REPO.items()), "sha-no-readme-123"

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)

    with TestClient(app) as c:
        user_token = c.post("/api/auth/guest").json()["token"]
        headers = {"Authorization": f"Bearer {user_token}"}

        # Connect repository without README
        repo = c.post("/api/repos", json={"url": "https://github.com/demo/no-readme-app"}, headers=headers).json()
        assert repo["file_count"] == len(NO_README_REPO)

        # Ask overview question
        res = c.post(
            f"/api/repos/{repo['id']}/ask",
            json={"question": "What is the purpose of this project?"},
            headers=headers,
        ).json()

        assert res["confidence"] == "high"
        assert res["inferred"] is True
        assert len(res["sources"]) > 0

        # Assert answer does NOT give up or say unknown
        reply = res["reply"]
        assert "the purpose is not explicitly described" not in reply.lower()
        # Should mention detected stack elements in answer or profile
        assert any(term in reply for term in ("FastAPI", "React", "Next.js", "Fullstack", "User", "Item"))


@pytest.mark.anyio
async def test_reindex_endpoint(monkeypatch):
    async def fake_meta(owner, name):
        return {"description": "Demo app", "default_branch": "main", "languages": "Python"}

    async def fake_download(owner, name, ref):
        return list(NO_README_REPO.items()), "sha-updated-456"

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)

    with TestClient(app) as c:
        user_token = c.post("/api/auth/guest").json()["token"]
        headers = {"Authorization": f"Bearer {user_token}"}

        repo = c.post("/api/repos", json={"url": "https://github.com/demo/reindex-app"}, headers=headers).json()
        repo_id = repo["id"]

        # Call re-index endpoint
        reindexed = c.post(f"/api/repos/{repo_id}/reindex", headers=headers)
        assert reindexed.status_code == 200
        data = reindexed.json()
        assert data["id"] == repo_id
        assert data["commit_sha"] == "sha-updated-456"
