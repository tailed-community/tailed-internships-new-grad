from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse
import re

import requests

from core.classify import classify_job_type


SEARCH_TERM_EQUIVALENT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("intern", "internship"),
    ("co-op", "coop", "co op"),
    ("student", "summer student"),
    ("new grad", "new graduate"),
)


def _extract_workday_site_from_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        return ""

    canonical_segments = path_segments
    for index, segment in enumerate(path_segments):
        if segment.lower() == "job":
            canonical_segments = path_segments[:index]
            break

    if not canonical_segments:
        return ""

    return canonical_segments[-1]


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
        site = _extract_workday_site_from_url(raw_url)

    if not tenant or not site:
        raise ValueError("Could not determine Workday tenant/site from company config.")

    return f"{origin}/wday/cxs/{tenant}/{site}/jobs"


def _build_workday_request_headers(company: dict[str, Any]) -> dict[str, str]:
    raw_url = str(company.get("url", "")).strip()
    parsed = urlparse(raw_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Tail'ed Community Job Fetcher/1.0",
        "Origin": origin,
        "Referer": raw_url,
    }


def _build_workday_session(company: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.headers.update(_build_workday_request_headers(company))
    return session


def _get_workday_pagination_settings(company: dict[str, Any]) -> tuple[int, int]:
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
    return limit, max_pages


def _get_full_listing_limit(company: dict[str, Any]) -> int:
    limit_raw = company.get("full_listing_limit", 20)
    try:
        limit = max(1, int(limit_raw))
    except (TypeError, ValueError):
        limit = 20
    return min(limit, 20)


def _get_full_listing_max_total(company: dict[str, Any]) -> int:
    total_raw = company.get("full_listing_max_total", 400)
    try:
        return max(1, int(total_raw))
    except (TypeError, ValueError):
        return 400


def _get_workday_max_concurrent_searches(company: dict[str, Any]) -> int:
    raw_value = company.get("max_concurrent_searches", 4)
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return 4


def is_vague_location_text(location: str) -> bool:
    text = str(location or "").strip().lower()
    if not text:
        return False
    if text in {"multiple locations", "several locations"}:
        return True
    return bool(re.match(r"^\d+\s+locations?$", text))


def build_workday_detail_url(company: dict[str, Any], external_path: str) -> str:
    raw_url = str(company.get("url", "")).strip()
    if not raw_url:
        raise ValueError("Missing company url for Workday source.")

    parsed = urlparse(raw_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    tenant = str(company.get("tenant", "")).strip() or parsed.netloc.split(".")[0]
    site = str(company.get("site", "")).strip() or _extract_workday_site_from_url(raw_url)
    if not tenant or not site:
        raise ValueError("Could not determine Workday tenant/site from company config.")

    clean_path = str(external_path or "").strip()
    if not clean_path:
        raise ValueError("Missing externalPath for Workday detail fetch.")
    clean_path = clean_path.lstrip("/")

    return f"{origin}/wday/cxs/{tenant}/{site}/{clean_path}"


def fetch_workday_job_detail(
    company: dict[str, Any],
    raw_job: dict[str, Any],
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    external_path = str(raw_job.get("externalPath", "")).strip()
    if not external_path:
        return None

    try:
        detail_url = build_workday_detail_url(company, external_path)
    except Exception as error:
        print(f"[workday] {company.get('company', 'Unknown')} detail URL error: {error}")
        return None

    managed_session: requests.Session | None = None
    if session is None:
        managed_session = _build_workday_session(company)
    client = session or managed_session or requests

    try:
        try:
            response = client.get(detail_url, timeout=20)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as error:
            print(
                f"[workday] {company.get('company', 'Unknown')} detail request failed "
                f"for {external_path}: {error}"
            )
            return None
        except ValueError as error:
            print(
                f"[workday] {company.get('company', 'Unknown')} detail JSON parse failed "
                f"for {external_path}: {error}"
            )
            return None

        if not isinstance(data, dict):
            return None
        return data
    finally:
        if managed_session is not None:
            managed_session.close()


def _extract_text_candidates(value: Any) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            results.append(text)
        return results

    if isinstance(value, list):
        for item in value:
            results.extend(_extract_text_candidates(item))
        return results

    if isinstance(value, dict):
        for key in (
            "displayName",
            "descriptor",
            "location",
            "primaryLocation",
            "primaryLocationDescriptor",
            "locationsText",
        ):
            entry = value.get(key)
            if isinstance(entry, str) and entry.strip():
                results.append(entry.strip())

        city = value.get("city")
        region = value.get("region") or value.get("state") or value.get("province")
        country = value.get("country") or value.get("countryName") or value.get("countryDescriptor")
        if isinstance(city, str) and city.strip():
            combined = city.strip()
            if isinstance(region, str) and region.strip():
                combined = f"{combined}, {region.strip()}"
            if isinstance(country, str) and country.strip():
                combined = f"{combined}, {country.strip()}"
            results.append(combined)

    return results


def extract_workday_detail_locations(detail_data: dict[str, Any]) -> list[str]:
    job_info = detail_data.get("jobPostingInfo")
    candidates: list[str] = []
    fallback_candidates: list[str] = []

    if isinstance(job_info, dict):
        for key in (
            "locations",
            "location",
            "primaryLocation",
            "primaryLocationDescriptor",
            "locationsText",
            "additionalLocations",
        ):
            if key in job_info:
                candidates.extend(_extract_text_candidates(job_info.get(key)))

        if "jobRequisitionLocation" in job_info:
            fallback_candidates.extend(_extract_text_candidates(job_info.get("jobRequisitionLocation")))

    if "hiringOrganization" in detail_data:
        fallback_candidates.extend(_extract_text_candidates(detail_data.get("hiringOrganization")))

    if not candidates:
        candidates = fallback_candidates

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    return deduped


def _fetch_workday_listing(
    company: dict[str, Any],
    search_text: str,
    request_label: str,
    timeout_seconds: int = 25,
    session: requests.Session | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Fetch one Workday listing query with pagination and return raw postings."""
    try:
        jobs_url = build_workday_jobs_url(company)
    except Exception as error:
        print(f"[workday] {company.get('company', 'Unknown')}: invalid config ({error})")
        return False, []

    limit, max_pages = _get_workday_pagination_settings(company)
    managed_session: requests.Session | None = None
    if session is None:
        managed_session = _build_workday_session(company)
    client = session or managed_session or requests

    postings: list[dict[str, Any]] = []
    offset = 0
    pages_fetched = 0

    try:
        while True:
            if pages_fetched >= max_pages:
                print(
                    f"[workday] {company.get('company', 'Unknown')} {request_label}: "
                    f"reached max_pages={max_pages}"
                )
                break

            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": search_text,
            }
            try:
                response = client.post(
                    jobs_url,
                    json=payload,
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
            except requests.RequestException as error:
                print(
                    f"[workday] {company.get('company', 'Unknown')} {request_label} "
                    f"request failed at offset {offset}: {error}"
                )
                return False, []
            except ValueError as error:
                print(
                    f"[workday] {company.get('company', 'Unknown')} {request_label} "
                    f"returned invalid JSON at offset {offset}: {error}"
                )
                return False, []

            page = body.get("jobPostings")
            if page is None:
                print(
                    f"[workday] {company.get('company', 'Unknown')} {request_label} "
                    f"response missing 'jobPostings' at offset {offset}"
                )
                return False, []
            if not isinstance(page, list):
                print(
                    f"[workday] {company.get('company', 'Unknown')} {request_label} "
                    f"'jobPostings' is not a list at offset {offset}"
                )
                return False, []
            if not page:
                break

            for item in page:
                if isinstance(item, dict):
                    postings.append(item)

            print(
                f"[workday] {company.get('company', 'Unknown')} {request_label}: "
                f"+{len(page)} jobs (offset {offset})"
            )

            pages_fetched += 1

            if len(page) < limit:
                break

            offset += limit

        return True, postings
    finally:
        if managed_session is not None:
            managed_session.close()


def _fetch_workday_full_listing(
    company: dict[str, Any],
    timeout_seconds: int = 25,
    session: requests.Session | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    try:
        jobs_url = build_workday_jobs_url(company)
    except Exception as error:
        print(f"[workday] {company.get('company', 'Unknown')}: invalid config ({error})")
        return False, []

    limit = _get_full_listing_limit(company)
    max_total = _get_full_listing_max_total(company)
    managed_session: requests.Session | None = None
    if session is None:
        managed_session = _build_workday_session(company)
    client = session or managed_session or requests

    postings: list[dict[str, Any]] = []
    offset = 0
    expected_total: int | None = None

    try:
        while True:
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }
            try:
                response = client.post(
                    jobs_url,
                    json=payload,
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
            except requests.RequestException as error:
                print(
                    f"[workday] {company.get('company', 'Unknown')} full listing "
                    f"request failed at offset {offset}: {error}"
                )
                return False, []
            except ValueError as error:
                print(
                    f"[workday] {company.get('company', 'Unknown')} full listing "
                    f"returned invalid JSON at offset {offset}: {error}"
                )
                return False, []

            page = body.get("jobPostings")
            if not isinstance(page, list):
                print(
                    f"[workday] {company.get('company', 'Unknown')} full listing "
                    f"response missing valid 'jobPostings' at offset {offset}"
                )
                return False, []

            total_raw = body.get("total")
            if expected_total is None and isinstance(total_raw, int) and total_raw >= 0:
                expected_total = total_raw
                if expected_total > max_total:
                    print(
                        f"[workday] {company.get('company', 'Unknown')} full listing "
                        f"too large for this strategy ({expected_total} jobs > {max_total}); "
                        f"falling back to search terms"
                    )
                    return False, []

            if not page:
                break

            for item in page:
                if isinstance(item, dict):
                    postings.append(item)

            print(
                f"[workday] {company.get('company', 'Unknown')} full listing: "
                f"+{len(page)} jobs (offset {offset})"
            )

            offset += limit

            if expected_total is not None and offset >= expected_total:
                break
            if len(page) < limit:
                break

        return True, postings
    finally:
        if managed_session is not None:
            managed_session.close()


def fetch_workday_search(
    company: dict[str, Any],
    search_term: str,
    timeout_seconds: int = 25,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch one Workday search term with pagination and return raw postings."""
    success, postings = _fetch_workday_listing(
        company=company,
        search_text=search_term,
        request_label=f"search '{search_term}'",
        timeout_seconds=timeout_seconds,
        session=session,
    )
    if not success:
        return []
    return postings


def fetch_workday_full_listing(
    company: dict[str, Any],
    timeout_seconds: int = 25,
    session: requests.Session | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Fetch the full Workday listing using an empty searchText when supported."""
    return _fetch_workday_full_listing(company, timeout_seconds=timeout_seconds, session=session)


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


def _enrich_raw_workday_job(
    raw_job: dict[str, Any],
    company_name: str,
    career_url: Any,
    search_term: str = "",
) -> dict[str, Any]:
    enriched = dict(raw_job)
    enriched["_company"] = company_name
    enriched["_source"] = "workday"
    enriched["_search_term"] = search_term
    enriched["_career_url"] = career_url
    return enriched


def _normalize_search_term(term: str) -> str:
    normalized = str(term).strip().lower()
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _build_equivalent_term_lookup() -> dict[str, frozenset[str]]:
    lookup: dict[str, frozenset[str]] = {}
    for group in SEARCH_TERM_EQUIVALENT_GROUPS:
        normalized_group = frozenset(_normalize_search_term(term) for term in group)
        for term in normalized_group:
            lookup[term] = normalized_group
    return lookup


EQUIVALENT_TERM_LOOKUP = _build_equivalent_term_lookup()


def _build_search_term_plan(search_terms: list[Any]) -> list[dict[str, list[str] | str]]:
    plan: list[dict[str, list[str] | str]] = []
    group_index_by_key: dict[frozenset[str], int] = {}
    seen_ungrouped: set[str] = set()

    for raw_term in search_terms:
        term = str(raw_term).strip()
        if not term:
            continue

        normalized_term = _normalize_search_term(term)
        equivalent_group = EQUIVALENT_TERM_LOOKUP.get(normalized_term)
        if equivalent_group is None:
            if normalized_term in seen_ungrouped:
                continue
            seen_ungrouped.add(normalized_term)
            plan.append({"primary": term, "alternates": []})
            continue

        existing_index = group_index_by_key.get(equivalent_group)
        if existing_index is None:
            group_index_by_key[equivalent_group] = len(plan)
            plan.append({"primary": term, "alternates": []})
            continue

        alternates = plan[existing_index]["alternates"]
        if isinstance(alternates, list) and term not in alternates:
            alternates.append(term)

    return plan


def _dedupe_raw_jobs(raw_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for job in raw_jobs:
        key = _raw_dedupe_key(job)
        if key in seen_keys:
            continue

        seen_keys.add(key)
        deduped.append(job)

    return deduped


def _is_student_or_new_grad_candidate(raw_job: dict[str, Any]) -> bool:
    title = str(raw_job.get("title", "")).strip()
    return classify_job_type(title) in {"internship", "new_grad"}


def _title_matches_search_term(title: str, search_term: str) -> bool:
    normalized_title = _normalize_search_term(title)
    normalized_term = _normalize_search_term(search_term)
    if not normalized_title or not normalized_term:
        return False
    return normalized_term in normalized_title


def _existing_results_cover_term(raw_jobs: list[dict[str, Any]], search_term: str) -> bool:
    return any(
        _title_matches_search_term(str(job.get("title", "")), search_term)
        for job in raw_jobs
        if isinstance(job, dict)
    )


def _should_fetch_detail_locations(raw_job: dict[str, Any]) -> bool:
    locations_text = str(raw_job.get("locationsText", "")).strip()
    has_locations = isinstance(raw_job.get("locations"), list) and len(raw_job.get("locations", [])) > 0
    has_primary = bool(str(raw_job.get("primaryLocation", "")).strip())
    has_primary_descriptor = bool(str(raw_job.get("primaryLocationDescriptor", "")).strip())
    has_external_path = bool(str(raw_job.get("externalPath", "")).strip())

    return (
        is_vague_location_text(locations_text)
        and not has_locations
        and not has_primary
        and not has_primary_descriptor
        and has_external_path
    )


def _fetch_search_term_results(
    company: dict[str, Any],
    search_term: str,
    timeout_seconds: int = 25,
) -> tuple[str, list[dict[str, Any]]]:
    with _build_workday_session(company) as session:
        return search_term, fetch_workday_search(
            company=company,
            search_term=search_term,
            timeout_seconds=timeout_seconds,
            session=session,
        )


def _run_workday_search_batch(
    company: dict[str, Any],
    search_terms: list[str],
    timeout_seconds: int = 25,
) -> dict[str, list[dict[str, Any]]]:
    if not search_terms:
        return {}

    max_workers = min(_get_workday_max_concurrent_searches(company), len(search_terms))
    results_by_term: dict[str, list[dict[str, Any]]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_term = {
            executor.submit(_fetch_search_term_results, company, search_term, timeout_seconds): search_term
            for search_term in search_terms
        }
        for future in as_completed(future_to_term):
            search_term = future_to_term[future]
            try:
                returned_term, results = future.result()
                results_by_term[returned_term] = results
            except Exception as error:
                print(
                    f"[workday] {company.get('company', 'Unknown')} search '{search_term}' "
                    f"worker failed: {error}"
                )
                results_by_term[search_term] = []

    return results_by_term


def fetch_workday_jobs(company: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch, locally filter, and selectively enrich Workday jobs."""
    company_name = str(company.get("company", "Unknown"))
    search_terms = company.get("search_terms")
    if not isinstance(search_terms, list) or not search_terms:
        search_terms = ["intern", "student", "new grad"]

    all_jobs: list[dict[str, Any]] = []
    search_plan = _build_search_term_plan(search_terms)
    use_full_listing = company.get("full_listing") is True

    if use_full_listing:
        print(f"[workday] {company_name}: trying full listing mode")
        with _build_workday_session(company) as session:
            full_listing_success, full_listing_jobs = fetch_workday_full_listing(company, session=session)
        if full_listing_success and full_listing_jobs:
            print(
                f"[workday] {company_name}: full listing mode succeeded "
                f"with {len(full_listing_jobs)} jobs"
            )
            all_jobs.extend(
                _enrich_raw_workday_job(
                    raw_job=job,
                    company_name=company_name,
                    career_url=company.get("url"),
                    search_term="",
                )
                for job in full_listing_jobs
                if isinstance(job, dict)
            )
        else:
            if not full_listing_success:
                reason = "request/response failure"
            else:
                reason = "zero jobs returned"
            print(
                f"[workday] {company_name}: full listing mode unavailable "
                f"({reason}); falling back to search terms"
            )

    if not all_jobs:
        primary_terms = [
            primary
            for primary in (
                str(plan_entry.get("primary", "")).strip()
                for plan_entry in search_plan
                if isinstance(plan_entry, dict)
            )
            if primary
        ]

        primary_results = _run_workday_search_batch(company, primary_terms)
        for search_term in primary_terms:
            results = primary_results.get(search_term, [])
            all_jobs.extend(
                _enrich_raw_workday_job(
                    raw_job=job,
                    company_name=company_name,
                    career_url=company.get("url"),
                    search_term=search_term,
                )
                for job in results
                if isinstance(job, dict)
            )

        alternate_terms_to_run: list[str] = []
        for plan_entry in search_plan:
            alternates = plan_entry.get("alternates", []) if isinstance(plan_entry, dict) else []
            if not isinstance(alternates, list):
                continue
            for alternate_term in alternates:
                if not _existing_results_cover_term(all_jobs, alternate_term):
                    alternate_terms_to_run.append(alternate_term)

        alternate_terms_to_run = [term for term in alternate_terms_to_run if str(term).strip()]
        if alternate_terms_to_run:
            alternate_results = _run_workday_search_batch(company, alternate_terms_to_run)
            for search_term in alternate_terms_to_run:
                results = alternate_results.get(search_term, [])
                all_jobs.extend(
                    _enrich_raw_workday_job(
                        raw_job=job,
                        company_name=company_name,
                        career_url=company.get("url"),
                        search_term=search_term,
                    )
                    for job in results
                    if isinstance(job, dict)
                )

    deduped = _dedupe_raw_jobs(all_jobs)
    kept_jobs = [job for job in deduped if _is_student_or_new_grad_candidate(job)]

    max_detail_fetches_raw = company.get("max_detail_fetches", 50)
    try:
        max_detail_fetches = max(0, int(max_detail_fetches_raw))
    except (TypeError, ValueError):
        max_detail_fetches = 50

    detail_fetch_attempts = 0
    with _build_workday_session(company) as detail_session:
        for job in kept_jobs:
            if not _should_fetch_detail_locations(job):
                continue
            if detail_fetch_attempts >= max_detail_fetches:
                break

            detail_fetch_attempts += 1
            title = str(job.get("title", "(no title)")).strip() or "(no title)"
            locations_text = str(job.get("locationsText", "")).strip()
            print(f"Fetching detail locations for {company_name}: {title}")

            detail_data = fetch_workday_job_detail(company, job, session=detail_session)
            if not detail_data:
                print(
                    f"Could not recover detail locations; using fallback "
                    f"'{locations_text or 'Not specified'}'."
                )
                continue

            detail_locations = extract_workday_detail_locations(detail_data)
            job["_detail"] = detail_data
            if detail_locations:
                job["_detail_locations"] = detail_locations
                print(f"Recovered {len(detail_locations)} detail locations.")
            else:
                print(
                    f"Could not recover detail locations; using fallback "
                    f"'{locations_text or 'Not specified'}'."
                )

    return kept_jobs
