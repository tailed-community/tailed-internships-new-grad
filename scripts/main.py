from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.archive import merge_active_and_archive
from core.dedupe import dedupe_jobs
from core.markdown import generate_jobs_table, update_markdown_table
from core.normalize import normalize_workday_job
from fetchers.workday import fetch_workday_jobs


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


def main() -> None:
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

    enabled_companies = [company for company in companies if company.get("enabled") is True]
    if not enabled_companies:
        print("No enabled companies found in data/companies.json. Exiting.")
        return

    errors_count = 0
    raw_workday_jobs_count = 0
    normalized_fetched_jobs: list[dict[str, Any]] = []

    for company in enabled_companies:
        company_name = str(company.get("company", "Unknown"))
        source = str(company.get("source", "")).strip().lower()
        if source != "workday":
            print(f"Skipping enabled company {company_name} with unsupported source '{source}'.")
            continue

        print(f"Fetching Workday jobs for {company_name}...")
        try:
            raw_jobs = fetch_workday_jobs(company)
            raw_workday_jobs_count += len(raw_jobs)
            print(f"Fetched {len(raw_jobs)} unique raw jobs for {company_name}.")

            normalized_count = 0
            for raw_job in raw_jobs:
                normalized = normalize_workday_job(raw_job)
                if normalized is None:
                    continue
                normalized_fetched_jobs.append(normalized)
                normalized_count += 1

            print(f"Kept {normalized_count} internship/new grad jobs for {company_name}.")
        except Exception as error:
            errors_count += 1
            print(f"Failed to process company '{company_name}' ({source}): {error}")

    deduped_fetched_jobs = dedupe_jobs(normalized_fetched_jobs)

    active_jobs, archived_jobs = merge_active_and_archive(
        existing_jobs=existing_jobs,
        fetched_jobs=deduped_fetched_jobs,
        existing_archived_jobs=existing_archived_jobs,
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

    internships_count = sum(1 for job in active_jobs if job.get("type") == "internship")
    new_grad_count = sum(1 for job in active_jobs if job.get("type") == "new_grad")

    print("\nUpdate summary")
    print(f"- enabled companies checked: {len(enabled_companies)}")
    print(f"- fetched raw Workday jobs: {raw_workday_jobs_count}")
    print(f"- active jobs saved: {len(active_jobs)}")
    print(f"- internships count: {internships_count}")
    print(f"- new grad count: {new_grad_count}")
    print(f"- archived jobs count: {len(archived_jobs)}")
    print(f"- errors count: {errors_count}")


if __name__ == "__main__":
    main()
