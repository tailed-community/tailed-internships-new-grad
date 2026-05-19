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
]

EXPERIENCED_ROLE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\blead\b",
    r"\bhead of\b",
    r"\bexperienced\b",
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

    if is_likely_internship(normalized):
        return "internship"

    if _contains_pattern(normalized, EXPERIENCED_ROLE_PATTERNS):
        return None

    if is_likely_new_grad(normalized):
        return "new_grad"

    return None
