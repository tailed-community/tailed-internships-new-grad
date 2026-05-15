from __future__ import annotations

from datetime import date
from typing import Any


def _job_key(job: dict[str, Any]) -> str:
    job_id = str(job.get("id", "")).strip()
    if job_id:
        return f"id::{job_id}"

    company = str(job.get("company", "")).strip().lower()
    title = str(job.get("title", "")).strip().lower()
    location = str(job.get("location", "")).strip().lower()
    url = str(job.get("url", "")).strip().lower()
    return f"fallback::{company}::{title}::{location}::{url}"


def _target_key(source: str, company: str) -> str:
    return f"{source.strip().lower()}::{company.strip().lower()}"


def _job_target_key(job: dict[str, Any]) -> str:
    source = str(job.get("source", "")).strip()
    company = str(job.get("company", "")).strip()
    return _target_key(source, company)


def merge_active_and_archive(
    existing_jobs: list[dict[str, Any]],
    fetched_jobs: list[dict[str, Any]],
    existing_archived_jobs: list[dict[str, Any]],
    touched_targets: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    today = date.today().isoformat()

    existing_by_key = {_job_key(job): job for job in existing_jobs if isinstance(job, dict)}
    archived_by_key = {_job_key(job): job for job in existing_archived_jobs if isinstance(job, dict)}
    normalized_touched_targets = {
        _target_key(source, company) for source, company in (touched_targets or set())
    }

    fetched_by_key = {_job_key(job): job for job in fetched_jobs if isinstance(job, dict)}
    fetched_keys = set(fetched_by_key.keys())

    normalized_fetched: list[dict[str, Any]] = []
    for key, job in fetched_by_key.items():
        merged = dict(job)
        existing = existing_by_key.get(key)
        archived = archived_by_key.get(key)

        if existing and existing.get("date_added"):
            merged["date_added"] = existing["date_added"]
        elif archived and archived.get("date_added"):
            merged["date_added"] = archived["date_added"]

        merged["active"] = True
        normalized_fetched.append(merged)

    active_jobs: list[dict[str, Any]] = []
    for job in existing_jobs:
        if not isinstance(job, dict):
            continue

        if _job_target_key(job) in normalized_touched_targets:
            continue

        carry = dict(job)
        carry["active"] = True
        active_jobs.append(carry)

    active_jobs.extend(normalized_fetched)

    archived_jobs_map = {
        _job_key(job): {**job, "active": False}
        for job in existing_archived_jobs
        if isinstance(job, dict)
    }

    # Restore previously archived jobs that reappeared.
    for restored_key in fetched_keys:
        if restored_key in archived_jobs_map:
            archived_jobs_map.pop(restored_key, None)

    # Archive missing jobs only for fetched Workday companies.
    for job in existing_jobs:
        if not isinstance(job, dict):
            continue
        if _job_target_key(job) not in normalized_touched_targets:
            continue

        key = _job_key(job)
        if key in fetched_keys:
            continue

        archived_job = dict(job)
        archived_job["active"] = False
        archived_job["date_archived"] = today
        archived_jobs_map[key] = archived_job

    archived_jobs = list(archived_jobs_map.values())

    return active_jobs, archived_jobs
