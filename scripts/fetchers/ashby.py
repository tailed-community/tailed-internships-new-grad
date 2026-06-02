from __future__ import annotations

from typing import Any
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

import requests


def _extract_ashby_slug_from_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    hostname = (parsed.hostname or "").lower()
    path_segments = [segment for segment in parsed.path.split("/") if segment]

    if hostname == "jobs.ashbyhq.com" and path_segments:
        return unquote(path_segments[0]).strip()

    if (
        hostname == "api.ashbyhq.com"
        and len(path_segments) >= 3
        and path_segments[0].lower() == "posting-api"
        and path_segments[1].lower() == "job-board"
    ):
        return unquote(path_segments[2]).strip()

    return ""


def build_ashby_jobs_url(company: dict[str, Any]) -> str:
    raw_url = str(company.get("url", "")).strip()
    slug = str(company.get("slug", "")).strip()

    if not slug and raw_url:
        slug = _extract_ashby_slug_from_url(raw_url)

    if not slug:
        raise ValueError("Missing Ashby job board name for company config.")

    return f"https://api.ashbyhq.com/posting-api/job-board/{quote(slug, safe='')}?includeCompensation=false"


def _build_ashby_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def fetch_ashby_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))

    try:
        jobs_url = build_ashby_jobs_url(company)
    except Exception as error:
        print(f"[ashby] {company_name}: invalid config ({error})")
        return []

    try:
        response = requests.get(
            jobs_url,
            headers=_build_ashby_request_headers(company),
            timeout=25,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as error:
        print(f"[ashby] {company_name}: request failed ({error})")
        return []
    except ValueError as error:
        print(f"[ashby] {company_name}: invalid JSON response ({error})")
        return []

    if not isinstance(body, dict):
        print(f"[ashby] {company_name}: expected a JSON object response.")
        return []

    raw_jobs = body.get("jobs")
    if not isinstance(raw_jobs, list):
        print(f"[ashby] {company_name}: expected a 'jobs' list in response.")
        return []

    jobs: list[dict[str, Any]] = []
    skipped_unlisted_count = 0
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        if item.get("isListed") is False:
            skipped_unlisted_count += 1
            continue
        enriched = dict(item)
        enriched.pop("descriptionHtml", None)
        enriched.pop("descriptionPlain", None)
        enriched["_company"] = company_name
        enriched["_source"] = "ashby"
        enriched["_career_url"] = str(company.get("url", "")).strip()
        jobs.append(enriched)

    if skipped_unlisted_count:
        print(
            f"[ashby] {company_name}: skipped {skipped_unlisted_count} unlisted postings"
        )
    print(f"[ashby] {company_name}: fetched {len(jobs)} published postings")
    return jobs
