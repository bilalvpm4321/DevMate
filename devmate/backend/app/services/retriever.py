"""Dependency-free BM25 retriever over code chunks with symbol and path boosting."""
import math
import re
from collections import Counter

from ..db import db

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_STOP = {
    "the", "a", "an", "is", "are", "of", "to", "in", "and", "or", "how", "does", "do", "what",
    "where", "this", "that", "it", "for", "with", "work", "works", "project", "repository",
    "can", "you", "tell", "me", "about",
}

DOWNRANK_PATTERNS = ("test", "spec", "migration", "package-lock.json", "yarn.lock", "cargo.lock", "pnpm-lock")
DOWNRANK_EXTS = (".md", ".txt", ".map")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _WORD.findall(text):
        parts = [p.lower() for p in _CAMEL.findall(word)]
        tokens.append(word.lower())
        if len(parts) > 1:
            tokens.extend(parts)
    return [t for t in tokens if t not in _STOP and len(t) > 1]


class BM25Index:
    def __init__(self, rows: list[dict], k1: float = 1.4, b: float = 0.75):
        self.rows, self.k1, self.b = rows, k1, b

        # Weighting: boost file path tokens (3x) and extracted symbol names (3x)
        self.docs = []
        for r in rows:
            path_tokens = tokenize(r.get("path", "")) * 3
            symbol_tokens = tokenize(r.get("symbol", "")) * 3
            content_tokens = tokenize(r.get("content", ""))
            self.docs.append(Counter(path_tokens + symbol_tokens + content_tokens))

        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 6) -> list[tuple[dict, float]]:
        terms = tokenize(query)
        if not terms:
            return []

        query_lower = query.lower()
        wants_tests = any(t in query_lower for t in ("test", "spec", "mock", "unit"))
        wants_docs = any(t in query_lower for t in ("readme", "doc", "markdown"))
        wants_migrations = "migration" in query_lower

        scored = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for t in terms:
                f = doc.get(t, 0)
                if f:
                    norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg))
                    score += self.idf.get(t, 0) * norm

            if score > 0:
                row = self.rows[i]
                path_lower = row.get("path", "").lower()

                # Down-rank lock files, tests and docs unless explicitly asked
                is_test_file = "test" in path_lower or "spec" in path_lower
                is_doc_file = any(path_lower.endswith(ext) for ext in DOWNRANK_EXTS)
                is_migration = "migration" in path_lower

                if is_test_file and not wants_tests:
                    score *= 0.35
                elif is_doc_file and not wants_docs:
                    score *= 0.5
                elif is_migration and not wants_migrations:
                    score *= 0.4

                # Boost key implementation files
                if any(core in path_lower for core in ("main", "app", "router", "model", "schema", "service", "auth")):
                    score *= 1.2

                scored.append((row, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


_cache: dict[int, BM25Index] = {}


def get_index(repo_id: int) -> BM25Index:
    if repo_id not in _cache:
        with db() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM code_chunks WHERE repo_id = ?", (repo_id,))]
        _cache[repo_id] = BM25Index(rows)
    return _cache[repo_id]


def invalidate(repo_id: int) -> None:
    _cache.pop(repo_id, None)
