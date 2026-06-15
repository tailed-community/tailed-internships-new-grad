from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

import requests


WORKABLE_SEARCH_TERMS = [
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

WORKABLE_RELEVANT_PATTERN = re.compile(
    r"\b(intern|internship|co-?op|student|new grad|new graduate|early career|entry[- ]level|graduate)\b",
    flags=re.IGNORECASE,
)


def _extract_slug_from_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    path_segments = [unquote(segment).strip() for segment in parsed.path.split("/") if segment]
    if host != "apply.workable.com" or not path_segments:
        return ""

    lowered = [segment.lower() for segment in path_segments]
    if len(path_segments) >= 4 and lowered[:3] == ["api", "v3", "accounts"]:
        return path_segments[3]
    if lowered[0] != "api":
        return path_segments[0]
    return ""


def _company_slug(company: dict[str, Any]) -> str:
    slug = str(company.get("slug", "")).strip()
    if slug:
        return slug

    raw_url = str(company.get("url", "")).strip()
    slug = _extract_slug_from_url(raw_url)
    if not slug:
        raise ValueError("Missing Workable account slug for company config.")
    return slug


def _build_workable_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def _search_terms(company: dict[str, Any]) -> list[str]:
    search_terms = company.get("search_terms")
    if not isinstance(search_terms, list) or not search_terms:
        search_terms = WORKABLE_SEARCH_TERMS

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


def _searchable_department(item: dict[str, Any]) -> str:
    department = item.get("department")
    if isinstance(department, list):
        return " ".join(str(part).strip() for part in department if str(part).strip())
    if isinstance(department, str):
        return department.strip()
    return ""


def _is_relevant_job(item: dict[str, Any]) -> bool:
    searchable_text = " ".join(
        part
        for part in (
            str(item.get("title", "")).strip(),
            str(item.get("code", "")).strip(),
            str(item.get("type", "")).strip(),
            _searchable_department(item),
        )
        if part
    )
    return WORKABLE_RELEVANT_PATTERN.search(searchable_text) is not None


def _job_url(slug: str, item: dict[str, Any]) -> str:
    shortcode = str(item.get("shortcode", "")).strip()
    if shortcode:
        return f"https://apply.workable.com/{quote(slug, safe='')}/j/{quote(shortcode, safe='')}/"
    return f"https://apply.workable.com/{quote(slug, safe='')}/"


def fetch_workable_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    try:
        slug = _company_slug(company)
    except Exception as error:
        print(f"[workable] {company_name}: invalid config ({error})")
        return []

    session = requests.Session()
    session.headers.update(_build_workable_request_headers(company))
    url = f"https://apply.workable.com/api/v3/accounts/{quote(slug, safe='')}/jobs"
    jobs_by_id: dict[str, dict[str, Any]] = {}
    request_count = 0

    try:
        for search_term in _search_terms(company):
            response = session.post(url, json={"query": search_term}, timeout=25)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                continue

            raw_jobs = body.get("results")
            if not isinstance(raw_jobs, list):
                continue
            request_count += 1

            for item in raw_jobs:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id") or item.get("shortcode") or "").strip()
                title = str(item.get("title", "")).strip()
                if not job_id or not title:
                    continue
                if not _is_relevant_job(item):
                    continue

                enriched = dict(item)
                enriched["id"] = job_id
                enriched["title"] = title
                enriched["_company"] = company_name
                enriched["_source"] = "workable"
                enriched["_career_url"] = str(company.get("url", "")).strip()
                enriched["_url"] = _job_url(slug, item)
                enriched["_search_term"] = search_term
                jobs_by_id[job_id] = enriched
    except requests.RequestException as error:
        print(f"[workable] {company_name}: request failed ({error})")
        return list(jobs_by_id.values())
    except ValueError as error:
        print(f"[workable] {company_name}: invalid JSON response ({error})")
        return list(jobs_by_id.values())

    jobs = list(jobs_by_id.values())
    print(
        f"[workable] {company_name}: fetched {len(jobs)} postings "
        f"across {request_count} search requests"
    )
    return jobs
