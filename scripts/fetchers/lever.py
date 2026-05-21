from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests


def build_lever_postings_url(company: dict[str, Any]) -> str:
    raw_url = str(company.get("url", "")).strip()
    slug = str(company.get("slug", "")).strip().lower()

    parsed = urlparse(raw_url) if raw_url else None
    if not slug and parsed is not None:
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        if path_segments:
            slug = path_segments[0].strip().lower()

    if not slug:
        raise ValueError("Missing Lever slug for company config.")

    host = parsed.netloc.lower() if parsed is not None else ""
    api_host = "api.eu.lever.co" if host == "jobs.eu.lever.co" else "api.lever.co"
    return f"https://{api_host}/v0/postings/{slug}?mode=json"


def _build_lever_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def fetch_lever_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))

    try:
        postings_url = build_lever_postings_url(company)
    except Exception as error:
        print(f"[lever] {company_name}: invalid config ({error})")
        return []

    try:
        response = requests.get(
            postings_url,
            headers=_build_lever_request_headers(company),
            timeout=25,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as error:
        print(f"[lever] {company_name}: request failed ({error})")
        return []
    except ValueError as error:
        print(f"[lever] {company_name}: invalid JSON response ({error})")
        return []

    if not isinstance(body, list):
        print(f"[lever] {company_name}: expected a JSON list response.")
        return []

    jobs: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        enriched["_company"] = company_name
        enriched["_source"] = "lever"
        enriched["_career_url"] = str(company.get("url", "")).strip()
        jobs.append(enriched)

    print(f"[lever] {company_name}: fetched {len(jobs)} published postings")
    return jobs
