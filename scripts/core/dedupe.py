from __future__ import annotations

import re
from typing import Any


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_full: set[str] = set()
    seen_loose: set[str] = set()

    for job in jobs:
        job_id = _normalize_text(job.get("id"))
        if job_id and job_id in seen_ids:
            continue

        company = _normalize_text(job.get("company"))
        title = _normalize_text(job.get("title"))
        location = _normalize_text(job.get("location"))
        url = _normalize_text(job.get("url"))

        full_key = f"{company}::{title}::{location}::{url}"
        if full_key in seen_full:
            continue

        loose_key = f"{company}::{title}::{location}"
        if loose_key in seen_loose:
            continue

        if job_id:
            seen_ids.add(job_id)
        seen_full.add(full_key)
        seen_loose.add(loose_key)
        deduped.append(job)

    return deduped
