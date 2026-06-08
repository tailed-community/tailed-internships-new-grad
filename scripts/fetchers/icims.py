from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode
from urllib.parse import urlparse

import requests


ICIMS_SEARCH_TERMS = [
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

CLASSIC_MAX_PAGES_PER_TERM = 5
JIBE_PAGE_LIMIT = 100
JIBE_MAX_PAGES = 3
JIBE_RELEVANT_TERM_PATTERN = re.compile(
    r"\b(intern|internship|campus|student|new grad|new graduate|early career|entry level)\b",
    flags=re.IGNORECASE,
)


def _company_host(company: dict[str, Any]) -> str:
    host = str(company.get("host", "")).strip().lower()
    if host:
        return host

    raw_url = str(company.get("url", "")).strip()
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Missing iCIMS host for company config.")
    return host


def _icims_mode(company: dict[str, Any]) -> str:
    mode = str(company.get("mode", "")).strip().lower()
    if mode in {"classic", "jibe"}:
        return mode

    raw_url = str(company.get("url", "")).strip()
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if host.endswith(".icims.com"):
        return "classic"
    if host.endswith(".jibeapply.com") or "icims=1" in parsed.query.lower():
        return "jibe"
    raise ValueError("Missing iCIMS mode for company config.")


def _build_icims_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    headers = {
        "Accept": "application/json,text/html",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
    }
    if raw_url:
        headers["Referer"] = raw_url
    return headers


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_classic_field(row_html: str, field_label: str) -> str:
    pattern = (
        rf"<dt[^>]*>\s*(?:<[^>]+>\s*)*"
        rf"(?:<span[^>]*>\s*)?{re.escape(field_label)}(?:\s*</span>)?"
        rf".*?</dt>\s*<dd[^>]*>(?P<value>.*?)</dd>"
    )
    match = re.search(pattern, row_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _strip_tags(match.group("value"))


def _extract_classic_location(row_html: str) -> str:
    for label in ("Job Location", "Job Locations", "Location", "Locations"):
        value = _extract_classic_field(row_html, label)
        if value:
            return value

    header_match = re.search(
        r'<span[^>]*class="sr-only field-label"[^>]*>\s*Job Locations?\s*</span>\s*'
        r"<span[^>]*>(?P<value>.*?)</span>",
        row_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if header_match:
        return _strip_tags(header_match.group("value"))

    return ""


def _normalize_classic_url(raw_url: str) -> str:
    url = html.unescape(raw_url).strip()
    url = re.sub(r"([?&])in_iframe=1&?", r"\1", url)
    url = re.sub(r"[?&]$", "", url)
    return url


def _parse_classic_jobs_page(
    body: str,
    company: dict[str, Any],
    page: int,
    search_term: str,
) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    jobs: list[dict[str, Any]] = []

    for row_match in re.finditer(
        r'<li[^>]*class="[^"]*iCIMS_JobCardItem[^"]*"[^>]*>(?P<row>.*?)</li>',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        row_html = row_match.group("row")
        link_match = re.search(
            r'<a[^>]+href="(?P<url>[^"]*/jobs/(?P<id>\d+)(?:/[^"]*)?/job[^"]*)"[^>]*>.*?'
            r"<h3[^>]*>(?P<title>.*?)</h3>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not link_match:
            continue

        title = _strip_tags(link_match.group("title"))
        url = _normalize_classic_url(link_match.group("url"))
        job_id = str(link_match.group("id")).strip()
        if not title or not url or not job_id:
            continue

        posted_match = re.search(
            r'<span[^>]+title="(?P<posted>[^"]+)"[^>]*>\s*[^<]*<span[^>]*class="sr-only"',
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        posted_at = html.unescape(posted_match.group("posted")).strip() if posted_match else ""

        jobs.append(
            {
                "id": job_id,
                "title": title,
                "url": url,
                "location": _extract_classic_location(row_html),
                "posted_at": posted_at,
                "_company": company_name,
                "_source": "icims",
                "_source_kind": "classic",
                "_career_url": str(company.get("url", "")).strip(),
                "_search_term": search_term,
                "_page": page,
            }
        )

    return jobs


def _classic_page_has_next(body: str, page: int) -> bool:
    next_page = page + 1
    return re.search(
        rf'href="[^"]*jobs/search\?[^"]*\bpr={next_page}\b',
        body,
        flags=re.IGNORECASE,
    ) is not None


def _fetch_classic_icims_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    host = _company_host(company)
    headers = _build_icims_request_headers(company)
    session = requests.Session()
    session.headers.update(headers)

    jobs_by_id: dict[str, dict[str, Any]] = {}
    total_pages = 0
    search_terms = company.get("search_terms")
    if not isinstance(search_terms, list) or not search_terms:
        search_terms = ICIMS_SEARCH_TERMS

    try:
        for search_term in [str(term).strip() for term in search_terms if str(term).strip()]:
            for page in range(CLASSIC_MAX_PAGES_PER_TERM):
                query = urlencode(
                    {
                        "searchKeyword": search_term,
                        "searchRelation": "keyword_all",
                        "pr": page,
                        "in_iframe": "1",
                    }
                )
                url = f"https://{host}/jobs/search?{query}"
                response = session.get(url, timeout=25)
                response.raise_for_status()
                page_jobs = _parse_classic_jobs_page(
                    response.text,
                    company=company,
                    page=page,
                    search_term=search_term,
                )
                total_pages += 1
                for job in page_jobs:
                    jobs_by_id[str(job["id"])] = job
                if not page_jobs or not _classic_page_has_next(response.text, page):
                    break
    except requests.RequestException as error:
        print(f"[icims] {company_name}: classic request failed ({error})")
        return list(jobs_by_id.values())

    jobs = list(jobs_by_id.values())
    print(
        f"[icims] {company_name}: fetched {len(jobs)} classic postings "
        f"across {total_pages} search pages"
    )
    return jobs


def _jibe_job_location(data: dict[str, Any]) -> str:
    multiple_locations = data.get("multipleLocations")
    if isinstance(multiple_locations, list) and multiple_locations:
        values: list[str] = []
        for item in multiple_locations:
            if not isinstance(item, dict):
                continue
            parts = [
                str(item.get(key, "")).strip()
                for key in ("city", "state", "country")
                if str(item.get(key, "")).strip()
            ]
            if parts:
                values.append(", ".join(parts))
        if values:
            return " / ".join(values)

    for key in ("full_location", "location_name", "short_location"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    parts = [
        str(data.get(key, "")).strip()
        for key in ("city", "state", "country")
        if str(data.get(key, "")).strip()
    ]
    return ", ".join(parts)


def _fetch_jibe_icims_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    host = _company_host(company)
    headers = _build_icims_request_headers(company)
    jobs_by_id: dict[str, dict[str, Any]] = {}
    total_pages = 0

    try:
        facet_response = requests.get(
            f"https://{host}/api/jobs",
            params={"limit": 1},
            headers=headers,
            timeout=25,
        )
        facet_response.raise_for_status()
        facet_body = facet_response.json()
        facet_terms = _extract_jibe_relevant_facet_terms(facet_body)
        if not facet_terms:
            facet_terms = [(tag_key, "Intern") for tag_key in ("tags1", "tags2", "tags3", "tags4")]

        for tag_key, term in facet_terms:
            for page in range(1, JIBE_MAX_PAGES + 1):
                url = f"https://{host}/api/jobs"
                response = requests.get(
                    url,
                    params={tag_key: term, "page": page, "limit": JIBE_PAGE_LIMIT},
                    headers=headers,
                    timeout=25,
                )
                response.raise_for_status()
                body = response.json()
                raw_jobs = body.get("jobs")
                if not isinstance(raw_jobs, list):
                    break
                total_pages += 1
                if not raw_jobs:
                    break

                for item in raw_jobs:
                    if not isinstance(item, dict):
                        continue
                    data = item.get("data")
                    if not isinstance(data, dict):
                        continue
                    job_id = str(data.get("slug") or data.get("req_id") or "").strip()
                    title = str(data.get("title", "")).strip()
                    if not job_id or not title:
                        continue
                    apply_url = f"https://{host}/jobs/{job_id}?lang=en-us&icims=1"
                    jobs_by_id[job_id] = {
                        "id": job_id,
                        "title": title,
                        "url": apply_url,
                        "location": _jibe_job_location(data),
                        "posted_at": data.get("posted_date") or data.get("create_date"),
                        "employment_type": data.get("employment_type"),
                        "_company": company_name,
                        "_source": "icims",
                        "_source_kind": "jibe",
                        "_career_url": str(company.get("url", "")).strip(),
                    }

                total_count = body.get("totalCount") or body.get("count")
                if not isinstance(total_count, int) or page * JIBE_PAGE_LIMIT >= total_count:
                    break
    except requests.RequestException as error:
        print(f"[icims] {company_name}: jibe request failed ({error})")
        return list(jobs_by_id.values())
    except ValueError as error:
        print(f"[icims] {company_name}: jibe invalid JSON response ({error})")
        return list(jobs_by_id.values())

    jobs = list(jobs_by_id.values())
    print(
        f"[icims] {company_name}: fetched {len(jobs)} jibe postings "
        f"across {total_pages} filtered API pages"
    )
    return jobs


def _extract_jibe_relevant_facet_terms(body: dict[str, Any]) -> list[tuple[str, str]]:
    filter_data = body.get("filter")
    if not isinstance(filter_data, dict):
        return []
    facet_list = filter_data.get("facetList")
    if not isinstance(facet_list, dict):
        return []

    terms: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for facet_key, raw_terms in facet_list.items():
        if not isinstance(facet_key, str) or not facet_key.startswith("tags"):
            continue
        if not isinstance(raw_terms, list):
            continue
        for raw_term in raw_terms:
            if not isinstance(raw_term, dict):
                continue
            term = str(raw_term.get("term", "")).strip()
            if not term or not JIBE_RELEVANT_TERM_PATTERN.search(term):
                continue
            key = (facet_key, term)
            if key in seen:
                continue
            seen.add(key)
            terms.append(key)

    return terms


def fetch_icims_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    company_name = str(company.get("company", "Unknown"))
    try:
        mode = _icims_mode(company)
    except Exception as error:
        print(f"[icims] {company_name}: invalid config ({error})")
        return []

    if mode == "jibe":
        return _fetch_jibe_icims_jobs(company)
    return _fetch_classic_icims_jobs(company)
