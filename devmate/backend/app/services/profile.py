"""Deterministic project profiling and file summarization for deep repo understanding."""
import asyncio
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from ..db import db
from . import llm

# Known signature patterns for technologies
TECH_SIGNATURES: dict[str, dict[str, list[str]]] = {
    "frameworks": {
        "FastAPI": ["fastapi"],
        "Flask": ["flask"],
        "Django": ["django"],
        "Express": ["express"],
        "NestJS": ["@nestjs/core", "@nestjs/common"],
        "Next.js": ["next", "next/router", "next/navigation", "next.config"],
        "React": ["react", "react-dom"],
        "Vue": ["vue", "vue-router", "pinia", "vuex"],
        "Svelte": ["svelte", "@sveltejs/kit"],
        "Angular": ["@angular/core"],
        "Spring Boot": ["spring-boot", "org.springframework"],
        "Go Gin/Fiber": ["github.com/gin-gonic/gin", "github.com/gofiber/fiber"],
        "Rust Actix/Axum": ["actix-web", "axum"],
    },
    "databases_orms": {
        "Prisma": ["@prisma/client", "prisma"],
        "SQLAlchemy": ["sqlalchemy"],
        "Alembic": ["alembic"],
        "TypeORM": ["typeorm"],
        "Mongoose": ["mongoose"],
        "Drizzle": ["drizzle-orm"],
        "PostgreSQL": ["pg", "psycopg2", "psycopg", "postgres"],
        "Neon": ["@neondatabase/serverless", "neon"],
        "Supabase": ["@supabase/supabase-js", "supabase"],
        "SQLite": ["sqlite3", "aiosqlite"],
        "MySQL": ["mysql2", "pymysql", "mysql"],
        "MongoDB": ["mongodb", "pymongo"],
        "Redis": ["redis", "ioredis", "aioredis"],
    },
    "auth": {
        "JWT": ["jsonwebtoken", "pyjwt", "jose"],
        "NextAuth": ["next-auth", "@auth/core"],
        "Firebase Auth": ["firebase/auth", "firebase-admin"],
        "Clerk": ["@clerk/nextjs", "@clerk/clerk-sdk-node"],
        "Bcrypt": ["bcrypt", "bcryptjs", "passlib"],
        "OAuth": ["oauth", "passport"],
    },
    "ai_services": {
        "Google Gemini": ["@google/generative-ai", "google-generativeai", "gemini"],
        "OpenAI": ["openai"],
        "Anthropic": ["@anthropic-ai/sdk", "anthropic"],
        "LangChain": ["langchain", "@langchain/core"],
        "LlamaIndex": ["llama-index", "llamaindex"],
    },
    "cloud_devops": {
        "Docker": ["dockerfile", "docker-compose"],
        "Vercel": ["vercel", "@vercel/kv", "@vercel/blob"],
        "AWS": ["aws-sdk", "boto3", "@aws-sdk"],
        "GitHub Actions": [".github/workflows"],
    },
    "styling": {
        "Tailwind CSS": ["tailwindcss", "tailwind.config"],
        "CSS Modules": [".module.css"],
        "Styled Components": ["styled-components"],
        "Material UI": ["@mui/material"],
        "Chakra UI": ["@chakra-ui/react"],
        "Shadcn UI": ["@radix-ui", "components/ui"],
    },
}

ENTRY_POINT_CANDIDATES = {
    "main.py", "app.py", "wsgi.py", "asgi.py", "run.py", "manage.py",
    "index.js", "server.js", "app.js", "main.js",
    "index.ts", "server.ts", "app.ts", "main.ts",
    "main.tsx", "index.tsx", "app.tsx",
    "src/main.py", "src/app.py", "src/index.ts", "src/main.ts", "src/main.tsx", "src/app.tsx",
    "src/app/layout.tsx", "src/app/page.tsx", "app/layout.tsx", "app/page.tsx",
    "pages/_app.tsx", "pages/index.tsx", "src/pages/_app.tsx",
}

