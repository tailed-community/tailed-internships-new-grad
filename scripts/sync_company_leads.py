from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from sync_companies import build_company_config, load_company_sources, normalize_url


SIMPLIFY_LISTINGS_URL = (
    "https://raw.githubusercontent.com/"
    "SimplifyJobs/Summer2026-Internships/refs/heads/dev/.github/scripts/listings.json"
)


def fetch_json_list(url: str) -> list[dict[str, Any]]:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list from '{url}'.")
    return [item for item in payload if isinstance(item, dict)]


def canonicalize_existing_source_urls(rows: list[dict[str, str]]) -> set[str]:
    existing_urls: set[str] = set()
    for row in rows:
        company_name = str(row.get("company", "")).strip()
        raw_url = str(row.get("url", "")).strip()
        if not company_name or not raw_url:
            continue

        normalized_url = normalize_url(raw_url)
        try:
            config = build_company_config(company_name, normalized_url, enabled=False)
        except ValueError:
            config = None

        if config is None:
            existing_urls.add(normalized_url)
            continue

        canonical_url = str(config.get("url", "")).strip()
        if canonical_url:
            existing_urls.add(canonical_url)

    return existing_urls


def company_identity(config: dict[str, Any]) -> tuple[str, ...] | None:
    source = str(config.get("source", "")).strip().lower()
    if not source:
        return None

    if source == "workday":
        tenant = str(config.get("tenant", "")).strip().lower()
        site = str(config.get("site", "")).strip()
        if tenant and site:
            return source, tenant, site.casefold()
        return None

    if source in {
        "ashby",
        "greenhouse",
        "lever",
        "rippling",
        "smartrecruiters",
        "workable",
    }:
        slug = str(config.get("slug", "")).strip().lower()
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
        language = str(config.get("language", "")).strip().lower()
        site = str(config.get("site", "")).strip().lower()
        if host and language and site:
            return source, host, language, site
        return None

    url = str(config.get("url", "")).strip()
    if url:
        return source, url

    return None


def canonicalize_existing_source_identities(rows: list[dict[str, str]]) -> set[tuple[str, ...]]:
    identities: set[tuple[str, ...]] = set()
    for row in rows:
        company_name = str(row.get("company", "")).strip()
        raw_url = str(row.get("url", "")).strip()
        if not company_name or not raw_url:
            continue

        normalized_url = normalize_url(raw_url)
        try:
            config = build_company_config(company_name, normalized_url, enabled=False)
        except ValueError:
            continue

        if config is None:
            continue

        identity = company_identity(config)
        if identity is not None:
            identities.add(identity)

    return identities


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


def collect_supported_leads(listings: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, int]]:
    leads_by_identity: dict[tuple[str, ...], dict[str, Any]] = {}
    stats = {
        "total_listings": 0,
        "supported_listings": 0,
        "unsupported_listings": 0,
        "invalid_listings": 0,
    }

    for item in listings:
        stats["total_listings"] += 1

        company_name = str(item.get("company_name", "")).strip()
        raw_url = str(item.get("url", "")).strip()
        if not company_name or not raw_url:
            stats["invalid_listings"] += 1
            continue

        normalized_url = normalize_url(raw_url)
        try:
            config = build_company_config(company_name, normalized_url, enabled=False)
        except ValueError:
            stats["invalid_listings"] += 1
            continue

        if config is None:
            stats["unsupported_listings"] += 1
            continue

        canonical_url = str(config.get("url", "")).strip()
        source = str(config.get("source", "")).strip()
        if not canonical_url or not source:
            stats["invalid_listings"] += 1
            continue

        identity = company_identity(config)
        if identity is None:
            stats["invalid_listings"] += 1
            continue

        stats["supported_listings"] += 1

        existing = leads_by_identity.get(identity)
        if existing is None:
            leads_by_identity[identity] = {
                "source": source,
                "identity": identity,
                "company_counts": Counter([company_name]),
                "url_counts": Counter([canonical_url]),
                "job_count": 1,
                "example_job_url": raw_url,
            }
            continue

        existing["company_counts"][company_name] += 1
        existing["url_counts"][canonical_url] += 1
        existing["job_count"] += 1

    rows: list[dict[str, str]] = []
    for lead in sorted(
        leads_by_identity.values(),
        key=lambda item: (
            choose_company_name(item["company_counts"]).casefold(),
            str(item["source"]).casefold(),
            choose_preferred_url(item["url_counts"]),
        ),
    ):
        rows.append(
            {
                "company": choose_company_name(lead["company_counts"]),
                "url": choose_preferred_url(lead["url_counts"]),
                "source": str(lead["source"]),
                "job_count": str(int(lead["job_count"])),
                "example_job_url": str(lead["example_job_url"]),
                "lead_source": "Simplify",
                "identity": " :: ".join(lead["identity"]),
            }
        )

    return rows, stats


def save_leads(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "company",
        "url",
        "source",
        "job_count",
        "example_job_url",
        "lead_source",
        "identity",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "")).strip() for field in fieldnames})


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    company_sources_path = repo_root / "data" / "company_sources.csv"
    output_path = repo_root / "data" / "company_leads.csv"

    company_sources = load_company_sources(company_sources_path)
    existing_urls = canonicalize_existing_source_urls(company_sources)
    existing_identities = canonicalize_existing_source_identities(company_sources)

    listings = fetch_json_list(SIMPLIFY_LISTINGS_URL)
    all_leads, stats = collect_supported_leads(listings)

    new_leads = [
        row
        for row in all_leads
        if row["identity"] and tuple(row["identity"].split(" :: ")) not in existing_identities
        and row["url"] not in existing_urls
    ]
    save_leads(output_path, new_leads)

    print("Company lead sync summary")
    print(f"- Listings scanned: {stats['total_listings']}")
    print(f"- Supported ATS listings: {stats['supported_listings']}")
    print(f"- Unsupported ATS listings: {stats['unsupported_listings']}")
    print(f"- Invalid listings skipped: {stats['invalid_listings']}")
    print(f"- Unique supported ATS companies found: {len(all_leads)}")
    print(f"- Existing company sources already covered: {len(all_leads) - len(new_leads)}")
    print(f"- New leads written: {len(new_leads)}")
    print(f"- Output: {output_path}")


if __name__ == "__main__":
    main()
