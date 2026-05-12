from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import re


TABLE_HEADER = "| Company | Role | Location | Season | Date Added | Apply |"
TABLE_DIVIDER = "|---|---|---|---|---|---|"


def _parse_date(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return datetime.min


def generate_jobs_table(jobs: list[dict[str, Any]], job_type: str) -> str:
    filtered = [
        job
        for job in jobs
        if isinstance(job, dict)
        and job.get("active") is True
        and str(job.get("type", "")).strip() == job_type
    ]

    filtered.sort(
        key=lambda job: (
            -_parse_date(job.get("date_added")).toordinal(),
            str(job.get("company", "")).lower(),
            str(job.get("title", "")).lower(),
        )
    )

    lines = [TABLE_HEADER, TABLE_DIVIDER]
    if not filtered:
        lines.append("| No jobs found | - | - | - | - | - |")
        return "\n".join(lines)

    for job in filtered:
        company = str(job.get("company", "Unknown")).strip() or "Unknown"
        title = str(job.get("title", "Unknown")).strip() or "Unknown"
        location = str(job.get("location", "Not specified")).strip() or "Not specified"
        season = str(job.get("season", "Not specified")).strip() or "Not specified"
        date_added = str(job.get("date_added", "Unknown")).strip() or "Unknown"
        url = str(job.get("url", "")).strip() or "#"
        lines.append(f"| {company} | {title} | {location} | {season} | {date_added} | [Apply]({url}) |")

    return "\n".join(lines)


def update_markdown_table(file_path: str | Path, start_marker: str, end_marker: str, table: str) -> None:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    pattern = re.compile(
        rf"({re.escape(start_marker)})([\s\S]*?)({re.escape(end_marker)})",
        re.MULTILINE,
    )
    replacement = f"{start_marker}\n{table}\n{end_marker}"
    updated_content, count = pattern.subn(replacement, content, count=1)

    if count == 0:
        raise ValueError(f"Markers not found in {path}")

    path.write_text(updated_content, encoding="utf-8")
