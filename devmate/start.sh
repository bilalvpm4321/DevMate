#!/usr/bin/env bash
# ==============================================================================
# DevMate - One-Command Launcher (Linux / macOS)
# Starts FastAPI backend, React+Vite frontend, and optional community bots.
# ==============================================================================

set -e

# Resolve repository root directory
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Parse CLI arguments
START_BOTS=false
for arg in "$@"; do
    case "$arg" in
        --bots|-bots)
            START_BOTS=true
            ;;
    esac
done

# Track background process IDs for clean exit
pids=()
cleaned_up=false

cleanup() {
    if [ "$cleaned_up" = true ]; then return; fi
    cleaned_up=true
    echo ""
    echo "[DevMate] Stopping all services cleanly..."
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
        fi
    done
    wait 2>/dev/null || true
    echo "[DevMate] All processes stopped. Goodbye!"
}
trap cleanup INT TERM EXIT

# ------------------------------------------------------------------------------
# 1. Check Python (>= 3.10)
# ------------------------------------------------------------------------------
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [ -n "$ver" ]; then
            major="$(echo "$ver" | cut -d. -f1)"
            minor="$(echo "$ver" | cut -d. -f2)"
            if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then
                PYTHON_BIN="$candidate"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "\n\033[0;31m[ERROR] Python 3.10+ is required, but was not found.\033[0m"
    echo -e "\033[0;33mPlease download and install Python 3.10+ from: https://www.python.org/downloads/\033[0m\n"
    exit 1
fi

# ------------------------------------------------------------------------------
# 2. Check Node.js (>= 18)
# ------------------------------------------------------------------------------
NODE_OK=false
if command -v node >/dev/null 2>&1; then
    node_ver="$(node -v 2>/dev/null || true)"
    node_major="$(echo "$node_ver" | sed -E 's/^v([0-9]+)\..*/\1/')"
    if [ -n "$node_major" ] && [ "$node_major" -ge 18 ]; then
        NODE_OK=true
    fi
fi

if [ "$NODE_OK" = false ]; then
    echo -e "\n\033[0;31m[ERROR] Node.js 18+ is required, but was not found.\033[0m"
    echo -e "\033[0;33mPlease download and install Node.js (LTS recommended) from: https://nodejs.org/\033[0m\n"
    exit 1
fi

# ------------------------------------------------------------------------------
# 3. Check or create .env file
# ------------------------------------------------------------------------------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "[DevMate] Created .env from .env.example"
        echo -e "\033[0;33m[DevMate] Please add your GEMINI_API_KEY in .env (get a free key at https://aistudio.google.com/apikey)\033[0m"
    else
        echo "[WARN] Neither .env nor .env.example found."
    fi
fi

get_env_val() {
    local key="$1"
    if [ -f ".env" ]; then
        grep -E "^[[:space:]]*${key}=" .env | tail -n 1 | cut -d '=' -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
    fi
}

# ------------------------------------------------------------------------------
# 4. Backend setup: virtualenv & requirements.txt
# ------------------------------------------------------------------------------
VENV_DIR="$ROOT_DIR/backend/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "[backend] Creating virtual environment in backend/.venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

BACKEND_STAMP="$VENV_DIR/.requirements_installed"
REQ_FILE="$ROOT_DIR/backend/requirements.txt"
if [ ! -f "$BACKEND_STAMP" ] || [ "$REQ_FILE" -nt "$BACKEND_STAMP" ]; then
    echo "[backend] Installing backend dependencies from requirements.txt..."
    "$VENV_PYTHON" -m pip install -r "$REQ_FILE"
    touch "$BACKEND_STAMP"
fi

# ------------------------------------------------------------------------------
# 5. Frontend setup: npm install if node_modules missing
# ------------------------------------------------------------------------------
FRONTEND_DIR="$ROOT_DIR/frontend"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "[frontend] Installing frontend dependencies (npm install)..."
    (cd "$FRONTEND_DIR" && npm install)
fi

# ------------------------------------------------------------------------------
# 6. Bots setup (optional --bots flag)
# ------------------------------------------------------------------------------
START_DISCORD=false
START_TELEGRAM=false

if [ "$START_BOTS" = true ]; then
    BOTS_DIR="$ROOT_DIR/bots"
    BOTS_STAMP="$VENV_DIR/.bots_requirements_installed"
    BOTS_REQ="$BOTS_DIR/requirements.txt"
    if [ ! -f "$BOTS_STAMP" ] || [ "$BOTS_REQ" -nt "$BOTS_STAMP" ]; then
        echo "[bots] Installing bots dependencies from bots/requirements.txt..."
        "$VENV_PYTHON" -m pip install -r "$BOTS_REQ"
        touch "$BOTS_STAMP"
    fi

    discord_tok="$(get_env_val "DISCORD_TOKEN")"
    if [ -n "$discord_tok" ] && [ "$discord_tok" != "change-me" ]; then
        START_DISCORD=true
    else
        echo -e "\033[0;33m[WARN] DISCORD_TOKEN is empty in .env - skipping Discord bot.\033[0m"
    fi

    telegram_tok="$(get_env_val "TELEGRAM_TOKEN")"
    if [ -n "$telegram_tok" ] && [ "$telegram_tok" != "change-me" ]; then
        START_TELEGRAM=true
    else
        echo -e "\033[0;33m[WARN] TELEGRAM_TOKEN is empty in .env - skipping Telegram bot.\033[0m"
    fi
fi

# ------------------------------------------------------------------------------
# Helper: Run command with prefixed logs
# ------------------------------------------------------------------------------
run_prefixed() {
    local prefix="$1"
    local color="$2"
    local dir="$3"
    shift 3

    (
        cd "$dir"
        "$@" 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
            printf "%b[%s]%b %s\n" "$color" "$prefix" "\033[0m" "$line"
        done
    ) &
    pids+=($!)
}

# ------------------------------------------------------------------------------
# 7. Start Services
# ------------------------------------------------------------------------------
echo ""
echo "[DevMate] Starting backend and frontend services..."

# Backend: uvicorn app.main:app --reload --port 8000
run_prefixed "backend" "\033[0;36m" "$ROOT_DIR/backend" "$VENV_PYTHON" -m uvicorn app.main:app --reload --port 8000

# Frontend: npm run dev
run_prefixed "frontend" "\033[0;32m" "$FRONTEND_DIR" npm run dev

# Optional bots
if [ "$START_DISCORD" = true ]; then
    run_prefixed "discord" "\033[0;35m" "$ROOT_DIR/bots" "$VENV_PYTHON" discord_bot.py
fi

if [ "$START_TELEGRAM" = true ]; then
    run_prefixed "telegram" "\033[0;33m" "$ROOT_DIR/bots" "$VENV_PYTHON" telegram_bot.py
fi

# ------------------------------------------------------------------------------
# 8. Ready banner with URLs
# ------------------------------------------------------------------------------
echo ""
echo "=============================================================="
echo "  DevMate is running!"
echo "  - App:      http://localhost:5173"
echo "  - API docs: http://localhost:8000/docs"
if [ "$START_DISCORD" = true ]; then  echo "  - Bot:      Discord bot active"; fi
if [ "$START_TELEGRAM" = true ]; then echo "  - Bot:      Telegram bot active"; fi
echo "  Press Ctrl+C to stop all services cleanly."
echo "=============================================================="
echo ""

# Wait for all background services
wait "${pids[@]}" 2>/dev/null || true