ROUTE_REGEXES = [
    re.compile(r"""@(app|router|api)\.(get|post|put|delete|patch|options|head)\s*\(\s*["']([^"']+)["']""", re.IGNORECASE),
    re.compile(r"""(app|router)\.(get|post|put|delete|patch|use)\s*\(\s*["']([^"']+)["']""", re.IGNORECASE),
    re.compile(r"""path\s*\(\s*["']([^"']+)["']""", re.IGNORECASE),
]

NEXT_EXPORT_ROUTE = re.compile(r"""export\s+(async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)\b""")
PRISMA_MODEL = re.compile(r"""model\s+([A-Za-z0-9_]+)\s+\{""")
PYTHON_MODEL = re.compile(r"""class\s+([A-Za-z0-9_]+)\s*\((Base|models\.Model|SQLModel)\):""")
SQL_TABLE = re.compile(r"""CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_"`]+)""", re.IGNORECASE)
ENV_VAR_REGEX = re.compile(r"""^[A-Za-z_][A-Za-z0-9_]*(?=\s*=)""")
ENV_CODE_REGEX = re.compile(r"""(?:process\.env\.([A-Za-z_][A-Za-z0-9_]+)|os\.getenv\(["']([A-Za-z_][A-Za-z0-9_]+)["']\)|os\.environ\[["']([A-Za-z_][A-Za-z0-9_]+)["']\])""")


def build_project_profile(files: list[tuple[str, str]]) -> dict[str, Any]:
    """Deterministically extracts architecture, stack, models, routes and structure without LLM."""
    file_map = {path: text for path, text in files}
    total_files = len(files)
    total_lines = sum(len(text.splitlines()) for _, text in files)

    # 1. Languages and extension stats
    ext_counter: Counter = Counter()
    lang_counter: Counter = Counter()
    for path, _ in files:
        suffix = PurePosixPath(path).suffix.lower() or PurePosixPath(path).name.lower()
        ext_counter[suffix] += 1

    # 2. Folder tree (depth <= 3)
    dirs_set = set()
    for path, _ in files:
        parts = PurePosixPath(path).parts[:-1]
        for depth in range(1, min(len(parts) + 1, 4)):
            dirs_set.add("/".join(parts[:depth]))
    sorted_dirs = sorted(dirs_set)

    # 3. Detect manifests & dependencies
    manifests: dict[str, list[str]] = {}
    dep_text_pool: list[str] = []

    for path, text in files:
        name = PurePosixPath(path).name.lower()
        if name == "package.json":
            try:
                pkg = json.loads(text)
                deps = list(pkg.get("dependencies", {}).keys()) + list(pkg.get("devDependencies", {}).keys())
                manifests[path] = deps[:80]
                dep_text_pool.extend(deps)
            except Exception:
                pass
        elif name in ("requirements.txt", "requirements.in"):
            lines = [l.strip().split("==")[0].split(">=")[0].split("<=")[0].strip()
                     for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
            manifests[path] = lines[:80]
            dep_text_pool.extend(lines)
        elif name == "pyproject.toml":
            manifests[path] = [l.strip() for l in text.splitlines()[:50] if "dependencies" in l or "=" in l]
            dep_text_pool.append(text)
        elif name in ("cargo.toml", "go.mod", "pom.xml", "dockerfile", "docker-compose.yml"):
            manifests[path] = [l.strip() for l in text.splitlines()[:40] if l.strip() and not l.strip().startswith("#")]
            dep_text_pool.append(text)

    dep_haystack = " ".join(dep_text_pool).lower()

    # 4. Classify detected technologies
    detected_tech: dict[str, list[str]] = {}
    for category, signatures in TECH_SIGNATURES.items():
        matched = []
        for tech, keys in signatures.items():
            for key in keys:
                if key.lower() in dep_haystack or any(key.lower() in p.lower() for p, _ in files):
                    matched.append(tech)
                    break
        if matched:
            detected_tech[category] = matched

    # 5. Entry points
    detected_entries = []
    for path, _ in files:
        p_clean = path.replace("\\", "/").lower()
        if p_clean in ENTRY_POINT_CANDIDATES or PurePosixPath(p_clean).name in ENTRY_POINT_CANDIDATES:
            detected_entries.append(path)

    # 6. API routes
    api_routes: list[dict[str, str]] = []
    for path, text in files:
        p_lower = path.lower()
        if any(term in p_lower for term in ("route", "router", "api", "controller", "endpoint", "main", "app")):
            # Check route handlers in Next.js app router
            if "/api/" in p_lower or p_lower.startswith("app/") or "/routes/" in p_lower:
                for match in NEXT_EXPORT_ROUTE.finditer(text):
                    method = match.group(2)
                    api_routes.append({"method": method, "route": path, "file": path})
            # Python / Express routes
            for regex in ROUTE_REGEXES:
                for match in regex.finditer(text):
                    if len(match.groups()) == 3:
                        method = match.group(2).upper()
                        route = match.group(3)
                    elif len(match.groups()) == 1:
                        method = "GET"
                        route = match.group(1)
                    else:
                        continue
                    if len(api_routes) < 60:
                        api_routes.append({"method": method, "route": route, "file": path})

    # 7. Database models & tables
    db_models: list[dict[str, str]] = []
    for path, text in files:
        p_lower = path.lower()
        if any(term in p_lower for term in ("model", "schema", "db", "entity", "prisma", "migration")):
            for m in PRISMA_MODEL.finditer(text):
                db_models.append({"name": m.group(1), "kind": "Prisma Model", "file": path})
            for m in PYTHON_MODEL.finditer(text):
                db_models.append({"name": m.group(1), "kind": "Python Model", "file": path})
            for m in SQL_TABLE.finditer(text):
                clean_name = m.group(2).strip('"` ')
                if not any(dm["name"] == clean_name for dm in db_models):
                    db_models.append({"name": clean_name, "kind": "SQL Table", "file": path})

    # 8. Frontend pages / routes
    frontend_pages = []
    for path, _ in files:
        p = path.replace("\\", "/")
        if (p.startswith("pages/") or p.startswith("src/pages/") or
            p.startswith("app/") or p.startswith("src/app/") or
            p.startswith("src/views/")) and not any(part.startswith("_") for part in PurePosixPath(p).parts):
            if not p.endswith(".css") and not p.endswith(".test.ts"):
                frontend_pages.append(p)

    # 9. Environment variables (names ONLY)
    env_vars = set()
    for path, text in files:
        name = PurePosixPath(path).name.lower()
        if name.endswith(".env.example") or name.endswith(".env.sample") or name == ".env.template":
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    m = ENV_VAR_REGEX.match(line)
                    if m:
                        env_vars.add(m.group(0))
        # Code extractions
        for m in ENV_CODE_REGEX.finditer(text):
            found = m.group(1) or m.group(2) or m.group(3)
            if found and len(found) > 2 and found.isupper():
                env_vars.add(found)

    # 10. Commands & scripts
    scripts: dict[str, str] = {}
    for path, text in files:
        if PurePosixPath(path).name.lower() == "package.json":
            try:
                pkg = json.loads(text)
                scripts.update(pkg.get("scripts", {}))
            except Exception:
                pass

    # 11. Tests
    test_files = [path for path, _ in files if "test" in path.lower() or "spec" in path.lower()]

    profile = {
        "stats": {
            "total_files": total_files,
            "total_lines": total_lines,
            "top_extensions": dict(ext_counter.most_common(8)),
        },
        "folder_tree": sorted_dirs[:40],
        "manifests": list(manifests.keys()),
        "technologies": detected_tech,
        "entry_points": detected_entries[:10],
        "api_routes": api_routes[:40],
        "db_models": db_models[:40],
        "frontend_pages": frontend_pages[:30],
        "env_vars": sorted(list(env_vars))[:40],
        "scripts": scripts,
        "test_files_count": len(test_files),
    }
    return profile


def format_profile_markdown(profile: dict[str, Any]) -> str:
    """Formats the extracted profile into a dense, informative Markdown context block."""
    tech_lines = []
    for cat, items in profile.get("technologies", {}).items():
        tech_lines.append(f"- **{cat.replace('_', ' ').title()}:** {', '.join(items)}")

    routes_lines = [f"- `{r.get('method', 'GET')} {r.get('route', '')}` (in `{r.get('file', '')}`)"
                    for r in profile.get("api_routes", [])[:15]]
    models_lines = [f"- `{m['name']}` ({m['kind']} in `{m['file']}`)"
                    for m in profile.get("db_models", [])[:15]]
    pages_lines = [f"- `{p}`" for p in profile.get("frontend_pages", [])[:15]]
    entries_lines = [f"- `{e}`" for e in profile.get("entry_points", [])]
    env_lines = [f"- `{v}`" for v in profile.get("env_vars", [])[:20]]
    scripts_lines = [f"- `npm run {k}`: `{v}`" for k, v in list(profile.get("scripts", {}).items())[:10]]

    sections = [
        "### Project Architecture & Profile (Inferred from Code)",
        f"**Scale:** {profile.get('stats', {}).get('total_files', 0)} files, ~{profile.get('stats', {}).get('total_lines', 0)} lines of code.",
    ]
    if tech_lines:
        sections.append("#### Detected Technologies & Libraries:\n" + "\n".join(tech_lines))
    if entries_lines:
        sections.append("#### Main Entry Points:\n" + "\n".join(entries_lines))
    if routes_lines:
        sections.append("#### Key API Routes & Endpoints:\n" + "\n".join(routes_lines))
    if models_lines:
        sections.append("#### Database Models & Tables:\n" + "\n".join(models_lines))
    if pages_lines:
        sections.append("#### Frontend Pages & Routes:\n" + "\n".join(pages_lines))
    if env_lines:
        sections.append("#### Environment Variables Required:\n" + "\n".join(env_lines))
    if scripts_lines:
        sections.append("#### Run & Build Commands:\n" + "\n".join(scripts_lines))
    if profile.get("folder_tree"):
        sections.append("#### Directory Structure:\n```\n" + "\n".join(profile["folder_tree"][:30]) + "\n```")

    return "\n\n".join(sections)


def select_key_files(files: list[tuple[str, str]], limit: int = 40) -> list[tuple[str, str]]:
    """Scores and selects the ~40 most representative files in the repository for summarization."""
    scored: list[tuple[float, str, str]] = []

    for path, text in files:
        p_clean = path.replace("\\", "/").lower()
        score = 0.0

        # Manifests and configs
        if p_clean in ("package.json", "requirements.txt", "pyproject.toml", "cargo.toml", "go.mod", "docker-compose.yml", "dockerfile"):
            score += 100.0
        elif any(cfg in p_clean for cfg in ("vite.config", "next.config", "tsconfig.json", "settings.py", "config.py", ".env.example")):
            score += 85.0
        # Entry points
        elif any(p_clean.endswith(entry) for entry in ENTRY_POINT_CANDIDATES):
            score += 95.0
        # Models and schemas
        elif any(m in p_clean for m in ("model", "schema", "db", "entity", "prisma")):
            score += 80.0
        # Routes and API
        elif any(r in p_clean for r in ("router", "route", "api", "controller", "endpoint")):
            score += 75.0
        # Core services and business logic
        elif any(s in p_clean for s in ("service", "lib", "util", "core", "client")):
            score += 65.0
        # Main UI components / pages
        elif any(ui in p_clean for ui in ("page", "app", "view", "component", "screen")):
            score += 55.0
        else:
            score += 10.0

        # Downrank tests, migrations, lockfiles
        if any(bad in p_clean for bad in ("test", "spec", "migration", "lock", "mock", ".min.")):
            score -= 60.0

        scored.append((score, path, text))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(path, text) for _, path, text in scored[:limit]]


