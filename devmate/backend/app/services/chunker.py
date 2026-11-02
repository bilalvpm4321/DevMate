"""Split source files into overlapping, line-numbered chunks that prefer natural boundaries."""
from dataclasses import dataclass
from pathlib import PurePosixPath

LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".kt": "kotlin",
    ".swift": "swift", ".sql": "sql", ".sh": "bash", ".html": "html", ".css": "css",
    ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".md": "markdown",
    ".txt": "text", ".env.example": "env",
}
IGNORED_DIRS = {
    "node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", "vendor",
    ".next", "target", "coverage", ".idea", ".vscode", "site-packages",
}
IGNORED_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "go.sum"}
SECRET_MARKERS = (".env", ".pem", ".key", "id_rsa", "secrets", "credentials")


@dataclass
class Chunk:
    path: str
    language: str
    start_line: int
    end_line: int
    content: str


def language_of(path: str) -> str | None:
    name = PurePosixPath(path).name.lower()
    if name.endswith(".env.example"):
        return "env"
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


def should_index(path: str) -> bool:
    """Skip vendored/generated folders, lock files, secrets and unsupported file types."""
    p = PurePosixPath(path)
    if any(part in IGNORED_DIRS for part in p.parts) or p.name in IGNORED_FILES:
        return False
    name = p.name.lower()
    if any(m in name for m in SECRET_MARKERS) and not name.endswith(".example"):
        return False
    if name.endswith(".min.js") or name.endswith(".map"):
        return False
    return language_of(path) is not None


def chunk_file(path: str, text: str, max_lines: int = 60, overlap: int = 8) -> list[Chunk]:
    language = language_of(path) or "text"
    lines = text.splitlines()
    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        if end < len(lines):  # prefer to cut on a blank line near the end of the window
            for i in range(end, max(start + max_lines // 2, start + 1), -1):
                if not lines[i - 1].strip():
                    end = i
                    break
        body = "\n".join(lines[start:end]).strip("\n")
        if body.strip():
            chunks.append(Chunk(path, language, start + 1, end, body))
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks
