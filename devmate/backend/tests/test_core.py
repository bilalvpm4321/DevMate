import os
import tempfile

os.environ["DEVMATE_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["BOT_API_KEY"] = "test-bot-key"
os.environ["GEMINI_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import github
from app.services.chunker import chunk_file, should_index
from app.services.errors import detect_error
from app.services.retriever import BM25Index, tokenize

SAMPLE = {
    "app/auth.py": "def login(user, password):\n    token = create_jwt_token(user)\n    return token\n",
    "app/db.py": "import sqlite3\n\ndef connect_database():\n    return sqlite3.connect('x.db')\n",
    "README.md": "# Demo\nA tiny demo project.\n",
}


def test_detect_error():
    assert detect_error("IndexError: list index out of range").error_type == "IndexError"
    assert detect_error("TypeError: Cannot read properties of undefined (reading 'x')").language == "JavaScript"
    assert detect_error("hello world") is None


def test_should_index_skips_secrets_and_vendor():
    assert should_index("src/app.py")
    assert not should_index(".env")
    assert not should_index("node_modules/x/index.js")
    assert not should_index("logo.png")


def test_chunker_line_numbers():
    text = "\n".join(f"line{i}" for i in range(1, 130))
    chunks = chunk_file("a.py", text, max_lines=50, overlap=5)
    assert chunks[0].start_line == 1 and chunks[-1].end_line == 129
    assert all(c.content for c in chunks)


def test_bm25_finds_login():
    rows = [{"path": p, "content": c, "start_line": 1, "end_line": 3, "language": "python"} for p, c in SAMPLE.items()]
    top = BM25Index(rows).search("how does login work", 1)[0][0]
    assert top["path"] == "app/auth.py"
    assert "create" in tokenize("createJwtToken")


@pytest.fixture()
def client(monkeypatch):
    async def fake_meta(owner, name):
        return {"description": "demo", "default_branch": "main", "languages": "Python"}

    async def fake_download(owner, name, ref):
        return list(SAMPLE.items()), "abc1234"

    monkeypatch.setattr(github, "fetch_repo_meta", fake_meta)
    monkeypatch.setattr(github, "download_files", fake_download)
    with TestClient(app) as c:
        yield c


def _auth(client):
    token = client.post("/api/auth/guest").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_auth_flow(client):
    body = {"name": "Ada", "email": "ada@example.com", "password": "secret1"}
    assert client.post("/api/auth/register", json=body).status_code == 200
    assert client.post("/api/auth/register", json=body).status_code == 409
    assert client.post("/api/auth/login", json={"email": "ada@example.com", "password": "bad"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_chat_offline_and_history(client):
    h = _auth(client)
    r = client.post("/api/chat", json={"message": "IndexError: list index out of range", "mode": "debug"}, headers=h).json()
    assert r["detected_error"]["type"] == "IndexError"
    msgs = client.get(f"/api/conversations/{r['conversation_id']}/messages", headers=h).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_repo_flow(client):
    h = _auth(client)
    repo = client.post("/api/repos", json={"url": "https://github.com/acme/demo"}, headers=h).json()
    assert repo["file_count"] == 3
    ans = client.post(f"/api/repos/{repo['id']}/ask", json={"question": "Where is login implemented?"}, headers=h).json()
    assert ans["sources"][0]["path"] == "app/auth.py"
    assert ans["sources"][0]["url"].endswith("app/auth.py#L1-L3")
    docs = client.post(f"/api/repos/{repo['id']}/docs", headers=h).json()
    assert "demo" in docs["markdown"]
    other = _auth(client)  # another user must not see this repo
    assert client.post(f"/api/repos/{repo['id']}/ask", json={"question": "x"}, headers=other).status_code == 404


def test_bot_flow(client):
    hdr = {"X-Bot-Key": "test-bot-key"}
    assert client.post("/api/bot/ask", json={"platform": "discord", "community_id": "1", "message": "hi"}).status_code == 401
    client.post("/api/bot/link", json={"platform": "discord", "community_id": "1", "repo_url": "https://github.com/a/b"}, headers=hdr)
    r = client.post("/api/bot/ask", json={"platform": "discord", "community_id": "1", "message": "database connection"}, headers=hdr).json()
    assert r["sources"][0]["path"] == "app/db.py"
    r2 = client.post("/api/bot/ask", json={"platform": "telegram", "community_id": "9", "message": "KeyError: 'x'"}, headers=hdr).json()
    assert r2["sources"] == []  # other community has no repo -> isolated
