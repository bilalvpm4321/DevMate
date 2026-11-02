"""Split source files into structural or line-based chunks with symbol metadata."""
import ast
import re
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

# Structural split patterns for JS/TS
JS_TS_BOUNDARY = re.compile(
    r"""^(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*([A-Za-z0-9_$]+)|class\s+([A-Za-z0-9_$]+)|(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s+)?(?:\(|function))""",
    re.MULTILINE,
)


@dataclass
class Chunk:
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    symbol: str = ""


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


def chunk_by_lines(path: str, text: str, language: str, max_lines: int = 60, overlap: int = 8) -> list[Chunk]:
    """Standard sliding window fallback chunker."""
    lines = text.splitlines()
    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        if end < len(lines):
            for i in range(end, max(start + max_lines // 2, start + 1), -1):
                if not lines[i - 1].strip():
                    end = i
                    break
        body = "\n".join(lines[start:end]).strip("\n")
        if body.strip():
            header = f"// File: {path} (lines {start + 1}-{end})\n"
            chunks.append(Chunk(path, language, start + 1, end, header + body))
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_python(path: str, text: str) -> list[Chunk]:
    """Split Python files by top-level def/class with AST, falling back to line windows."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return chunk_by_lines(path, text, "python")

    lines = text.splitlines()
    total_lines = len(lines)
    if not total_lines:
        return []

    chunks: list[Chunk] = []
    top_defs: list[ast.AST] = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    if not top_defs:
        return chunk_by_lines(path, text, "python")

    # Header chunk (docstring + imports before first definition)
    first_def_line = top_defs[0].lineno
    if first_def_line > 1:
        header_text = "\n".join(lines[:first_def_line - 1]).strip()
        if header_text:
            chunks.append(
                Chunk(
                    path=path,
                    language="python",
                    start_line=1,
                    end_line=first_def_line - 1,
                    content=f"# File: {path} (lines 1-{first_def_line - 1}) | Module Imports & Config\n{header_text}",
                    symbol="module",
                )
            )

    for node in top_defs:
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", None)
        if end_line is None:
            # Fallback estimation if end_lineno is absent in older ast
            end_line = min(start_line + 50, total_lines)

        symbol_name = getattr(node, "name", "unknown")
        kind = "class" if isinstance(node, ast.ClassDef) else "def"
        body_slice = "\n".join(lines[start_line - 1:end_line]).strip()

        # If definition is reasonably sized, keep it intact
        if (end_line - start_line + 1) <= 90:
            header = f"# File: {path} (lines {start_line}-{end_line}) | {kind} {symbol_name}\n"
            chunks.append(
                Chunk(
                    path=path,
                    language="python",
                    start_line=start_line,
                    end_line=end_line,
                    content=header + body_slice,
                    symbol=symbol_name,
                )
            )
        else:
            # Sub-chunk very large classes or functions using sliding windows
            sub_chunks = chunk_by_lines(path, body_slice, "python", max_lines=70, overlap=10)
            for sc in sub_chunks:
                sc.start_line += (start_line - 1)
                sc.end_line += (start_line - 1)
                sc.symbol = symbol_name
                sc.content = f"# File: {path} (lines {sc.start_line}-{sc.end_line}) | {kind} {symbol_name}\n" + sc.content
                chunks.append(sc)

    return chunks if chunks else chunk_by_lines(path, text, "python")


def chunk_javascript_typescript(path: str, text: str, language: str) -> list[Chunk]:
    """Split JS/TS files by function/class/export boundaries, falling back to line windows."""
    lines = text.splitlines()
    total_lines = len(lines)
    if not total_lines:
        return []

    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        m = JS_TS_BOUNDARY.search(line)
        if m:
            name = m.group(1) or m.group(2) or m.group(3) or "export"
            boundaries.append((i, name))

    if len(boundaries) < 2:
        return chunk_by_lines(path, text, language)

    chunks: list[Chunk] = []
    # Module header
    if boundaries[0][0] > 1:
        header_text = "\n".join(lines[:boundaries[0][0] - 1]).strip()
        if header_text:
            chunks.append(
                Chunk(
                    path=path,
                    language=language,
                    start_line=1,
                    end_line=boundaries[0][0] - 1,
                    content=f"// File: {path} (lines 1-{boundaries[0][0] - 1}) | Imports & Header\n{header_text}",
                    symbol="module",
                )
            )

    for idx, (start_line, symbol_name) in enumerate(boundaries):
        end_line = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else total_lines
        body_slice = "\n".join(lines[start_line - 1:end_line]).strip()

        if (end_line - start_line + 1) <= 90:
            header = f"// File: {path} (lines {start_line}-{end_line}) | Symbol: {symbol_name}\n"
            chunks.append(
                Chunk(
                    path=path,
                    language=language,
                    start_line=start_line,
                    end_line=end_line,
                    content=header + body_slice,
                    symbol=symbol_name,
                )
            )
        else:
            sub_chunks = chunk_by_lines(path, body_slice, language, max_lines=70, overlap=10)
            for sc in sub_chunks:
                sc.start_line += (start_line - 1)
                sc.end_line += (start_line - 1)
                sc.symbol = symbol_name
                chunks.append(sc)

    return chunks if chunks else chunk_by_lines(path, text, language)


def chunk_file(path: str, text: str, max_lines: int = 60, overlap: int = 8) -> list[Chunk]:
    """Top-level chunker routing by language structure with fallback."""
    language = language_of(path) or "text"
    if language == "python":
        return chunk_python(path, text)
    elif language in ("javascript", "typescript"):
        return chunk_javascript_typescript(path, text, language)
    return chunk_by_lines(path, text, language, max_lines=max_lines, overlap=overlap)
