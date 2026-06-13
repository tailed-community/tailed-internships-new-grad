from __future__ import annotations

from typing import Any
from urllib.parse import quote
from urllib.parse import urlparse

import requests


ORACLE_HCM_SEARCH_TERMS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "student",
    "new grad",
    "new graduate",
    "early career",
    "entry level",
]

ORACLE_HCM_PAGE_SIZE = 25
ORACLE_HCM_MAX_PAGES_PER_TERM = 3


def _company_host(company: dict[str, Any]) -> str:
    host = str(company.get("host", "")).strip().lower()
    if host:
        return host

    raw_url = str(company.get("url", "")).strip()
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Missing Oracle HCM host for company config.")
    return host


def _company_site(company: dict[str, Any]) -> str:
    site = str(company.get("site", "")).strip()
    if site:
        return site
    raise ValueError("Missing Oracle HCM site for company config.")


def _company_language(company: dict[str, Any]) -> str:
    language = str(company.get("language", "")).strip()
    return language or "en"


def _build_oracle_hcm_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def _build_job_url(host: str, language: str, site: str, job_id: str) -> str:
    return (
        f"https://{host}/hcmUI/CandidateExperience/"
        f"{quote(language, safe='')}/sites/{quote(site, safe='')}/job/{quote(job_id, safe='')}"
    )


def _search_terms(company: dict[str, Any]) -> list[str]:
    search_terms = company.get("search_terms")
    if not isinstance(search_terms, list) or not search_terms:
        search_terms = ORACLE_HCM_SEARCH_TERMS
    return [str(term).strip() for term in search_terms if str(term).strip()]


def _extract_requisition_list(body: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return [], 0

    search_result = items[0]
    if not isinstance(search_result, dict):
        return [], 0

    total_count = search_result.get("TotalJobsCount")
    total = total_count if isinstance(total_count, int) else 0
    raw_jobs = search_result.get("requisitionList")
    if not isinstance(raw_jobs, list):
        return [], total

    return [item for item in raw_jobs if isinstance(item, dict)], total


def fetch_oracle_hcm_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))

    try:
        host = _company_host(company)
        site = _company_site(company)
        language = _company_language(company)
    except Exception as error:
        print(f"[oracle_hcm] {company_name}: invalid config ({error})")
        return []

    session = requests.Session()
    session.headers.update(_build_oracle_hcm_request_headers(company))
    url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    jobs_by_id: dict[str, dict[str, Any]] = {}
    total_pages = 0

    try:
        for search_term in _search_terms(company):
            for page in range(ORACLE_HCM_MAX_PAGES_PER_TERM):
                offset = page * ORACLE_HCM_PAGE_SIZE
                finder = (
                    f"findReqs;siteNumber={site},keyword={search_term},"
                    f"sortBy=POSTING_DATES_DESC,offset={offset},limit={ORACLE_HCM_PAGE_SIZE}"
                )
                response = session.get(
                    url,
                    params={
                        "finder": finder,
                        "onlyData": "true",
                        "expand": "requisitionList",
                    },
                    timeout=25,
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    break

                raw_jobs, total_count = _extract_requisition_list(body)
                total_pages += 1
                if not raw_jobs:
                    break

                for item in raw_jobs:
                    job_id = str(item.get("Id", "")).strip()
                    title = str(item.get("Title", "")).strip()
                    if not job_id or not title:
                        continue

                    enriched = dict(item)
                    enriched["id"] = job_id
                    enriched["title"] = title
                    enriched["_company"] = company_name
                    enriched["_source"] = "oracle_hcm"
                    enriched["_career_url"] = str(company.get("url", "")).strip()
                    enriched["_url"] = _build_job_url(host, language, site, job_id)
                    enriched["_search_term"] = search_term
                    enriched["_page"] = page
                    jobs_by_id[job_id] = enriched

                if offset + len(raw_jobs) >= total_count:
                    break
    except requests.RequestException as error:
        print(f"[oracle_hcm] {company_name}: request failed ({error})")
        return list(jobs_by_id.values())
    except ValueError as error:
        print(f"[oracle_hcm] {company_name}: invalid JSON response ({error})")
        return list(jobs_by_id.values())

    jobs = list(jobs_by_id.values())
    print(
        f"[oracle_hcm] {company_name}: fetched {len(jobs)} postings "
        f"across {total_pages} search pages"
    )
    return jobs
