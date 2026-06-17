from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.archive import merge_active_and_archive
from core.dedupe import dedupe_jobs
from core.markdown import generate_jobs_table, update_markdown_table
from core.normalize import (
    normalize_ashby_job,
    normalize_greenhouse_job,
    normalize_icims_job,
    normalize_lever_job,
    normalize_oracle_hcm_job,
    normalize_rippling_job,
    normalize_smartrecruiters_job,
    normalize_workable_job,
    normalize_workday_job,
)
from fetchers.ashby import fetch_ashby_jobs
from fetchers.greenhouse import fetch_greenhouse_jobs
from fetchers.icims import fetch_icims_jobs
from fetchers.lever import fetch_lever_jobs
from fetchers.oracle_hcm import fetch_oracle_hcm_jobs
from fetchers.rippling import fetch_rippling_jobs
from fetchers.smartrecruiters import fetch_smartrecruiters_jobs
from fetchers.workable import fetch_workable_jobs
from fetchers.workday import fetch_workday_jobs


FetchJobs = Callable[[dict[str, Any]], list[dict[str, Any]]]
NormalizeJob = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class SourceHandler:
    fetch_jobs: FetchJobs
    normalize_job: NormalizeJob


@dataclass(frozen=True)
class CompanyResult:
    company: str
    source: str
    raw_jobs_count: int = 0
    normalized_jobs: tuple[dict[str, Any], ...] = ()
    touched: bool = False
    error: bool = False


SOURCE_HANDLERS = {
    "ashby": SourceHandler(fetch_ashby_jobs, normalize_ashby_job),
    "greenhouse": SourceHandler(fetch_greenhouse_jobs, normalize_greenhouse_job),
    "icims": SourceHandler(fetch_icims_jobs, normalize_icims_job),
    "lever": SourceHandler(fetch_lever_jobs, normalize_lever_job),
    "oracle_hcm": SourceHandler(fetch_oracle_hcm_jobs, normalize_oracle_hcm_job),
    "rippling": SourceHandler(fetch_rippling_jobs, normalize_rippling_job),
    "smartrecruiters": SourceHandler(fetch_smartrecruiters_jobs, normalize_smartrecruiters_job),
    "workable": SourceHandler(fetch_workable_jobs, normalize_workable_job),
    "workday": SourceHandler(fetch_workday_jobs, normalize_workday_job),
}


def load_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Failed to load JSON list '{path}': {error}")
        return []

    if not isinstance(data, list):
        print(f"Invalid JSON list format in '{path}': expected a list.")
        return []

    return [item for item in data if isinstance(item, dict)]


