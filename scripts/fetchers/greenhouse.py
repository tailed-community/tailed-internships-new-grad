from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests


def build_greenhouse_jobs_url(company: dict[str, Any]) -> str:
    raw_url = str(company.get("url", "")).strip()
    slug = str(company.get("slug", "")).strip().lower()

    parsed = urlparse(raw_url) if raw_url else None
    if not slug and parsed is not None:
        hostname = (parsed.hostname or "").lower()
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        if hostname == "boards.greenhouse.io" and path_segments:
            slug = path_segments[0].strip().lower()
        elif (
            hostname == "boards-api.greenhouse.io"
            and len(path_segments) >= 3
            and path_segments[0].lower() == "v1"
            and path_segments[1].lower() == "boards"
        ):
            slug = path_segments[2].strip().lower()

    if not slug:
        raise ValueError("Missing Greenhouse board token for company config.")

    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _build_greenhouse_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def fetch_greenhouse_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))

    try:
        jobs_url = build_greenhouse_jobs_url(company)
    except Exception as error:
        print(f"[greenhouse] {company_name}: invalid config ({error})")
        return []

    try:
        response = requests.get(
            jobs_url,
            headers=_build_greenhouse_request_headers(company),
            timeout=25,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as error:
        print(f"[greenhouse] {company_name}: request failed ({error})")
        return []
    except ValueError as error:
        print(f"[greenhouse] {company_name}: invalid JSON response ({error})")
        return []

    if not isinstance(body, dict):
        print(f"[greenhouse] {company_name}: expected a JSON object response.")
        return []

    raw_jobs = body.get("jobs")
    if not isinstance(raw_jobs, list):
        print(f"[greenhouse] {company_name}: expected a 'jobs' list in response.")
        return []

    jobs: list[dict[str, Any]] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        enriched["_company"] = company_name
        enriched["_source"] = "greenhouse"
        enriched["_career_url"] = str(company.get("url", "")).strip()
        jobs.append(enriched)

    print(f"[greenhouse] {company_name}: fetched {len(jobs)} published postings")
    return jobs
