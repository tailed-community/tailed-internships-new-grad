from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.markdown import generate_jobs_table, update_markdown_table


def load_jobs(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Failed to load jobs from {path}: {error}") from error

    if not isinstance(data, list):
        raise RuntimeError(f"Invalid jobs file format at {path}: expected a list.")

    return [item for item in data if isinstance(item, dict)]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    jobs_path = repo_root / "data" / "jobs.json"
    readme_path = repo_root / "README.md"
    new_grad_path = repo_root / "NEW_GRAD.md"

    jobs = load_jobs(jobs_path)

    internships_table = generate_jobs_table(jobs, "internship")
    new_grad_table = generate_jobs_table(jobs, "new_grad")

    update_markdown_table(
        file_path=readme_path,
        start_marker="<!-- INTERNSHIPS_TABLE_START -->",
        end_marker="<!-- INTERNSHIPS_TABLE_END -->",
        table=internships_table,
    )
    update_markdown_table(
        file_path=new_grad_path,
        start_marker="<!-- NEW_GRAD_TABLE_START -->",
        end_marker="<!-- NEW_GRAD_TABLE_END -->",
        table=new_grad_table,
    )

    internships_count = sum(1 for job in jobs if job.get("active") is True and job.get("type") == "internship")
    new_grad_count = sum(1 for job in jobs if job.get("active") is True and job.get("type") == "new_grad")

    print("Formatted markdown tables from existing data/jobs.json")
    print(f"- internships rendered: {internships_count}")
    print(f"- new grad rendered: {new_grad_count}")


if __name__ == "__main__":
    main()
