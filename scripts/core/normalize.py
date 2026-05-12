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
PROVINCE_NAME_TO_CODE = {
    "ontario": "ON",
    "quebec": "QC",
    "québec": "QC",
    "british columbia": "BC",
    "alberta": "AB",
    "manitoba": "MB",
    "saskatchewan": "SK",
    "nova scotia": "NS",
    "new brunswick": "NB",
    "newfoundland and labrador": "NL",
    "prince edward island": "PE",
    "northwest territories": "NT",
    "nunavut": "NU",
    "yukon": "YT",
}
PROVINCE_CODES = {
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
}
COUNTRY_TOKENS = {
    "canada",
    "united states",
    "united states of america",
    "usa",
    "us",
}


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


def _normalize_province(token: str) -> str:
    cleaned = token.strip().strip(".")
    if not cleaned:
        return ""
    upper = cleaned.upper()
    if upper in PROVINCE_CODES:
        return upper
    return PROVINCE_NAME_TO_CODE.get(cleaned.lower(), "")


def _clean_city(token: str) -> str:
    words = [word for word in token.split(" ") if word]
    return " ".join(_format_word(word) for word in words).strip()


def _split_location_tokens(location: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*,\s*", location) if part.strip()]


def normalize_single_location(location: str) -> str:
    text = re.sub(r"\s+", " ", str(location or "").strip())
    if not text:
        return ""

    lowered = text.lower()
    if "remote" in lowered:
        if "canada" in lowered:
            return "Canada Remote"
        return "Remote"

    if lowered == "multiple locations":
        return "Multiple Locations"
    number_match = re.match(r"^(\d+)\s+locations?$", lowered)
    if number_match:
        return f"{number_match.group(1)} Locations"

    parts = _split_location_tokens(text)
    if not parts:
        return ""

    filtered_parts = [part for part in parts if part.lower() not in COUNTRY_TOKENS]
    if not filtered_parts:
        filtered_parts = parts

    province = ""
    province_index = -1
    for index in range(len(filtered_parts) - 1, -1, -1):
        candidate = _normalize_province(filtered_parts[index])
        if candidate:
            province = candidate
            province_index = index
            break

    city = ""
    search_end = province_index if province_index > -1 else len(filtered_parts)
    for index in range(search_end - 1, -1, -1):
        token = filtered_parts[index]
        if re.search(r"\d", token):
            continue
        if _normalize_province(token):
            continue
        if token.lower() in COUNTRY_TOKENS:
            continue
        city = _clean_city(token)
        if city:
            break

    if city and province:
        return f"{city}, {province}"
    if city:
        return city
    if province:
        return province

    fallback = _clean_city(filtered_parts[-1])
    return fallback if fallback else ""


def format_location(location: str) -> str:
    text = re.sub(r"\s+", " ", str(location or "").strip())
    if not text:
        return "Not specified"

    segments = [seg.strip() for seg in re.split(r"\s*;\s*|\s*/\s*", text) if seg.strip()]
    if not segments:
        segments = [text]

    cleaned: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        normalized = normalize_single_location(segment)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)

    if not cleaned:
        return "Not specified"
    return " / ".join(cleaned)


def _extract_location_values_from_entry(entry: Any) -> list[str]:
    if isinstance(entry, str):
        return [entry]
    if not isinstance(entry, dict):
        return []

    values: list[str] = []
    for key in ("displayName", "location", "primaryLocation", "primaryLocationDescriptor"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    city = entry.get("city")
    region = entry.get("state") or entry.get("province") or entry.get("region")
    country = entry.get("country")
    if isinstance(city, str) and city.strip():
        combined = city.strip()
        if isinstance(region, str) and region.strip():
            combined = f"{combined}, {region.strip()}"
        if isinstance(country, str) and country.strip():
            combined = f"{combined}, {country.strip()}"
        values.append(combined)

    return values


def format_locations(raw_job: dict[str, Any]) -> str:
    candidates: list[str] = []

    locations = raw_job.get("locations")
    if isinstance(locations, list) and locations:
        for entry in locations:
            candidates.extend(_extract_location_values_from_entry(entry))
    else:
        for key in ("locationsText", "primaryLocation", "primaryLocationDescriptor"):
            value = raw_job.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

    if not candidates:
        return "Not specified"

    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        formatted = format_location(candidate)
        if formatted == "Not specified":
            continue
        for piece in [part.strip() for part in formatted.split(" / ") if part.strip()]:
            key = piece.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(piece)

    if not cleaned:
        return "Not specified"
    return " / ".join(cleaned)


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
    location = format_locations(raw_job)
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
