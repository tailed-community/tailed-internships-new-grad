from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from core.classify import classify_job_type

UPPERCASE_LOCATION_TOKENS = {
    "ON",
    "QC",
    "BC",
    "AB",
    "MB",
    "SK",
    "NS",
    "NB",
    "NL",
    "PE",
    "NT",
    "NU",
    "YT",
    "CA",
    "US",
    "USA",
    "UK",
}

SEASON_NAMES = ("Summer", "Fall", "Winter", "Spring")


def _slug(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-") or "unknown"


def _format_word(word: str) -> str:
    token = word.strip()
    if not token:
        return ""

    upper = token.upper()
    if upper in UPPERCASE_LOCATION_TOKENS:
        return upper

    if "-" in token:
        return "-".join(_format_word(part) for part in token.split("-") if part)

    return token[0].upper() + token[1:].lower()


def format_location(location: str) -> str:
    text = re.sub(r"\s+", " ", str(location or "").strip())
    if not text:
        return "Not specified"

    lowered = text.lower()
    if lowered == "canada remote":
        return "Canada Remote"
    if lowered == "multiple locations":
        return "Multiple Locations"

    number_match = re.match(r"^(\d+)\s+locations?$", lowered)
    if number_match:
        return f"{number_match.group(1)} Locations"

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return "Not specified"

    formatted_parts: list[str] = []
    for part in parts:
        words = [word for word in part.split(" ") if word]
        formatted = " ".join(_format_word(word) for word in words).strip()
        formatted_parts.append(formatted if formatted else part)

    return ", ".join(formatted_parts) if formatted_parts else "Not specified"


def _extract_raw_location(raw_job: dict[str, Any]) -> str:
    locations_text = raw_job.get("locationsText")
    if isinstance(locations_text, str) and locations_text.strip():
        return locations_text.strip()

    locations = raw_job.get("locations")
    if isinstance(locations, list) and locations:
        parts: list[str] = []
        for entry in locations:
            if isinstance(entry, str) and entry.strip():
                parts.append(entry.strip())
            elif isinstance(entry, dict):
                value = entry.get("location") or entry.get("displayName") or entry.get("city")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        if parts:
            return ", ".join(parts)

    return "Not specified"


def extract_season(title: str) -> str:
    normalized = str(title or "").strip()
    if not normalized:
        return "Not specified"

    for season in SEASON_NAMES:
        season_pattern = rf"\b{season}\b"
        season_with_year = re.search(
            rf"{season_pattern}\s+(20\d{{2}})|\b(20\d{{2}})\s+{season_pattern}",
            normalized,
            re.IGNORECASE,
        )
        if season_with_year:
            year = season_with_year.group(1) or season_with_year.group(2)
            return f"{season} {year}"

    for season in SEASON_NAMES:
        if re.search(rf"\b{season}\b", normalized, re.IGNORECASE):
            return season

    year_match = re.search(r"\b(20\d{2})\b", normalized)
    if year_match:
        return year_match.group(1)

    return "Not specified"


def _build_job_id(source: str, company: str, raw_job: dict[str, Any], url: str, location: str, title: str) -> str:
    company_slug = _slug(company)
    external_path = str(raw_job.get("externalPath", "")).strip()
    if external_path:
        token = _slug(external_path)
        return f"{source}-{company_slug}-{token}"

    raw_id = str(raw_job.get("id", "")).strip()
    if raw_id:
        token = _slug(raw_id)
        return f"{source}-{company_slug}-{token}"

    fingerprint = f"{title}::{location}::{url}"
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"{source}-{company_slug}-{digest}"


def normalize_workday_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("title", "Unknown")).strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "workday")).strip() or "workday"
    location = format_location(_extract_raw_location(raw_job))
    career_url = str(raw_job.get("_career_url", "")).strip()
    external_path = str(raw_job.get("externalPath", "")).strip()

    if external_path and career_url:
        if external_path.startswith("/"):
            url = f"{career_url}{external_path}"
        else:
            url = f"{career_url}/{external_path}"
    else:
        url = career_url or "Not specified"

    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    posted_on = raw_job.get("postedOn")
    date_posted = posted_on if isinstance(posted_on, str) and posted_on.strip() else None

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": job_type,
        "season": extract_season(title),
        "source": source,
        "url": url,
        "date_posted": date_posted,
        "date_added": date.today().isoformat(),
        "active": True,
    }
