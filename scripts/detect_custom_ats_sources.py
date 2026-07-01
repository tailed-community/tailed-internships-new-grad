from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from custom_career_ats import (
    FetchResult,
    build_ats_source_candidates,
    detect_ats,
    detect_ats_from_html,
    discover_pages,
    fetch_page,
    normalize_page_url,
)


OUTPUT_COLUMNS = [
    "company",
    "original_url",
    "detected_source",
    "source_key",
    "canonical_source_url",
    "evidence_count",
    "best_evidence_url",
    "confidence",
    "route_ready",
    "route_block_reason",
    "recommended_action",
    "discovered_from",
    "notes",
]
TRUE_VALUES = {"1", "true", "yes"}


def load_company_inputs(paths: Iterable[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            for raw in csv.DictReader(file):
                company = (raw.get("company") or "").strip()
                url = (raw.get("career_url") or raw.get("url") or "").strip()
                enabled = (raw.get("enabled") or "true").strip().casefold()
                if not company or not url or enabled not in TRUE_VALUES:
                    continue
                key = (company.casefold(), normalize_page_url(url))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "company": company,
                        "url": url,
                        "discovered_from": (
                            raw.get("discovered_from")
                            or ("manual_custom_companies" if path.name == "custom_companies.csv" else "")
                        ).strip(),
                    }
                )
    return rows


def recommended_action(source: str, route_ready: bool) -> str:
    if source == "phenom":
        return "future_phenom_adapter"
    if source == "breezyhr":
        return "custom_ats_adapter_needed" if route_ready else "manual_review"
    if source in {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "workday",
        "icims",
        "jobvite",
        "bamboohr",
        "workable",
        "recruitee",
        "comeet",
        "oracle_hcm",
        "rippling",
    }:
        return "validate_with_existing_ats_scraper" if route_ready else "add_to_existing_ats_csv_later"
    return "unsupported_for_now"


def normalize_candidate(
    candidate: dict[str, object],
    discovered_from: str,
) -> dict[str, object]:
    source = str(candidate.get("detected_source", ""))
    best_url = str(candidate.get("best_evidence_url", ""))
    canonical = str(candidate.get("canonical_ats_url", ""))
    route_ready = bool(candidate.get("route_ready"))
    block_reason = str(candidate.get("route_block_reason", ""))

    if source == "breezyhr":
        if best_url.casefold().endswith("/json"):
            canonical = best_url
            route_ready = best_url.casefold().startswith("https://")
            block_reason = "" if route_ready else "BreezyHR JSON endpoint is not HTTPS"
        else:
            source_key = str(candidate.get("source_key", ""))
            canonical = f"https://{source_key}.breezy.hr/json" if source_key else best_url
            route_ready = False
            block_reason = "A public BreezyHR /json endpoint was not directly observed"
    elif source == "phenom":
        lowered = best_url.casefold()
        clear_job_api = (
            best_url.startswith("https://")
            and "/api/" in lowered
            and any(marker in lowered for marker in ("jobsearch", "search-jobs", "/jobs"))
        )
        route_ready = clear_job_api
        block_reason = (
            ""
            if clear_job_api
            else "No clear public Phenom job-search API endpoint was identified"
        )

    return {
        "company": candidate.get("company", ""),
        "original_url": candidate.get("original_url", ""),
        "detected_source": source,
        "source_key": candidate.get("source_key", ""),
        "canonical_source_url": canonical,
        "evidence_count": candidate.get("evidence_count", 0),
        "best_evidence_url": best_url,
        "confidence": candidate.get("confidence", ""),
        "route_ready": route_ready,
        "route_block_reason": block_reason,
        "recommended_action": recommended_action(source, route_ready),
        "discovered_from": discovered_from,
        "notes": candidate.get("notes", ""),
    }


