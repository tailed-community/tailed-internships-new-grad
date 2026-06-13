from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

import requests


SMARTRECRUITERS_SEARCH_TERMS = [
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

SMARTRECRUITERS_PAGE_SIZE = 100
SMARTRECRUITERS_MAX_PAGES_PER_TERM = 1
SMARTRECRUITERS_RELEVANT_PATTERN = re.compile(
    r"\b(intern|internship|co-?op|student|new grad|new graduate|early career|entry[- ]level|graduate)\b",
    flags=re.IGNORECASE,
)


def _extract_slug_from_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    path_segments = [unquote(segment).strip() for segment in parsed.path.split("/") if segment]

    if host == "api.smartrecruiters.com":
        lowered = [segment.lower() for segment in path_segments]
        if "companies" in lowered:
            index = lowered.index("companies")
            if index + 1 < len(path_segments):
                return path_segments[index + 1]

    if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"} and path_segments:
        lowered = [segment.lower() for segment in path_segments]
        if path_segments[0].lower() == "oneclick-ui" and "company" in lowered:
            index = lowered.index("company")
            if index + 1 < len(path_segments):
                return path_segments[index + 1]
        return path_segments[0]

    return ""


def _company_slug(company: dict[str, Any]) -> str:
    slug = str(company.get("slug", "")).strip()
    if slug:
        return slug

    raw_url = str(company.get("url", "")).strip()
    slug = _extract_slug_from_url(raw_url)
    if not slug:
        raise ValueError("Missing SmartRecruiters company slug for company config.")
    return slug


def _build_smartrecruiters_request_headers(company: dict[str, Any]) -> dict[str, str]:
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
        search_terms = SMARTRECRUITERS_SEARCH_TERMS
    return [str(term).strip() for term in search_terms if str(term).strip()]


def _job_url(slug: str, job_id: str) -> str:
    return f"https://jobs.smartrecruiters.com/{quote(slug, safe='')}/{quote(job_id, safe='')}"


def _label(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if isinstance(value, dict):
        return " ".join(
            str(value.get(field, "")).strip()
            for field in ("id", "label")
            if str(value.get(field, "")).strip()
        )
    return ""


def _is_relevant_job(item: dict[str, Any]) -> bool:
    searchable_text = " ".join(
        part
        for part in (
            str(item.get("name", "")).strip(),
            str(item.get("refNumber", "")).strip(),
            _label(item, "typeOfEmployment"),
            _label(item, "experienceLevel"),
        )
        if part
    )
    return SMARTRECRUITERS_RELEVANT_PATTERN.search(searchable_text) is not None


def fetch_smartrecruiters_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    try:
        slug = _company_slug(company)
    except Exception as error:
        print(f"[smartrecruiters] {company_name}: invalid config ({error})")
        return []

    session = requests.Session()
    session.headers.update(_build_smartrecruiters_request_headers(company))
    url = f"https://api.smartrecruiters.com/v1/companies/{quote(slug, safe='')}/postings"
    jobs_by_id: dict[str, dict[str, Any]] = {}
    total_pages = 0

    try:
        for search_term in _search_terms(company):
            for page in range(SMARTRECRUITERS_MAX_PAGES_PER_TERM):
                offset = page * SMARTRECRUITERS_PAGE_SIZE
                response = session.get(
                    url,
                    params={
                        "q": search_term,
                        "limit": SMARTRECRUITERS_PAGE_SIZE,
                        "offset": offset,
                    },
                    timeout=25,
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    break

                raw_jobs = body.get("content")
                if not isinstance(raw_jobs, list) or not raw_jobs:
                    break

                total_pages += 1
                for item in raw_jobs:
                    if not isinstance(item, dict):
                        continue
                    job_id = str(item.get("id", "")).strip()
                    title = str(item.get("name", "")).strip()
                    if not job_id or not title:
                        continue
                    if not _is_relevant_job(item):
                        continue

                    enriched = dict(item)
                    enriched["id"] = job_id
                    enriched["title"] = title
                    enriched["_company"] = company_name
                    enriched["_source"] = "smartrecruiters"
                    enriched["_career_url"] = str(company.get("url", "")).strip()
                    enriched["_url"] = _job_url(slug, job_id)
                    enriched["_search_term"] = search_term
                    enriched["_page"] = page
                    jobs_by_id[job_id] = enriched

                total_found = body.get("totalFound")
                if not isinstance(total_found, int) or offset + len(raw_jobs) >= total_found:
                    break
    except requests.RequestException as error:
        print(f"[smartrecruiters] {company_name}: request failed ({error})")
        return list(jobs_by_id.values())
    except ValueError as error:
        print(f"[smartrecruiters] {company_name}: invalid JSON response ({error})")
        return list(jobs_by_id.values())

    jobs = list(jobs_by_id.values())
    print(
        f"[smartrecruiters] {company_name}: fetched {len(jobs)} postings "
        f"across {total_pages} search pages"
    )
    return jobs
