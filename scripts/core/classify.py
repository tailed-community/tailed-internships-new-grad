from __future__ import annotations

import re

INTERNSHIP_PATTERNS = [
    r"\bintern(ship)?s?\b",
    r"\bco[\s-]?op\b",
    r"\bstudent\b",
    r"\bsummer student\b",
    r"\bfall student\b",
    r"\bwinter student\b",
    r"\bstagiaire\b",
    r"\bstage\b",
]

NEW_GRAD_PATTERNS = [
    r"\bnew grad(uate)?s?\b",
    r"\bgraduate program\b",
    r"\bearly career\b",
    r"\bentry[\s-]?level\b",
    r"\buniversity graduate\b",
    r"\brecent graduate\b",
    r"\brotational program\b",
]

SENIOR_ROLE_KEYWORDS = [
    "senior",
    "staff",
    "principal",
    "director",
    "head of",
]


def _normalize_title(title: str) -> str:
    normalized = title.strip().lower()
    normalized = normalized.replace("–", "-")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _contains_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def is_likely_internship(title: str) -> bool:
    normalized = _normalize_title(title)
    if not normalized:
        return False
    return _contains_pattern(normalized, INTERNSHIP_PATTERNS)


def is_likely_new_grad(title: str) -> bool:
    normalized = _normalize_title(title)
    if not normalized:
        return False
    return _contains_pattern(normalized, NEW_GRAD_PATTERNS)


def classify_job_type(title: str) -> str | None:
    normalized = _normalize_title(title)
    if not normalized:
        return None

    # Keep clear internship/new-grad roles even if extra words are present.
    if is_likely_internship(normalized):
        return "internship"
    if is_likely_new_grad(normalized):
        return "new_grad"

    if _contains_pattern(
        normalized, [rf"\b{re.escape(keyword)}\b" for keyword in SENIOR_ROLE_KEYWORDS]
    ):
        return None

    return None