async def summarize_important_files(repo_id: int, files: list[tuple[str, str]], commit_sha: str) -> list[dict[str, str]]:
    """Generates and caches 2-3 sentence summaries for the top ~40 files using Semaphore(5)."""
    key_files = select_key_files(files, limit=40)
    sem = asyncio.Semaphore(5)

    # Check cached summaries in database
    cached_map: dict[str, str] = {}
    with db() as conn:
        rows = conn.execute("SELECT path, commit_sha, summary FROM file_summaries WHERE repo_id = ?", (repo_id,)).fetchall()
        for r in rows:
            if r["commit_sha"] == commit_sha and r["summary"]:
                cached_map[r["path"]] = r["summary"]

    results: list[dict[str, str]] = []
    to_summarize: list[tuple[str, str]] = []

    for path, text in key_files:
        if path in cached_map:
            results.append({"path": path, "summary": cached_map[path]})
        else:
            to_summarize.append((path, text))

    async def _summarize_one(path: str, text: str) -> dict[str, str]:
        async with sem:
            lang = PurePosixPath(path).suffix.lstrip(".") or "text"
            sample = text[:3500]
            prompt = (
                f"File: {path}\n"
                f"```{lang}\n{sample}\n```\n\n"
                "In 2-3 concise sentences, explain:\n"
                "1. The purpose of this file in the overall project\n"
                "2. Its primary exports, functions or classes\n"
                "3. Key dependencies or imports"
            )
            system = "You are a concise code analyst. Return only the 2-3 sentence summary."
            summary = ""
            try:
                summary = await llm.generate(system, prompt)
            except Exception:
                summary = ""

            # Deterministic fallback if LLM is offline or fails
            if not summary:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                funcs = [l for l in lines if l.startswith("def ") or l.startswith("function ") or "export async function" in l][:3]
                classes = [l for l in lines if l.startswith("class ") or l.startswith("export class ") or l.startswith("model ")][:2]
                items = [f.split("(")[0].strip() for f in (classes + funcs)]
                summary = f"Defines {', '.join(items) if items else 'core logic for ' + path} with {len(lines)} lines."

            with db() as conn:
                conn.execute(
                    "INSERT INTO file_summaries (repo_id, path, commit_sha, summary) VALUES (?,?,?,?) "
                    "ON CONFLICT(repo_id, path) DO UPDATE SET commit_sha=excluded.commit_sha, summary=excluded.summary",
                    (repo_id, path, commit_sha, summary),
                )
            return {"path": path, "summary": summary}

    if to_summarize:
        new_summaries = await asyncio.gather(*[_summarize_one(path, text) for path, text in to_summarize])
        results.extend(new_summaries)

    return results


