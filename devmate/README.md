# DevMate: your AI programming companion

DevMate helps developers understand code, debug errors, explore GitHub repositories, generate documentation and contribute to open source. It runs as a **web app**, a **Discord bot** and a **Telegram bot**, all backed by one FastAPI service.

**Category:** Chatbots & Communities (BharatCode)

## Features

| Module | What it does |
| --- | --- |
| AI Assistant | Q&A, code explanation, review, unit-test generation, optimization |
| Debugger | Recognises Python, JavaScript, Java and SQL errors, explains the cause and gives a fix |
| GitHub Explorer | Connect a public repo, ask questions, get answers with file and line links (RAG) |
| Documentation | Generate a README from the source code; preview and download as Markdown |
| Open Source | Lists open issues (beginner-friendly first) and explains how to approach one |
| Community bots | Discord and Telegram; each server or chat gets its own isolated repo knowledge base |
| Accounts | Register, sign in, or try instantly as a guest; chat history is saved |

## Architecture

```
React + TypeScript UI ─┐
Discord bot ───────────┼──► FastAPI ──► Auth (JWT) · SQLite
Telegram bot ──────────┘        │
                                ├─► GitHub API ─► Chunker ─► BM25 index ─► Retrieval
                                └─► Gemini LLM  ◄── retrieved code excerpts ◄──┘
```

Repository Q&A flow: download repo zip → skip binaries, lock files, vendored folders and secrets → split into line-numbered chunks → index → retrieve the best chunks for a question → send only those to the LLM → return the answer with source links. The model never sees the whole repository, and the prompt tells it to treat code as untrusted data.

## One-command start

The fastest way to launch the entire stack (FastAPI backend + React frontend) with a single command:

**Linux / macOS:**
```bash
./start.sh
```

**Windows:**
```bat
start.bat
```

**With community bots (Discord & Telegram):**
```bash
# Linux / macOS
./start.sh --bots

# Windows
start.bat --bots
```

The launcher will automatically:
- Verify that **Python 3.10+** and **Node 18+** are installed (with download links if missing).
- Initialize `.env` from `.env.example` if missing.
- Set up `backend/.venv` and install `requirements.txt` only when needed.
- Install frontend dependencies (`npm install`) if `node_modules` is missing.
- Stream backend (`[backend]`) and frontend (`[frontend]`) logs in parallel.
- Print URLs when ready: App at http://localhost:5173 and API docs at http://localhost:8000/docs.
- Cleanly stop all processes without leaving orphan processes when you press `Ctrl+C`.

## Manual Quick start

Requires Python 3.10+ and Node 18+.

```bash
cp .env.example .env          # add GEMINI_API_KEY (free at https://aistudio.google.com/apikey)

# 1) Backend  (http://localhost:8000, docs at /docs)
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 2) Frontend  (http://localhost:5173)  - in a second terminal
cd frontend
npm install
npm run dev
```

Without a `GEMINI_API_KEY` the app still runs in offline mode: the debugger shows rule-based hints and repo search shows the matching code locations.

### Community bots (optional)

Set `BOT_API_KEY` (any secret string, same value for backend and bots) plus `DISCORD_TOKEN` and/or `TELEGRAM_TOKEN` in `.env`, restart the backend, then:

```bash
cd bots
pip install -r requirements.txt
python discord_bot.py      # !repo <url>, !ask <question>, @mention, auto-replies to pasted errors
python telegram_bot.py     # /repo <url>, /ask <question>, or just send a message
```

Discord: enable **Message Content Intent** for your bot in the developer portal.

## Tests

```bash
cd backend && pytest
```

Covers error detection, file filtering, chunking, retrieval, auth, chat history, the repo pipeline (GitHub mocked), user isolation and bot isolation.

## Project layout

```
backend/app/
  main.py  config.py  db.py  security.py  schemas.py
  routers/   auth.py  chat.py  repos.py  bot.py
  services/  llm.py  github.py  chunker.py  retriever.py  rag.py  indexer.py  errors.py  prompts.py
backend/tests/
frontend/src/  App.tsx  api.ts  pages/  components/  styles.css
bots/          common.py  discord_bot.py  telegram_bot.py
```

## Roadmap / upgrades

- Replace `services/retriever.py` (BM25) with Sentence-Transformers embeddings + FAISS or pgvector. Callers only use `search(query, k)`.
- Replace line-window chunking with Tree-sitter function/class chunks.
- Move `db.py` to Supabase/PostgreSQL.
- Re-index only changed files by comparing commit SHAs.
- Private repos via GitHub OAuth, admin analytics dashboard, rate limiting.

## Security notes

Secrets (`.env`, keys, certificates) are never indexed. Repositories are only read, and their code is never executed. Every repo and conversation is scoped to its owner, and bot communities are isolated. Set a strong `JWT_SECRET` and `BOT_API_KEY` before deploying.
