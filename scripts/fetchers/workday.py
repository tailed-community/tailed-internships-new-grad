from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests


def build_workday_jobs_url(company: dict[str, Any]) -> str:
    """Build the Workday jobs endpoint URL for a company config."""
    raw_url = str(company.get("url", "")).strip()
    if not raw_url:
        raise ValueError("Missing company url for Workday source.")

    parsed = urlparse(raw_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    tenant = str(company.get("tenant", "")).strip()
    site = str(company.get("site", "")).strip()

    # Fallbacks if tenant/site are not provided in company config.
    if not tenant:
        tenant = parsed.netloc.split(".")[0]
    if not site:
        site = parsed.path.strip("/").split("/")[0]

    if not tenant or not site:
        raise ValueError("Could not determine Workday tenant/site from company config.")

    return f"{origin}/wday/cxs/{tenant}/{site}/jobs"


def fetch_workday_search(
    company: dict[str, Any], search_term: str, timeout_seconds: int = 25
) -> list[dict[str, Any]]:
    """Fetch one Workday search term with pagination and return raw postings."""
    try:
        jobs_url = build_workday_jobs_url(company)
    except Exception as error:
        print(f"[workday] {company.get('company', 'Unknown')}: invalid config ({error})")
        return []

    raw_url = str(company.get("url", "")).strip()
    parsed = urlparse(raw_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
        "Origin": origin,
        "Referer": raw_url,
    }

    limit_raw = company.get("limit", 20)
    max_pages_raw = company.get("max_pages", 25)
    try:
        limit = max(1, int(limit_raw))
    except (TypeError, ValueError):
        limit = 20
    try:
        max_pages = max(1, int(max_pages_raw))
    except (TypeError, ValueError):
        max_pages = 25

    postings: list[dict[str, Any]] = []
    offset = 0
    pages_fetched = 0

    while True:
        if pages_fetched >= max_pages:
            print(
                f"[workday] {company.get('company', 'Unknown')} search '{search_term}': "
                f"reached max_pages={max_pages}"
            )
            break

        payload = {
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": search_term,
        }
        try:
            response = requests.post(
                jobs_url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as error:
            print(
                f"[workday] {company.get('company', 'Unknown')} search '{search_term}' "
                f"request failed at offset {offset}: {error}"
            )
            return postings
        except ValueError as error:
            print(
                f"[workday] {company.get('company', 'Unknown')} search '{search_term}' "
                f"returned invalid JSON at offset {offset}: {error}"
            )
            return postings

        page = body.get("jobPostings")
        if page is None:
            print(
                f"[workday] {company.get('company', 'Unknown')} search '{search_term}' "
                f"response missing 'jobPostings' at offset {offset}"
            )
            break
        if not isinstance(page, list):
            print(
                f"[workday] {company.get('company', 'Unknown')} search '{search_term}' "
                f"'jobPostings' is not a list at offset {offset}"
            )
            break
        if not page:
            break

        for item in page:
            if isinstance(item, dict):
                postings.append(item)

        print(
            f"[workday] {company.get('company', 'Unknown')} search '{search_term}': "
            f"+{len(page)} jobs (offset {offset})"
        )

        pages_fetched += 1

        if len(page) < limit:
            break

        offset += limit

    return postings


def _extract_first_location(raw_job: dict[str, Any]) -> str:
    locations = raw_job.get("locations")
    if not isinstance(locations, list) or not locations:
        return ""

    first = locations[0]
    if isinstance(first, dict):
        for key in ("location", "displayName", "city", "country"):
            value = first.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(first, str) and first.strip():
        return first.strip()
    return ""


def _raw_dedupe_key(raw_job: dict[str, Any]) -> str:
    external_path = str(raw_job.get("externalPath", "")).strip()
    if external_path:
        return f"path::{external_path.lower()}"

    raw_id = str(raw_job.get("id", "")).strip()
    if raw_id:
        return f"id::{raw_id.lower()}"

    title = str(raw_job.get("title", "")).strip().lower()
    locations_text = str(raw_job.get("locationsText", "")).strip().lower()
    if title and locations_text:
        return f"title_locations::{title}::{locations_text}"

    first_location = _extract_first_location(raw_job).lower()
    return f"title_first_location::{title}::{first_location}"


def fetch_workday_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch and dedupe Workday jobs across company search terms."""
    company_name = str(company.get("company", "Unknown"))
    search_terms = company.get("search_terms")
    if not isinstance(search_terms, list) or not search_terms:
        search_terms = ["intern", "student", "new grad"]

    all_jobs: list[dict[str, Any]] = []

    for term in search_terms:
        search_term = str(term).strip()
        if not search_term:
            continue

        print(f"Search term: {search_term}")
        results = fetch_workday_search(company, search_term)
        for job in results:
            enriched = dict(job)
            enriched["_company"] = company_name
            enriched["_source"] = "workday"
            enriched["_search_term"] = search_term
            enriched["_career_url"] = company.get("url")
            all_jobs.append(enriched)

    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for job in all_jobs:
        key = _raw_dedupe_key(job)
        if key in seen_keys:
            continue

        seen_keys.add(key)
        deduped.append(job)

    return deduped