async def generate_project_summary(profile: dict[str, Any], readme_text: str | None, files: list[tuple[str, str]]) -> str:
    """Uses LLM to synthesize profile, README and key files into a cohesive project summary."""
    profile_md = format_profile_markdown(profile)
    readme_excerpt = (readme_text or "").strip()[:4000]

    prompt = (
        "Based on the following repository profile extracted from code and the README excerpt (if any), "
        "write an accurate, comprehensive summary of the project.\n\n"
        f"{profile_md}\n\n"
    )
    if readme_excerpt:
        prompt += f"#### README Excerpt:\n```markdown\n{readme_excerpt}\n```\n\n"

    prompt += (
        "Explain:\n"
        "1. What this project is and its primary real-world purpose.\n"
        "2. Who uses it and what problems it solves.\n"
        "3. Core architecture, main components, and data flow.\n"
        "4. Technology stack and how key parts connect."
    )

    system = (
        "You are an expert software architect. Infer the project purpose from code dependencies, "
        "routes, schemas, models, entry points and UI. If the README is short or missing, rely on the code structure. "
        "Never say 'the purpose is not described'."
    )
    try:
        summary = await llm.generate(system, prompt)
        if summary:
            return summary
    except Exception:
        pass

    # Deterministic fallback when offline
    frameworks = ", ".join(profile.get("technologies", {}).get("frameworks", ["Custom Application"]))
    databases = ", ".join(profile.get("technologies", {}).get("databases_orms", ["SQLite/Relational"]))
    entries = ", ".join(profile.get("entry_points", [])[:3])
    return (
        f"This repository is a {frameworks} application with {databases} backend storage. "
        f"It contains {profile.get('stats', {}).get('total_files', 0)} files. "
        f"Primary entry points include {entries or 'main module'}. "
        f"It exposes {len(profile.get('api_routes', []))} API routes and defines {len(profile.get('db_models', []))} data models."
    )
