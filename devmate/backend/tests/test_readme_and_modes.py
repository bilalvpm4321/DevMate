"""Tests for README quality scoring, Quick vs Detailed modes, report generation, and query caching."""
import json
import pytest
from fastapi.testclient import TestClient

from app.db import init_db, db
from app.main import app
from app.services import github, llm, readme

SAMPLE_DETAILED_README = """# DevMate: AI Code Mentor & Repository Intelligence

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://example.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

DevMate is an intelligent developer assistant designed to guide developers through complex codebases, automate documentation generation, and offer architectural mentorship.

## Overview
DevMate connects directly to GitHub repositories, builds an intelligent in-memory index, extracts code relationships, and enables natural language interaction.

## Features
- Real-time intelligent code search using BM25 and reciprocal rank fusion
- Architecture and data-flow extraction
- Offline deterministic project profiling
- Token-efficient Quick Mode leveraging README summaries
- One-click detailed architectural analysis

## Tech Stack
- **Backend**: FastAPI, Python 3.12, SQLite, PyJWT, HTTPX
- **Frontend**: React 18, TypeScript, Vite, Vanilla CSS
- **AI Integrations**: Gemini 2.5 Flash with OpenRouter fallback

## Architecture & Structure
The repository is organized into `/backend` for API services and `/frontend` for the user interface.
Requests flow through FastAPI routers down to retrieval services and database persistence.

## Installation
1. Clone the repository:
```bash
git clone https://github.com/example/devmate.git
cd devmate
```
2. Install Python dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## Usage
To start the development servers:
```bash
./start.bat
```
Navigate to `http://localhost:5173` to explore connected repositories.

## Configuration & API
DevMate requires the following environment variables:
- `GEMINI_API_KEY`: Google Gemini API key
- `JWT_SECRET`: Secret key for session security

API documentation is accessible at `/docs`.
"""

SAMPLE_BASIC_README = """# Simple Utility

A basic tool for parsing text files and printing summary statistics.

## Installation
```bash
pip install -r requirements.txt
```

## Usage
Run the script with:
```bash
python run.py --input data.txt
```
"""

SAMPLE_BOILERPLATE_README = """# my-react-app

This project was bootstrapped with Create React App.

## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in the development mode.
Open [http://localhost:3000](http://localhost:3000) to view it in the browser.

The page will reload if you make edits.
You will also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more information.

### `npm run build`

Builds the app for production to the `build` folder.
It correctly bundles React in production mode and optimizes the build for the best performance.
"""

SAMPLE_EMPTY_README = "   \n\n  "

MOCK_REPO_FILES: dict[str, str] = {
    "package.json": json.dumps({"name": "mock-app", "dependencies": {"react": "^18.0.0"}}),
    "requirements.txt": "fastapi>=0.110.0\nuvicorn>=0.29.0\n",
    "main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'status': 'ok'}\n",
}


def test_readme_scorer_unit_tests():
    """Validates scoring across detailed, basic, boilerplate, and empty READMEs."""
    # 1. Detailed README
    score_det, quality_det, cleaned_det = readme.score_readme(SAMPLE_DETAILED_README)
    assert score_det >= 60, f"Expected score >= 60, got {score_det}"
    assert quality_det == "detailed"
    assert "shields.io" not in cleaned_det

    # 2. Basic README
    score_bas, quality_bas, cleaned_bas = readme.score_readme(SAMPLE_BASIC_README)
    assert 30 <= score_bas <= 59, f"Expected score 30-59, got {score_bas}"
    assert quality_bas == "basic"

    # 3. Boilerplate CRA README
    score_cr, quality_cr, cleaned_cr = readme.score_readme(SAMPLE_BOILERPLATE_README)
    assert score_cr < 30, f"Expected boilerplate score < 30, got {score_cr}"
    assert quality_cr == "poor"

    # 4. Empty README
    score_emp, quality_emp, cleaned_emp = readme.score_readme(SAMPLE_EMPTY_README)
    assert score_emp == 0
    assert quality_emp == "poor"
    assert cleaned_emp == ""


@pytest.mark.anyio
async def test_quick_mode_detailed_readme_one_call_no_summaries(monkeypatch):
    """Assert quick mode makes exactly 1 LLM call, uses README sections, and skips file summaries."""
    init_db()

    repo_files = dict(MOCK_REPO_FILES)
    repo_files["README.md"] = SAMPLE_DETAILED_README

    async def fake_meta(owner, name):
        return {"description": "Detailed app", "default_branch": "main", "languages": "Python, TypeScript"}

    async def fake_download(owner, name, ref):
        return list(repo_files.items()), "sha-detailed-123"

    call_count = 0

    async def fake_generate(system, prompt):
        nonlocal call_count
        call_count += 1
        return "# Detailed Overview\nDevMate is an intelligent developer assistant."

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)
    monkeypatch.setattr(llm, "generate", fake_generate)

    with TestClient(app) as c:
        user_token = c.post("/api/auth/guest").json()["token"]
        headers = {"Authorization": f"Bearer {user_token}"}

        # Connect repo
        repo = c.post("/api/repos", json={"url": "https://github.com/test/detailed-repo"}, headers=headers).json()
        repo_id = repo["id"]
        assert repo["readme_quality"] == "detailed"
        assert repo["readme_score"] >= 60

        call_count = 0  # Reset counter before ask

        # Ask overview question in Quick mode (default)
        res = c.post(
            f"/api/repos/{repo_id}/ask",
            json={"question": "What is the purpose of this project?", "mode": "quick"},
            headers=headers,
        ).json()

        # Assert exactly 1 LLM call made
        assert call_count == 1
        assert res["meta"]["llm_calls"] == 1
        assert res["meta"]["mode_used"] == "quick"
        assert res["meta"]["used_readme"] is True
        assert res["meta"]["readme_quality"] == "detailed"
        assert res["suggest_detailed"] is False

        # Assert sources cite README sections
        assert len(res["sources"]) > 0
        assert any("README.md" in s["path"] for s in res["sources"])

        # Assert NO file summaries were generated
        with db() as conn:
            summary_count = conn.execute("SELECT COUNT(*) as cnt FROM file_summaries WHERE repo_id = ?", (repo_id,)).fetchone()["cnt"]
            assert summary_count == 0, f"Expected 0 file summaries in quick mode, found {summary_count}"