def candidates_from_html(
    company: str,
    original_url: str,
    html_pages: Iterable[tuple[str, str]],
    discovered_from: str = "",
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for source_page, html in html_pages:
        evidence.extend(detect_ats_from_html(company, source_page, html))
    candidates = build_ats_source_candidates(company, original_url, evidence)
    return [normalize_candidate(candidate, discovered_from) for candidate in candidates]


def _url_evidence(company: str, source_page: str, url: str, method: str) -> list[dict[str, object]]:
    source = detect_ats(url)
    if not source and "gh_jid=" not in url.casefold():
        return []
    escaped = url.replace("&", "&amp;").replace('"', "&quot;")
    rows = detect_ats_from_html(
        company,
        source_page,
        f'<a href="{escaped}">ATS evidence</a>',
    )
    for row in rows:
        row["detection_method"] = method
    return rows


def detect_company(
    company: dict[str, str],
    *,
    fetcher: Callable[[str], FetchResult] = fetch_page,
    max_pages: int = 4,
) -> list[dict[str, object]]:
    original_url = normalize_page_url(company["url"])
    first = fetcher(original_url)
    html_pages = [(first.final_url, first.html)]
    evidence = _url_evidence(
        company["company"],
        original_url,
        first.final_url,
        "final_url",
    )
    discovered, ats_links = discover_pages(
        first.final_url,
        first.html,
        max_pages=max_pages,
    )
    for ats_link in ats_links:
        _source, _separator, url = ats_link.partition(":")
        if url:
            evidence.extend(
                _url_evidence(
                    company["company"],
                    first.final_url,
                    url,
                    "discovered_external_link",
                )
            )
    fetched = {normalize_page_url(first.final_url)}
    for page in discovered[: max(0, max_pages - 1)]:
        url = normalize_page_url(page.fetch_url)
        if url in fetched:
            continue
        fetched.add(url)
        result = fetcher(url)
        html_pages.append((result.final_url, result.html))
        evidence.extend(
            _url_evidence(
                company["company"],
                page.original_url,
                result.final_url,
                "final_url",
            )
        )
        _nested_pages, nested_ats_links = discover_pages(
            result.final_url,
            result.html,
            max_pages=1,
        )
        for ats_link in nested_ats_links:
            _source, _separator, ats_url = ats_link.partition(":")
            if ats_url:
                evidence.extend(
                    _url_evidence(
                        company["company"],
                        result.final_url,
                        ats_url,
                        "discovered_external_link",
                    )
                )
    for source_page, html in html_pages:
        evidence.extend(
            detect_ats_from_html(company["company"], source_page, html)
        )
    candidates = build_ats_source_candidates(
        company["company"],
        original_url,
        evidence,
    )
    return [
        normalize_candidate(candidate, company.get("discovered_from", ""))
        for candidate in candidates
    ]


def detect_all(
    companies: Iterable[dict[str, str]],
    *,
    fetcher: Callable[[str], FetchResult] = fetch_page,
    max_pages: int = 2,
    workers: int = 8,
    progress_callback: Callable[[int, int, list[dict[str, object]]], None] | None = None,
) -> list[dict[str, object]]:
    company_rows = list(companies)
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()

    def run_one(company: dict[str, str]) -> list[dict[str, object]]:
        try:
            return detect_company(company, fetcher=fetcher, max_pages=max_pages)
        except Exception as error:
            return [
                {
                    "company": company["company"],
                    "original_url": company["url"],
                    "detected_source": "",
                    "source_key": "",
                    "canonical_source_url": "",
                    "evidence_count": 0,
                    "best_evidence_url": "",
                    "confidence": "",
                    "route_ready": False,
                    "route_block_reason": f"{type(error).__name__}: {error}",
                    "recommended_action": "manual_review",
                    "discovered_from": company.get("discovered_from", ""),
                    "notes": "Career page fetch or passive detection failed",
                }
            ]

    def add_detected(detected: list[dict[str, object]]) -> None:
        for row in detected:
            key = (
                str(row.get("company", "")).casefold(),
                str(row.get("detected_source", "")),
                str(row.get("source_key", "")),
            )
            if key not in seen:
                seen.add(key)
                rows.append(row)

    total = len(company_rows)
    if workers <= 1:
        for completed, company in enumerate(company_rows, start=1):
            add_detected(run_one(company))
            if progress_callback:
                progress_callback(completed, total, rows)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(run_one, company): company
                for company in company_rows
            }
            for completed, future in enumerate(as_completed(futures), start=1):
                add_detected(future.result())
                if progress_callback:
                    progress_callback(completed, total, rows)

    return sorted(
        rows,
        key=lambda row: (
            str(row.get("company", "")).casefold(),
            str(row.get("detected_source", "")),
            str(row.get("source_key", "")),
            str(row.get("original_url", "")),
        ),
    )


def write_candidates(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in OUTPUT_COLUMNS} for row in rows)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run passive ATS/API detection on custom career pages.")
    parser.add_argument(
        "--input",
        type=Path,
        default=repo_root / "data" / "custom_companies_discovered.csv",
    )
    parser.add_argument(
        "--include-manual",
        action="store_true",
        help="Also include data/custom_companies.csv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "data" / "custom_ats_candidates.csv",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Maximum pages fetched per company, including the initial page.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent companies to process.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N inputs; 0 means all.",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Rewrite partial output after this many completed companies; 0 disables checkpoints.",
    )
    args = parser.parse_args()

    inputs = [args.input]
    if args.include_manual:
        inputs.append(repo_root / "data" / "custom_companies.csv")
    companies = load_company_inputs(inputs)
    if args.limit > 0:
        companies = companies[: args.limit]

    checkpoint_every = max(0, args.checkpoint_every)

    def report_progress(
        completed: int,
        total: int,
        partial_rows: list[dict[str, object]],
    ) -> None:
        if completed == total or completed == 1 or completed % 25 == 0:
            print(
                f"Processed {completed}/{total} companies; "
                f"{len(partial_rows)} candidate rows",
                flush=True,
            )
        if checkpoint_every and (
            completed == total or completed % checkpoint_every == 0
        ):
            write_candidates(args.output, partial_rows)

    rows = detect_all(
        companies,
        max_pages=max(1, min(args.max_pages, 8)),
        workers=max(1, min(args.workers, 32)),
        progress_callback=report_progress,
    )
    write_candidates(args.output, rows)
    print(f"Wrote {len(rows)} passive ATS candidates to {args.output}")


if __name__ == "__main__":
    main()
