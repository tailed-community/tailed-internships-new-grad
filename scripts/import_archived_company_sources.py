from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from sync_companies import build_company_config
from sync_companies import load_company_sources
from sync_companies import normalize_url
from sync_companies import save_company_sources


ARCHIVED_JOBS_URL = (
    "https://raw.githubusercontent.com/"
    "tailed-community/tech-internships-2025-2026/refs/heads/main/data/archived.json"
)


def fetch_archived_jobs(url: str = ARCHIVED_JOBS_URL) -> list[dict[str, Any]]:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list from '{url}'.")
    return [item for item in payload if isinstance(item, dict)]


def company_identity(config: dict[str, Any]) -> tuple[str, ...] | None:
    source = str(config.get("source", "")).strip().lower()
    if not source:
        return None

    if source == "workday":
        tenant = str(config.get("tenant", "")).strip().lower()
        site = str(config.get("site", "")).strip().casefold()
        if tenant and site:
            return source, tenant, site
        return None

    if source in {"ashby", "greenhouse", "lever", "rippling", "smartrecruiters", "workable"}:
        slug = str(config.get("slug", "")).strip().casefold()
        if slug:
            return source, slug
        return None

    if source == "icims":
        host = str(config.get("host", "")).strip().lower()
        mode = str(config.get("mode", "")).strip().lower()
        if host and mode:
            return source, mode, host
        return None

    if source == "oracle_hcm":
        host = str(config.get("host", "")).strip().lower()
        language = str(config.get("language", "")).strip().casefold()
        site = str(config.get("site", "")).strip().casefold()
        if host and site:
            return source, host, language, site
        return None

    url = str(config.get("url", "")).strip()
    if url:
        return source, normalize_url(url)

    return None


def identity_label(config: dict[str, Any]) -> str:
    source = str(config.get("source", "")).strip().lower()
    if source == "workday":
        return str(config.get("site", "")).strip()
    if source in {"ashby", "greenhouse", "lever", "rippling", "smartrecruiters", "workable"}:
        return str(config.get("slug", "")).strip()
    if source == "icims":
        return str(config.get("host", "")).strip()
    if source == "oracle_hcm":
        return str(config.get("site", "")).strip()

    parsed = urlsplit(str(config.get("url", "")).strip())
    return parsed.hostname or source


def choose_company_name(counts: Counter[str]) -> str:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return ranked[0][0]


def choose_preferred_url(counts: Counter[str]) -> str:
    ranked = sorted(
        counts.items(),
        key=lambda item: (
            -item[1],
            -len(urlsplit(item[0]).path),
            item[0],
        ),
    )
    return ranked[0][0]


def source_row_identity(row: dict[str, str]) -> tuple[tuple[str, ...] | None, str | None, str | None]:
    company_name = str(row.get("company", "")).strip()
    raw_url = str(row.get("url", "")).strip()
    if not company_name or not raw_url:
        return None, None, None

    normalized_url = normalize_url(raw_url)
    try:
        config = build_company_config(company_name, normalized_url, enabled=True)
    except ValueError:
        return None, normalized_url, None

    if config is None:
        return None, normalized_url, None

    canonical_url = str(config.get("url", "")).strip()
    source = str(config.get("source", "")).strip().lower()
    return company_identity(config), normalize_url(canonical_url), source


def collect_existing_sources(
    rows: list[dict[str, str]],
) -> tuple[set[tuple[str, ...]], set[str], set[tuple[str, str]]]:
    identities: set[tuple[str, ...]] = set()
    urls: set[str] = set()
    company_sources: set[tuple[str, str]] = set()

    for row in rows:
        company_name = str(row.get("company", "")).strip()
        identity, url, source = source_row_identity(row)
        if identity is not None:
            identities.add(identity)
        if url:
            urls.add(url)
        if company_name and source:
            company_sources.add((company_name.casefold(), source))

    return identities, urls, company_sources


def dedupe_company_source_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], Counter[str]]:
    cleaned_rows: list[dict[str, str]] = []
    seen_identities: set[tuple[str, ...]] = set()
    seen_urls: set[str] = set()
    stats: Counter[str] = Counter()

    for row in rows:
        identity, url, _source = source_row_identity(row)
        if identity is not None:
            if identity in seen_identities:
                stats["duplicate_identities"] += 1
                continue
            seen_identities.add(identity)

        if url:
            if url in seen_urls:
                stats["duplicate_urls"] += 1
                continue
            seen_urls.add(url)

        cleaned_rows.append(row)

    return cleaned_rows, stats


