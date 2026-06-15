from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlparse

import requests


RIPPLING_SEARCH_TERMS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "student",
    "new grad",
    "new graduate",
    "early career",
    "entry level",
    "graduate",
]

RIPPLING_PAGE_SIZE = 1000
RIPPLING_RELEVANT_PATTERN = re.compile(
    r"\b(intern|internship|co-?op|student|new grad|new graduate|early career|entry[- ]level|graduate)\b",
    flags=re.IGNORECASE,
)


def _extract_slug_from_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    path_segments = [unquote(segment).strip() for segment in parsed.path.split("/") if segment]
    if host != "ats.rippling.com" or not path_segments:
        return ""

    if len(path_segments) >= 2 and path_segments[1].lower() == "jobs":
        return path_segments[0]
    if len(path_segments) >= 3 and path_segments[2].lower() == "jobs":
        return path_segments[1]
    return ""


def _company_slug(company: dict[str, Any]) -> str:
    slug = str(company.get("slug", "")).strip()
    if slug:
        return slug

    raw_url = str(company.get("url", "")).strip()
    slug = _extract_slug_from_url(raw_url)
    if not slug:
        raise ValueError("Missing Rippling job board slug for company config.")
    return slug


def _build_rippling_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def _search_terms(company: dict[str, Any]) -> list[str]:
    search_terms = company.get("search_terms")
    if not isinstance(search_terms, list) or not search_terms:
        search_terms = RIPPLING_SEARCH_TERMS

    terms: list[str] = []
    seen: set[str] = set()
    for term in search_terms:
        value = str(term).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        terms.append(value)
    return terms


def _is_relevant_job(item: dict[str, Any]) -> bool:
    title = str(item.get("name", "")).strip()
    department = item.get("department")
    department_name = ""
    if isinstance(department, dict):
        department_name = str(department.get("name", "")).strip()
    searchable_text = " ".join(part for part in (title, department_name) if part)
    return RIPPLING_RELEVANT_PATTERN.search(searchable_text) is not None


def _merge_locations(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing_locations = existing.setdefault("locations", [])
    if not isinstance(existing_locations, list):
        existing["locations"] = []
        existing_locations = existing["locations"]

    seen = {
        str(location.get("name", "")).strip().casefold()
        for location in existing_locations
        if isinstance(location, dict)
    }
    incoming_locations = incoming.get("locations")
    if not isinstance(incoming_locations, list):
        return

    for location in incoming_locations:
        if not isinstance(location, dict):
            continue
        key = str(location.get("name", "")).strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        existing_locations.append(location)


def fetch_rippling_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    try:
        slug = _company_slug(company)
    except Exception as error:
        print(f"[rippling] {company_name}: invalid config ({error})")
        return []

    session = requests.Session()
    session.headers.update(_build_rippling_request_headers(company))
    url = f"https://ats.rippling.com/api/v2/board/{slug}/jobs"
    jobs_by_id: dict[str, dict[str, Any]] = {}
    request_count = 0

    try:
        for search_term in _search_terms(company):
            response = session.get(
                url,
                params={
                    "groupJobsByLocation": "false",
                    "searchQuery": search_term,
                    "page": 0,
                    "pageSize": RIPPLING_PAGE_SIZE,
                },
                timeout=25,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                continue

            raw_jobs = body.get("items")
            if not isinstance(raw_jobs, list):
                continue
            request_count += 1

            for item in raw_jobs:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id", "")).strip()
                title = str(item.get("name", "")).strip()
                if not job_id or not title:
                    continue
                if not _is_relevant_job(item):
                    continue

                existing = jobs_by_id.get(job_id)
                if existing is not None:
                    _merge_locations(existing, item)
                    continue

                enriched = dict(item)
                enriched["id"] = job_id
                enriched["title"] = title
                enriched["_company"] = company_name
                enriched["_source"] = "rippling"
                enriched["_career_url"] = str(company.get("url", "")).strip()
                enriched["_url"] = str(item.get("url", "")).strip() or (
                    f"https://ats.rippling.com/{slug}/jobs/{job_id}"
                )
                enriched["_search_term"] = search_term
                jobs_by_id[job_id] = enriched
    except requests.RequestException as error:
        print(f"[rippling] {company_name}: request failed ({error})")
        return list(jobs_by_id.values())
    except ValueError as error:
        print(f"[rippling] {company_name}: invalid JSON response ({error})")
        return list(jobs_by_id.values())

    jobs = list(jobs_by_id.values())
    print(
        f"[rippling] {company_name}: fetched {len(jobs)} postings "
        f"across {request_count} search requests"
    )
    return jobs
