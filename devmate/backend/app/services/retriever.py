"""Dependency-free BM25 retriever over code chunks.

Swap this class for FAISS / pgvector + Sentence-Transformers embeddings without changing callers:
it only needs `search(query, k)` returning [(chunk_row, score)].
"""
import math
import re
from collections import Counter

from ..db import db

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "and", "or", "how", "does", "do", "what",
         "where", "this", "that", "it", "for", "with", "work", "works", "project", "repository"}


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
        self.docs = [Counter(tokenize(r["path"] + " " + r["path"] + " " + r["content"])) for r in rows]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 6) -> list[tuple[dict, float]]:
        terms = tokenize(query)
        scored = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for t in terms:
                f = doc.get(t, 0)
                if f:
                    norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg))
                    score += self.idf.get(t, 0) * norm
            if score > 0:
                scored.append((self.rows[i], score))
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
