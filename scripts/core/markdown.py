from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import re

from core.normalize import format_location_text

TABLE_HEADER = "| Company | Role | City | Apply | Date Added |"
TABLE_DIVIDER = "|---|---|---|---|---|"


def _parse_date(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return datetime.min


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|").strip()


def _format_date_added(value: Any) -> str:
    date_added = _parse_date(value)
    if date_added == datetime.min:
        return "Not specified"
    return date_added.strftime("%Y-%m-%d")


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
        lines.append("| No jobs found | - | - | - | - |")
        return "\n".join(lines)

    for job in filtered:
        company = _escape_cell(str(job.get("company", "Unknown")).strip() or "Unknown")
        title = _escape_cell(str(job.get("title", "Unknown")).strip() or "Unknown")
        location = _escape_cell(format_location_text(str(job.get("location", "")).strip()))
        url = str(job.get("url", "")).strip() or "#"
        date_added = _format_date_added(job.get("date_added"))
        lines.append(f"| {company} | {title} | {location} | [Apply]({url}) | {date_added} |")

    return "\n".join(lines)


def update_markdown_table(file_path: str | Path, start_marker: str, end_marker: str, table: str) -> None:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    pattern = re.compile(
        rf"({re.escape(start_marker)})([\s\S]*?)({re.escape(end_marker)})",
        re.MULTILINE,
    )
    newline = "\r\n" if "\r\n" in content else "\n"
    normalized_table = table.replace("\n", newline)
    replacement = f"{start_marker}{newline}{normalized_table}{newline}{end_marker}"
    updated_content, count = pattern.subn(lambda _: replacement, content, count=1)

    if count == 0:
        raise ValueError(f"Markers not found in {path}")

    path.write_text(updated_content, encoding="utf-8", newline="")