@pytest.mark.anyio
async def test_boilerplate_readme_triggers_poor_and_suggest_detailed(monkeypatch):
    """Assert boilerplate README gets poor quality and sets suggest_detailed: true."""
    init_db()

    repo_files = dict(MOCK_REPO_FILES)
    repo_files["README.md"] = SAMPLE_BOILERPLATE_README

    async def fake_meta(owner, name):
        return {"description": "Boilerplate app", "default_branch": "main", "languages": "Python"}

    async def fake_download(owner, name, ref):
        return list(repo_files.items()), "sha-boilerplate-456"

    async def fake_generate(system, prompt):
        return "# Code Overview\nInferred from codebase."

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)
    monkeypatch.setattr(llm, "generate", fake_generate)

    with TestClient(app) as c:
        user_token = c.post("/api/auth/guest").json()["token"]
        headers = {"Authorization": f"Bearer {user_token}"}

        repo = c.post("/api/repos", json={"url": "https://github.com/test/cra-repo"}, headers=headers).json()
        assert repo["readme_quality"] == "poor"

        res = c.post(
            f"/api/repos/{repo['id']}/ask",
            json={"question": "What does this app do?", "mode": "quick"},
            headers=headers,
        ).json()

        assert res["suggest_detailed"] is True
        assert "README is minimal" in res.get("suggest_reason", "")
        assert res["meta"]["mode_used"] == "quick"
        assert res["meta"]["used_readme"] is False


@pytest.mark.anyio
async def test_detailed_mode_and_analysis_report_caching(monkeypatch):
    """Assert detailed analysis report generation works and caches on the second call (0 LLM calls)."""
    init_db()

    repo_files = dict(MOCK_REPO_FILES)
    repo_files["README.md"] = SAMPLE_DETAILED_README

    async def fake_meta(owner, name):
        return {"description": "Test app", "default_branch": "main", "languages": "Python"}

    async def fake_download(owner, name, ref):
        return list(repo_files.items()), "sha-analysis-789"

    llm_calls = 0

    async def fake_generate(system, prompt):
        nonlocal llm_calls
        llm_calls += 1
        return "### 1. What it is\nDetailed mock report."

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)
    monkeypatch.setattr(llm, "generate", fake_generate)

    with TestClient(app) as c:
        user_token = c.post("/api/auth/guest").json()["token"]
        headers = {"Authorization": f"Bearer {user_token}"}

        repo = c.post("/api/repos", json={"url": "https://github.com/test/report-repo"}, headers=headers).json()
        repo_id = repo["id"]

        llm_calls = 0
        # Call 1: Run detailed analysis
        res1 = c.post(f"/api/repos/{repo_id}/analyze", headers=headers).json()
        assert "report" in res1
        assert res1["cached"] is False
        first_calls = llm_calls
        assert first_calls > 0

        # Check status endpoint
        status = c.get(f"/api/repos/{repo_id}/analyze/status", headers=headers).json()
        assert status["status"] == "done"
        assert status["progress"] == 100

        # Call 2: Second call should be 100% cached with 0 additional LLM calls
        res2 = c.post(f"/api/repos/{repo_id}/analyze", headers=headers).json()
        assert res2["cached"] is True
        assert res2["report"] == res1["report"]
        assert llm_calls == first_calls  # Exactly 0 new LLM calls made!


@pytest.mark.anyio
async def test_query_cache_zero_tokens_on_repeat(monkeypatch):
    """Assert identical question + commit SHA + mode returns cached: true and 0 LLM calls."""
    init_db()

    repo_files = dict(MOCK_REPO_FILES)
    repo_files["README.md"] = SAMPLE_DETAILED_README

    async def fake_meta(owner, name):
        return {"description": "Test app", "default_branch": "main", "languages": "Python"}

    async def fake_download(owner, name, ref):
        return list(repo_files.items()), "sha-cache-test"

    llm_calls = 0

    async def fake_generate(system, prompt):
        nonlocal llm_calls
        llm_calls += 1
        return "Unique reply."

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)
    monkeypatch.setattr(llm, "generate", fake_generate)

    with TestClient(app) as c:
        user_token = c.post("/api/auth/guest").json()["token"]
        headers = {"Authorization": f"Bearer {user_token}"}

        repo = c.post("/api/repos", json={"url": "https://github.com/test/cache-repo"}, headers=headers).json()
        repo_id = repo["id"]

        # Call 1
        res1 = c.post(
            f"/api/repos/{repo_id}/ask",
            json={"question": "What is the purpose of this project?", "mode": "quick"},
            headers=headers,
        ).json()
        assert res1["meta"]["cached"] is False
        assert llm_calls == 1

        # Call 2: Exact same question and mode
        res2 = c.post(
            f"/api/repos/{repo_id}/ask",
            json={"question": "What is the purpose of this project?", "mode": "quick"},
            headers=headers,
        ).json()
        assert res2["meta"]["cached"] is True
        assert res2["meta"]["llm_calls"] == 0
        assert llm_calls == 1  # 0 additional calls!
