"""Deterministic README quality evaluator, cleaner, and section retriever."""
import math
import re
from collections import Counter
from typing import Any

BADGE_PATTERNS = [
    re.compile(r"""\[!\[.*?\]\(.*?\)\]\(.*?\)"""),
    re.compile(r"""!\[.*?\]\(https?://(?:img\.shields\.io|badge|actions/workflows|coveralls|codecov).*?\)"""),
    re.compile(r"""<a[^>]*><img[^>]*shields\.io[^>]*></a>""", re.I),
    re.compile(r"""<img[^>]*shields\.io[^>]*>""", re.I),
]

HTML_TAGS = re.compile(r"""<div[^>]*>|</div>|<p[^>]*>|</p>|<h[1-6][^>]*>|</h[1-6]>|<br\s*/?>""", re.I)
MARKDOWN_HEADING = re.compile(r"""^(#{1,6})\s+(.+)$""", re.M)

SECTION_KEYWORDS = {
    "overview": ["about", "overview", "introduction", "what is", "summary", "description"],
    "features": ["feature", "features", "capabilities", "what it does", "highlights"],
    "stack_arch": ["tech stack", "technologies", "architecture", "requirements", "prerequisites", "built with"],
    "install": ["installation", "install", "setup", "quick start", "getting started", "how to install"],
    "usage": ["usage", "how to run", "how to use", "running", "commands", "start"],
    "config_api": ["configuration", "environment", "env", "api", "endpoints", "docs", "documentation"],
}

BOILERPLATE_PATTERNS = [
    ("create react app", re.compile(r"""(getting started with create react app|bootstrapped with create react app)""", re.I), 45),
    ("vite boilerplate", re.compile(r"""(vite\s*\+\s*react|expand the eslint configuration|save to test hmr|plugins are available)""", re.I), 35),
    ("nextjs boilerplate", re.compile(r"""(easiest way to deploy your next\.js app|vercel platform from the creators of next\.js)""", re.I), 35),
    ("vue boilerplate", re.compile(r"""(recommended ide setup|customize configuration see vite configuration reference)""", re.I), 35),
]


def clean_readme(text: str) -> str:
    """Removes HTML noise, image badges and excessive spacing from README."""
    cleaned = text
    # Remove HTML comments
    cleaned = re.sub(r"""<!--.*?-->""", "", cleaned, flags=re.DOTALL)
    # Remove badges
    for pat in BADGE_PATTERNS:
        cleaned = pat.sub("", cleaned)
    # Remove wrapper tags
    cleaned = HTML_TAGS.sub("", cleaned)
    # Remove consecutive empty lines
    cleaned = re.sub(r"""\n{3,}""", "\n\n", cleaned)
    return cleaned.strip()


def extract_readmes(files: list[tuple[str, str]]) -> dict[str, str]:
    """Finds root README and monorepo READMEs in /backend and /frontend."""
    readmes: dict[str, str] = {}
    for path, content in files:
        p_clean = path.replace("\\", "/").strip("/")
        name = p_clean.split("/")[-1].lower()
        if name in ("readme.md", "readme.rst", "readme.txt", "readme"):
            readmes[p_clean] = content
    return readmes


def score_readme(text: str) -> tuple[int, str, str]:
    """Scores README from 0 to 100 using cheap rules only. Returns (score, quality, cleaned_text)."""
    if not text or not text.strip():
        return 0, "poor", ""

    cleaned = clean_readme(text)
    words = re.findall(r"\b[A-Za-z0-9_-]+\b", cleaned)
    word_count = len(words)

    if word_count < 25:
        return max(0, min(25, word_count)), "poor", cleaned

    score = 0

    # 1. Word count points (max 25)
    if word_count >= 400:
        score += 25
    elif word_count >= 200:
        score += 18
    elif word_count >= 100:
        score += 12
    else:
        score += 5

    # 2. Heading count points (max 20)
    headings = MARKDOWN_HEADING.findall(cleaned)
    num_headings = len(headings)
    if num_headings >= 6:
        score += 20
    elif num_headings >= 3:
        score += 14
    elif num_headings >= 1:
        score += 7

    # 3. Section coverage points (max 35)
    cleaned_lower = cleaned.lower()
    heading_text = " ".join(h[1].lower() for h in headings)
    for category, keywords in SECTION_KEYWORDS.items():
        found = any(k in heading_text for k in keywords) or any(f"\n{k}" in cleaned_lower for k in keywords)
        if found:
            score += 6  # ~6 pts per standard section found (up to ~36)

    # 4. Code block points (max 20)
    code_blocks = len(re.findall(r"""```""", cleaned)) // 2
    if code_blocks >= 4:
        score += 20
    elif code_blocks >= 2:
        score += 14
    elif code_blocks >= 1:
        score += 8

    # 5. Penalties for template / boilerplate
    total_penalty = 0
    for name, pattern, penalty in BOILERPLATE_PATTERNS:
        if pattern.search(cleaned):
            total_penalty += penalty

    # Check if mostly links/badges
    link_count = len(re.findall(r"""https?://""", cleaned))
    if word_count > 0 and (link_count / (word_count / 10)) > 2.0 and num_headings < 3:
        total_penalty += 25

    score = max(0, min(100, score - total_penalty))

    if score >= 60:
        quality = "detailed"
    elif score >= 30:
        quality = "basic"
    else:
        quality = "poor"

    return score, quality, cleaned


def split_readme_sections(readme_text: str) -> list[dict[str, str]]:
    """Splits a README into sections by Markdown headings."""
    cleaned = clean_readme(readme_text)
    lines = cleaned.splitlines()
    sections: list[dict[str, str]] = []
    current_title = "Overview"
    current_body: list[str] = []

    for line in lines:
        m = re.match(r"""^(#{1,4})\s+(.+)$""", line)
        if m:
            if current_body:
                body_text = "\n".join(current_body).strip()
                if body_text:
                    sections.append({"title": current_title, "content": body_text})
            current_title = m.group(2).strip()
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        body_text = "\n".join(current_body).strip()
        if body_text:
            sections.append({"title": current_title, "content": body_text})

    return sections if sections else [{"title": "Overview", "content": cleaned}]


def rank_readme_sections(sections: list[dict[str, str]], query: str, top_k: int = 4) -> list[dict[str, str]]:
    """Ranks README sections against a query using token overlap and keyword matches."""
    q_words = set(re.findall(r"\w+", query.lower()))
    stop_words = {"what", "is", "the", "of", "this", "project", "how", "to", "does", "it", "work", "and", "in"}
    query_terms = [w for w in q_words if w not in stop_words and len(w) > 1]
    if not query_terms:
        query_terms = list(q_words)

    scored = []
    for s in sections:
        title_lower = s["title"].lower()
        content_lower = s["content"].lower()
        score = 0.0

        for t in query_terms:
            if t in title_lower:
                score += 5.0
            score += content_lower.count(t) * 0.5

        # Overview questions prioritize top overview / architecture / features sections
        is_overview_q = any(term in query.lower() for term in ("purpose", "what is", "overview", "architecture", "stack", "features"))
        if is_overview_q and any(term in title_lower for term in ("overview", "about", "feature", "architecture", "what")):
            score += 8.0

        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:top_k]]