def save_json_list(path: Path, data: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def _parse_source_filter(raw_sources: list[str] | None) -> set[str] | None:
    if not raw_sources:
        return None

    parsed_sources: set[str] = set()
    for raw_source in raw_sources:
        for part in str(raw_source).split(","):
            source = part.strip().lower()
            if source:
                parsed_sources.add(source)

    return parsed_sources or None


def _company_name(company: dict[str, Any]) -> str:
    return str(company.get("company", "Unknown")).strip() or "Unknown"


def _company_source(company: dict[str, Any]) -> str:
    return str(company.get("source", "")).strip().lower()


def _normalize_jobs(raw_jobs: list[dict[str, Any]], handler: SourceHandler) -> tuple[dict[str, Any], ...]:
    normalized_jobs: list[dict[str, Any]] = []
    for raw_job in raw_jobs:
        normalized = handler.normalize_job(raw_job)
        if normalized is not None:
            normalized_jobs.append(normalized)
    return tuple(normalized_jobs)


def _filter_enabled_companies(
    companies: list[dict[str, Any]],
    selected_sources: set[str] | None,
) -> list[dict[str, Any]]:
    enabled = [company for company in companies if company.get("enabled") is True]
    if selected_sources is None:
        return enabled

    return [
        company
        for company in enabled
        if _company_source(company) in selected_sources
    ]


def _apply_workday_search_workers(
    companies: list[dict[str, Any]],
    workday_search_workers: int | None,
) -> list[dict[str, Any]]:
    if workday_search_workers is None:
        return companies

    configured_companies: list[dict[str, Any]] = []
    for company in companies:
        if _company_source(company) != "workday":
            configured_companies.append(company)
            continue

        configured = dict(company)
        configured["max_concurrent_searches"] = workday_search_workers
        configured_companies.append(configured)

    return configured_companies


def process_company(company: dict[str, Any]) -> CompanyResult:
    company_name = _company_name(company)
    source = _company_source(company)
    handler = SOURCE_HANDLERS.get(source)
    if handler is None:
        print(f"Skipping enabled company {company_name} with unsupported source '{source}'.")
        return CompanyResult(company=company_name, source=source)

    print(f"Fetching {source} jobs for {company_name}...")
    try:
        raw_jobs = handler.fetch_jobs(company)
        print(f"Fetched {len(raw_jobs)} unique raw jobs for {company_name}.")

        normalized_jobs = _normalize_jobs(raw_jobs, handler)
        print(f"Kept {len(normalized_jobs)} internship/new grad jobs for {company_name}.")
        return CompanyResult(
            company=company_name,
            source=source,
            raw_jobs_count=len(raw_jobs),
            normalized_jobs=normalized_jobs,
            touched=True,
        )
    except Exception as error:
        print(f"Failed to process company '{company_name}' ({source}): {error}")
        return CompanyResult(company=company_name, source=source, error=True)


def process_companies(
    companies: list[dict[str, Any]],
    workers: int,
) -> list[CompanyResult]:
    if workers <= 1 or len(companies) <= 1:
        return [process_company(company) for company in companies]

    max_workers = min(workers, len(companies))
    print(f"Fetching companies with {max_workers} workers...")
    results: list[CompanyResult | None] = [None] * len(companies)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(process_company, company): index
            for index, company in enumerate(companies)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            company = companies[index]
            company_name = _company_name(company)
            source = _company_source(company)
            try:
                results[index] = future.result()
            except Exception as error:
                print(f"Failed to process company '{company_name}' ({source}): {error}")
                results[index] = CompanyResult(company=company_name, source=source, error=True)

    return [result for result in results if result is not None]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch and merge job listings by source.")
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help="Limit the run to one or more sources. Repeat the flag or use a comma-separated list.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of companies to fetch in parallel. Defaults to 1.",
    )
    parser.add_argument(
        "--workday-search-workers",
        type=int,
        default=None,
        help="Override parallel Workday search-term workers per company.",
    )
    args = parser.parse_args(argv)
    selected_sources = _parse_source_filter(args.sources)
    workers = max(1, args.workers)
    workday_search_workers = (
        max(1, args.workday_search_workers)
        if args.workday_search_workers is not None
        else None
    )

    repo_root = Path(__file__).resolve().parents[1]
    companies_path = repo_root / "data" / "companies.json"
    jobs_path = repo_root / "data" / "jobs.json"
    archived_path = repo_root / "data" / "archived.json"
    readme_path = repo_root / "README.md"
    new_grad_path = repo_root / "NEW_GRAD.md"

    companies = load_json_list(companies_path)
    existing_jobs = load_json_list(jobs_path)
    existing_archived_jobs = load_json_list(archived_path)
    if not companies:
        print("No companies configured. Exiting.")
        return

    enabled_companies = _filter_enabled_companies(companies, selected_sources)
    if not enabled_companies:
        if selected_sources is None:
            print("No enabled companies found in data/companies.json. Exiting.")
        else:
            requested = ", ".join(sorted(selected_sources))
            print(f"No enabled companies found for source filter: {requested}. Exiting.")
        return
    enabled_companies = _apply_workday_search_workers(enabled_companies, workday_search_workers)

    errors_count = 0
    raw_jobs_count = 0
    normalized_fetched_jobs: list[dict[str, Any]] = []
    touched_targets: set[tuple[str, str]] = set()

    for result in process_companies(enabled_companies, workers):
        if result.error:
            errors_count += 1
        if result.touched:
            touched_targets.add((result.source, result.company))
        raw_jobs_count += result.raw_jobs_count
        normalized_fetched_jobs.extend(result.normalized_jobs)

    deduped_fetched_jobs = dedupe_jobs(normalized_fetched_jobs)

    active_jobs, archived_jobs = merge_active_and_archive(
        existing_jobs=existing_jobs,
        fetched_jobs=deduped_fetched_jobs,
        existing_archived_jobs=existing_archived_jobs,
        touched_targets=touched_targets,
    )
    active_jobs = dedupe_jobs(active_jobs)

    save_json_list(jobs_path, active_jobs)
    save_json_list(archived_path, archived_jobs)

    internships_table = generate_jobs_table(active_jobs, "internship")
    new_grad_table = generate_jobs_table(active_jobs, "new_grad")

    try:
        update_markdown_table(
            file_path=readme_path,
            start_marker="<!-- INTERNSHIPS_TABLE_START -->",
            end_marker="<!-- INTERNSHIPS_TABLE_END -->",
            table=internships_table,
        )
    except Exception as error:
        errors_count += 1
        print(f"Failed to update README.md table: {error}")
        raise

    try:
        update_markdown_table(
            file_path=new_grad_path,
            start_marker="<!-- NEW_GRAD_TABLE_START -->",
            end_marker="<!-- NEW_GRAD_TABLE_END -->",
            table=new_grad_table,
        )
    except Exception as error:
        errors_count += 1
        print(f"Failed to update NEW_GRAD.md table: {error}")
        raise

    internships_count = sum(1 for job in active_jobs if job.get("type") == "internship")
    new_grad_count = sum(1 for job in active_jobs if job.get("type") == "new_grad")

    print("\nUpdate summary")
    if selected_sources is not None:
        print(f"- requested sources: {', '.join(sorted(selected_sources))}")
    print(f"- enabled companies checked: {len(enabled_companies)}")
    print(f"- fetched raw jobs: {raw_jobs_count}")
    print(f"- active jobs saved: {len(active_jobs)}")
    print(f"- internships count: {internships_count}")
    print(f"- new grad count: {new_grad_count}")
    print(f"- archived jobs count: {len(archived_jobs)}")
    print(f"- errors count: {errors_count}")


if __name__ == "__main__":
    main()