def collect_archived_source_candidates(
    archived_jobs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates_by_identity: dict[tuple[str, ...], dict[str, Any]] = {}
    stats: Counter[str] = Counter()

    for item in archived_jobs:
        stats["total_jobs"] += 1
        company_name = str(item.get("company_name", "")).strip()
        raw_url = str(item.get("url", "")).strip()
        if not company_name or not raw_url:
            stats["missing_company_or_url"] += 1
            continue

        normalized_url = normalize_url(raw_url)
        try:
            config = build_company_config(company_name, normalized_url, enabled=True)
        except ValueError:
            stats["invalid_supported_url"] += 1
            continue

        if config is None:
            stats["unsupported_url"] += 1
            continue

        identity = company_identity(config)
        canonical_url = str(config.get("url", "")).strip()
        source = str(config.get("source", "")).strip().lower()
        if identity is None or not canonical_url or not source:
            stats["invalid_supported_url"] += 1
            continue

        stats["supported_jobs"] += 1
        candidate = candidates_by_identity.get(identity)
        if candidate is None:
            candidates_by_identity[identity] = {
                "identity": identity,
                "source": source,
                "config": config,
                "company_counts": Counter([company_name]),
                "url_counts": Counter([normalize_url(canonical_url)]),
            }
            continue

        candidate["company_counts"][company_name] += 1
        candidate["url_counts"][normalize_url(canonical_url)] += 1

    return list(candidates_by_identity.values()), stats


def build_unique_company_name(
    base_name: str,
    source: str,
    config: dict[str, Any],
    used_company_sources: set[tuple[str, str]],
    duplicate_base_count: int,
) -> str:
    base_key = (base_name.casefold(), source)
    if duplicate_base_count == 1 and base_key not in used_company_sources:
        used_company_sources.add(base_key)
        return base_name

    label = identity_label(config) or source
    candidate = f"{base_name} - {label}"
    suffix = 2
    while (candidate.casefold(), source) in used_company_sources:
        candidate = f"{base_name} - {label} {suffix}"
        suffix += 1

    used_company_sources.add((candidate.casefold(), source))
    return candidate


def build_new_source_rows(
    candidates: list[dict[str, Any]],
    existing_identities: set[tuple[str, ...]],
    existing_urls: set[str],
    used_company_sources: set[tuple[str, str]],
) -> tuple[list[dict[str, str]], int]:
    filtered_candidates: list[dict[str, Any]] = []
    skipped_existing_count = 0
    seen_new_identities: set[tuple[str, ...]] = set()
    seen_new_urls: set[str] = set()

    for candidate in candidates:
        identity = candidate["identity"]
        canonical_url = choose_preferred_url(candidate["url_counts"])
        if identity in existing_identities or canonical_url in existing_urls:
            skipped_existing_count += 1
            continue
        if identity in seen_new_identities or canonical_url in seen_new_urls:
            continue

        filtered_candidates.append(candidate)
        seen_new_identities.add(identity)
        seen_new_urls.add(canonical_url)

    base_counts: Counter[tuple[str, str]] = Counter()
    for candidate in filtered_candidates:
        base_name = choose_company_name(candidate["company_counts"])
        source = str(candidate["source"])
        base_counts[(base_name.casefold(), source)] += 1

    rows: list[dict[str, str]] = []
    for candidate in sorted(
        filtered_candidates,
        key=lambda item: (
            choose_company_name(item["company_counts"]).casefold(),
            str(item["source"]),
            choose_preferred_url(item["url_counts"]),
        ),
    ):
        base_name = choose_company_name(candidate["company_counts"])
        source = str(candidate["source"])
        canonical_url = choose_preferred_url(candidate["url_counts"])
        company_name = build_unique_company_name(
            base_name=base_name,
            source=source,
            config=candidate["config"],
            used_company_sources=used_company_sources,
            duplicate_base_count=base_counts[(base_name.casefold(), source)],
        )
        rows.append(
            {
                "company": company_name,
                "url": canonical_url,
                "enabled": "true",
            }
        )

    return rows, skipped_existing_count


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    company_sources_path = repo_root / "data" / "company_sources.csv"

    company_sources = load_company_sources(company_sources_path)
    company_sources, dedupe_stats = dedupe_company_source_rows(company_sources)
    existing_identities, existing_urls, used_company_sources = collect_existing_sources(company_sources)

    archived_jobs = fetch_archived_jobs()
    candidates, stats = collect_archived_source_candidates(archived_jobs)
    new_rows, skipped_existing_count = build_new_source_rows(
        candidates=candidates,
        existing_identities=existing_identities,
        existing_urls=existing_urls,
        used_company_sources=used_company_sources,
    )

    if new_rows or dedupe_stats:
        save_company_sources(company_sources_path, [*company_sources, *new_rows])

    print("Archived company source import summary")
    print(f"- Archived jobs scanned: {stats['total_jobs']}")
    print(f"- Supported ATS jobs scanned: {stats['supported_jobs']}")
    print(f"- Unsupported URLs skipped: {stats['unsupported_url']}")
    print(f"- Invalid rows skipped: {stats['missing_company_or_url'] + stats['invalid_supported_url']}")
    print(f"- Unique supported ATS companies found: {len(candidates)}")
    print(f"- Existing company sources already covered: {skipped_existing_count}")
    print(
        "- Duplicate existing company sources removed: "
        f"{dedupe_stats['duplicate_identities'] + dedupe_stats['duplicate_urls']}"
    )
    print(f"- New company sources appended: {len(new_rows)}")
    print(f"- Output: {company_sources_path}")


if __name__ == "__main__":
    main()
