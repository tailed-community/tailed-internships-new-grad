from __future__ import annotations

import hashlib
import re
from datetime import datetime
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
    "ca",
    "united states",
    "united states of america",
    "usa",
    "us",
    "france",
    "united kingdom",
    "uk",
}
COUNTRY_MAP = {
    "canada": "Canada",
    "ca": "Canada",
    "united states": "United States",
    "united states of america": "United States",
    "usa": "United States",
    "us": "United States",
    "france": "France",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
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


def _is_generic_location_value(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return True
    if lowered == "multiple locations":
        return True
    if re.match(r"^\d+\s+locations?$", lowered):
        return True
    return False


def _normalize_country(token: str) -> str | None:
    cleaned = token.strip().strip(".")
    if not cleaned:
        return None
    return COUNTRY_MAP.get(cleaned.lower())


def _extract_country_from_free_text(text: str) -> str | None:
    lowered = text.lower()
    for raw, normalized in sorted(COUNTRY_MAP.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(raw)}\b", lowered):
            return normalized
    return None


def _normalize_region(token: str) -> str:
    province = _normalize_province(token)
    if province:
        return province

    cleaned = token.strip().strip(".")
    if re.fullmatch(r"[A-Za-z]{2}", cleaned):
        return cleaned.upper()
    return ""


def strip_workday_address_prefix(location: str) -> str:
    text = str(location or "").strip()
    if ":" not in text:
        return text
    return text.split(":")[-1].strip()


def extract_country_hint(location_object: dict) -> str | None:
    for key in ("country", "countryName", "countryDescriptor"):
        value = location_object.get(key)
        if isinstance(value, str) and value.strip():
            normalized = _normalize_country(value)
            if normalized:
                return normalized
            return _clean_city(value.strip())
    return None


def normalize_single_location(location: str, country_hint: str | None = None) -> str:
    text = re.sub(r"\s+", " ", str(location or "").strip())
    if not text:
        return ""
    text = strip_workday_address_prefix(text)
    if not text:
        return ""

    lowered = text.lower()
    if "remote" in lowered:
        country = _extract_country_from_free_text(text)
        for token in _split_location_tokens(text):
            normalized_country = _normalize_country(token)
            if normalized_country:
                country = normalized_country
                break
        if not country and country_hint:
            country = _normalize_country(country_hint) or _clean_city(country_hint)
        if country:
            return f"{country} Remote"
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
    country = None
    for part in parts:
        normalized_country = _normalize_country(part)
        if normalized_country:
            country = normalized_country
    if not country and country_hint:
        country = _normalize_country(country_hint) or _clean_city(country_hint)

    if not filtered_parts:
        filtered_parts = [part for part in parts if not _normalize_country(part)]
    if not filtered_parts:
        filtered_parts = parts

    province = ""
    province_index = -1
    for index in range(len(filtered_parts) - 1, -1, -1):
        candidate = _normalize_region(filtered_parts[index])
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
        if _normalize_region(token):
            continue
        if token.lower() in COUNTRY_TOKENS:
            continue
        city = _clean_city(token)
        if city:
            break

    if city and province and country:
        return f"{city}, {province}, {country}"
    if city and province:
        return f"{city}, {province}"
    if city and country:
        return f"{city}, {country}"
    if city:
        return city
    if province and country:
        return f"{province}, {country}"
    if province:
        return province
    if country:
        return country

    fallback = _clean_city(filtered_parts[-1])
    if fallback and country:
        return f"{fallback}, {country}"
    return fallback if fallback else ""


def format_location_text(location: str, country_hint: str | None = None) -> str:
    text = re.sub(r"\s+", " ", str(location or "").strip())
    if not text:
        return "Not specified"

    segments = [seg.strip() for seg in re.split(r"\s*;\s*|\s*/\s*", text) if seg.strip()]
    if not segments:
        segments = [text]

    cleaned: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        normalized = normalize_single_location(segment, country_hint=country_hint)
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


def format_location(location: str) -> str:
    return format_location_text(location)


def _extract_location_values_from_entry(entry: Any) -> list[tuple[str, str | None]]:
    if isinstance(entry, str):
        return [(entry, None)]
    if not isinstance(entry, dict):
        return []

    values: list[tuple[str, str | None]] = []
    country_hint = extract_country_hint(entry)
    for key in ("displayName", "descriptor", "location", "primaryLocation", "primaryLocationDescriptor"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            values.append((value.strip(), country_hint))

    city = entry.get("city")
    region = (
        entry.get("state")
        or entry.get("province")
        or entry.get("region")
        or entry.get("countryRegion")
        or entry.get("countryRegionDescriptor")
    )
    country = entry.get("country")
    if isinstance(city, str) and city.strip():
        combined = city.strip()
        if isinstance(region, str) and region.strip():
            combined = f"{combined}, {region.strip()}"
        if isinstance(country, str) and country.strip():
            combined = f"{combined}, {country.strip()}"
        values.append((combined, country_hint))

    return values


def _extract_priority_candidates(raw_job: dict[str, Any]) -> list[list[tuple[str, str | None]]]:
    prioritized: list[list[tuple[str, str | None]]] = []

    detail_locations_values: list[tuple[str, str | None]] = []
    detail_locations = raw_job.get("_detail_locations")
    if isinstance(detail_locations, list) and detail_locations:
        for entry in detail_locations:
            if isinstance(entry, str) and entry.strip():
                detail_locations_values.append((entry.strip(), None))
            elif isinstance(entry, dict):
                detail_locations_values.extend(_extract_location_values_from_entry(entry))
    prioritized.append(detail_locations_values)

    locations_values: list[tuple[str, str | None]] = []
    locations = raw_job.get("locations")
    if isinstance(locations, list) and locations:
        for entry in locations:
            locations_values.extend(_extract_location_values_from_entry(entry))
    prioritized.append(locations_values)

    primary_location_values: list[tuple[str, str | None]] = []
    primary_location = raw_job.get("primaryLocation")
    if isinstance(primary_location, str) and primary_location.strip():
        primary_location_values.append((primary_location.strip(), None))
    elif isinstance(primary_location, dict):
        primary_location_values.extend(_extract_location_values_from_entry(primary_location))
    prioritized.append(primary_location_values)

    primary_descriptor_values: list[tuple[str, str | None]] = []
    primary_descriptor = raw_job.get("primaryLocationDescriptor")
    if isinstance(primary_descriptor, str) and primary_descriptor.strip():
        primary_descriptor_values.append((primary_descriptor.strip(), None))
    elif isinstance(primary_descriptor, dict):
        primary_descriptor_values.extend(_extract_location_values_from_entry(primary_descriptor))
    prioritized.append(primary_descriptor_values)

    locations_text_values: list[tuple[str, str | None]] = []
    locations_text = raw_job.get("locationsText")
    if isinstance(locations_text, str) and locations_text.strip():
        locations_text_values.append((locations_text.strip(), None))
    prioritized.append(locations_text_values)

    return prioritized


def _dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def format_locations(raw_job: dict[str, Any]) -> str:
    prioritized = _extract_priority_candidates(raw_job)
    generic_fallback = ""

    for candidates in prioritized:
        if not candidates:
            continue

        normalized_parts: list[str] = []
        generic_parts: list[str] = []
        for candidate, country_hint in candidates:
            formatted = format_location_text(candidate, country_hint=country_hint)
            if formatted == "Not specified":
                continue
            pieces = [part.strip() for part in formatted.split(" / ") if part.strip()]
            for piece in pieces:
                if _is_generic_location_value(piece):
                    generic_parts.append(piece)
                else:
                    normalized_parts.append(piece)

        normalized_parts = _dedupe_ordered(normalized_parts)
        generic_parts = _dedupe_ordered(generic_parts)

        if normalized_parts:
            return " / ".join(normalized_parts)
        if generic_parts and not generic_fallback:
            generic_fallback = " / ".join(generic_parts)

    return generic_fallback or "Not specified"


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


def _extract_lever_location_values(raw_job: dict[str, Any]) -> list[str]:
    values: list[str] = []
    categories = raw_job.get("categories")
    if isinstance(categories, dict):
        all_locations = categories.get("allLocations")
        if isinstance(all_locations, list):
            for entry in all_locations:
                if isinstance(entry, str) and entry.strip():
                    values.append(entry.strip())

        location = categories.get("location")
        if isinstance(location, str) and location.strip():
            values.append(location.strip())

    workplace_type = str(raw_job.get("workplaceType", "")).strip()
    country = raw_job.get("country")
    country_text = country.strip() if isinstance(country, str) and country.strip() else ""

    if not values and workplace_type.lower() == "remote":
        if country_text:
            values.append(f"Remote, {country_text}")
        else:
            values.append("Remote")
    elif not values and country_text:
        values.append(country_text)

    return values


def _format_lever_locations(raw_job: dict[str, Any]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()

    for value in _extract_lever_location_values(raw_job):
        text = re.sub(r"\s+", " ", str(value or "").strip())
        city_region_match = re.match(r"^(?P<city>[^,]+),\s*(?P<region>[A-Za-z]{2})$", text)
        if city_region_match:
            formatted = (
                f"{_clean_city(city_region_match.group('city'))}, "
                f"{city_region_match.group('region').upper()}"
            )
        else:
            formatted = format_location_text(text)
        if formatted == "Not specified":
            continue

        for part in [piece.strip() for piece in formatted.split(" / ") if piece.strip()]:
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(part)

    if not cleaned:
        return "Not specified"
    return " / ".join(cleaned)


def _normalize_lever_created_at(raw_value: Any) -> str | None:
    timestamp: float | None = None
    if isinstance(raw_value, (int, float)):
        timestamp = float(raw_value)
    elif isinstance(raw_value, str) and raw_value.strip():
        try:
            timestamp = float(raw_value.strip())
        except ValueError:
            return None

    if timestamp is None:
        return None

    if timestamp > 10_000_000_000:
        timestamp /= 1000.0

    try:
        return datetime.utcfromtimestamp(timestamp).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _normalize_iso_date(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None

    text = raw_value.strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def normalize_lever_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("text", "Unknown")).strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "lever")).strip() or "lever"
    location = _format_lever_locations(raw_job)
    url = (
        str(raw_job.get("hostedUrl", "")).strip()
        or str(raw_job.get("applyUrl", "")).strip()
        or str(raw_job.get("_career_url", "")).strip()
        or "Not specified"
    )
    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": job_type,
        "season": extract_season(title),
        "source": source,
        "url": url,
        "date_posted": _normalize_lever_created_at(raw_job.get("createdAt")),
        "date_added": date.today().isoformat(),
        "active": True,
    }


def normalize_greenhouse_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("title", "Unknown")).strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "greenhouse")).strip() or "greenhouse"
    location_data = raw_job.get("location")
    location_text = ""
    if isinstance(location_data, dict):
        raw_name = location_data.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            location_text = raw_name.strip()
    elif isinstance(location_data, str) and location_data.strip():
        location_text = location_data.strip()

    location = format_location_text(location_text) if location_text else "Not specified"
    url = (
        str(raw_job.get("absolute_url", "")).strip()
        or str(raw_job.get("_career_url", "")).strip()
        or "Not specified"
    )
    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    date_posted = _normalize_iso_date(raw_job.get("first_published")) or _normalize_iso_date(
        raw_job.get("updated_at")
    )

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


def _extract_ashby_location_values(raw_job: dict[str, Any]) -> list[tuple[str, str | None]]:
    values: list[tuple[str, str | None]] = []

    primary_address_values: list[tuple[str, str | None]] = []
    address = raw_job.get("address")
    if isinstance(address, dict):
        postal_address = address.get("postalAddress")
        if isinstance(postal_address, dict):
            primary_address_values = _extract_ashby_postal_address_values(postal_address)

    if primary_address_values:
        values.extend(primary_address_values)
    else:
        location = raw_job.get("location")
        if isinstance(location, str) and location.strip():
            values.append((location.strip(), None))

    secondary_locations = raw_job.get("secondaryLocations")
    if isinstance(secondary_locations, list):
        for entry in secondary_locations:
            if isinstance(entry, str) and entry.strip():
                values.append((entry.strip(), None))
            elif isinstance(entry, dict):
                secondary_address = entry.get("address")
                secondary_address_values: list[tuple[str, str | None]] = []
                if isinstance(secondary_address, dict):
                    secondary_address_values = _extract_ashby_postal_address_values(secondary_address)
                if secondary_address_values:
                    values.extend(secondary_address_values)
                else:
                    secondary_location = entry.get("location")
                    if isinstance(secondary_location, str) and secondary_location.strip():
                        values.append((secondary_location.strip(), None))

    is_remote = raw_job.get("isRemote") is True
    workplace_type = str(raw_job.get("workplaceType", "")).strip().lower()
    if is_remote or workplace_type == "remote":
        country = ""
        if isinstance(address, dict):
            postal_address = address.get("postalAddress")
            if isinstance(postal_address, dict):
                raw_country = postal_address.get("addressCountry")
                if isinstance(raw_country, str) and raw_country.strip():
                    country = raw_country.strip()
        values.append((f"Remote, {country}" if country else "Remote", None))

    return values


def _extract_ashby_postal_address_values(address: dict[str, Any]) -> list[tuple[str, str | None]]:
    city = address.get("addressLocality")
    region = address.get("addressRegion")
    country = address.get("addressCountry")

    parts = [
        value.strip()
        for value in (city, region, country)
        if isinstance(value, str) and value.strip()
    ]
    if not parts:
        return []

    country_hint = country.strip() if isinstance(country, str) and country.strip() else None
    return [(", ".join(parts), country_hint)]


def _format_ashby_locations(raw_job: dict[str, Any]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()

    for value, country_hint in _extract_ashby_location_values(raw_job):
        formatted = format_location_text(value, country_hint=country_hint)
        if formatted == "Not specified":
            continue
        for part in [piece.strip() for piece in formatted.split(" / ") if piece.strip()]:
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(part)

    if not cleaned:
        return "Not specified"
    return " / ".join(cleaned)


def normalize_ashby_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("title", "Unknown")).strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None and str(raw_job.get("employmentType", "")).strip().lower() == "intern":
        job_type = "internship"
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "ashby")).strip() or "ashby"
    location = _format_ashby_locations(raw_job)
    url = (
        str(raw_job.get("jobUrl", "")).strip()
        or str(raw_job.get("applyUrl", "")).strip()
        or str(raw_job.get("_career_url", "")).strip()
        or "Not specified"
    )
    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": job_type,
        "season": extract_season(title),
        "source": source,
        "url": url,
        "date_posted": _normalize_iso_date(raw_job.get("publishedAt")),
        "date_added": date.today().isoformat(),
        "active": True,
    }


def _normalize_icims_posted_at(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None

    text = raw_value.strip()
    if not text:
        return None

    iso_date = _normalize_iso_date(text)
    if iso_date:
        return iso_date

    for pattern in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue

    return None


def _format_icims_location(location: str) -> str:
    text = str(location or "").strip()
    if not text:
        return "Not specified"

    parts: list[str] = []
    for segment in re.split(r"\s*\|\s*|\s*/\s*", text):
        segment = segment.strip()
        if not segment:
            continue

        coded_match = re.match(
            r"^(?P<country>[A-Za-z]{2})-(?P<region>[A-Za-z]{2})-(?P<city>.+)$",
            segment,
        )
        if coded_match:
            city = coded_match.group("city").replace("-", " ")
            region = coded_match.group("region").upper()
            country = _normalize_country(coded_match.group("country")) or coded_match.group(
                "country"
            ).upper()
            segment = f"{city}, {region}, {country}"
        else:
            country_region_match = re.match(
                r"^(?P<country>[A-Za-z]{2})-(?P<region>[A-Za-z]{2})$",
                segment,
            )
            if country_region_match:
                region = country_region_match.group("region").upper()
                country = _normalize_country(country_region_match.group("country")) or (
                    country_region_match.group("country").upper()
                )
                segment = f"{region}, {country}"
            elif re.fullmatch(r"[A-Za-z]{2}", segment):
                country = _normalize_country(segment)
                if country:
                    segment = country

        formatted = format_location_text(segment)
        if formatted != "Not specified":
            parts.extend(piece.strip() for piece in formatted.split(" / ") if piece.strip())

    deduped = _dedupe_ordered(parts)
    if not deduped:
        return "Not specified"
    return " / ".join(deduped)


def normalize_icims_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("title", "Unknown")).strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None and str(raw_job.get("employment_type", "")).strip().lower() == "intern":
        job_type = "internship"
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "icims")).strip() or "icims"
    location_text = str(raw_job.get("location", "")).strip()
    location = _format_icims_location(location_text)
    url = (
        str(raw_job.get("url", "")).strip()
        or str(raw_job.get("_career_url", "")).strip()
        or "Not specified"
    )
    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": job_type,
        "season": extract_season(title),
        "source": source,
        "url": url,
        "date_posted": _normalize_icims_posted_at(raw_job.get("posted_at")),
        "date_added": date.today().isoformat(),
        "active": True,
    }


def normalize_oracle_hcm_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("Title") or raw_job.get("title") or "Unknown").strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "oracle_hcm")).strip() or "oracle_hcm"
    location_text = str(raw_job.get("PrimaryLocation", "")).strip()
    location = format_location_text(location_text) if location_text else "Not specified"
    url = (
        str(raw_job.get("_url", "")).strip()
        or str(raw_job.get("_career_url", "")).strip()
        or "Not specified"
    )
    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": job_type,
        "season": extract_season(title),
        "source": source,
        "url": url,
        "date_posted": _normalize_iso_date(raw_job.get("PostedDate")),
        "date_added": date.today().isoformat(),
        "active": True,
    }


def _format_rippling_locations(raw_job: dict[str, Any]) -> str:
    locations = raw_job.get("locations")
    if not isinstance(locations, list):
        return "Not specified"

    parts: list[str] = []
    seen: set[str] = set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        location_name = str(location.get("name", "")).strip()
        workplace_type = str(location.get("workplaceType", "")).strip().upper()
        if location_name:
            value = location_name
        else:
            city = str(location.get("city", "")).strip()
            state = str(location.get("stateCode") or location.get("state") or "").strip()
            country = str(location.get("country", "")).strip()
            value = ", ".join(part for part in (city, state, country) if part)

        if workplace_type == "REMOTE":
            value = f"Remote, {value}" if value else "Remote"

        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(value)

    if not parts:
        return "Not specified"
    return " / ".join(parts)


def normalize_rippling_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    company = str(raw_job.get("_company", "Unknown")).strip() or "Unknown"
    title = str(raw_job.get("name") or raw_job.get("title") or "Unknown").strip() or "Unknown"
    job_type = classify_job_type(title)
    if job_type is None:
        return None

    source = str(raw_job.get("_source", "rippling")).strip() or "rippling"
    location = _format_rippling_locations(raw_job)
    url = (
        str(raw_job.get("_url", "")).strip()
        or str(raw_job.get("url", "")).strip()
        or str(raw_job.get("_career_url", "")).strip()
        or "Not specified"
    )
    job_id = _build_job_id(
        source=source,
        company=company,
        raw_job=raw_job,
        url=url,
        location=location,
        title=title,
    )

    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": job_type,
        "season": extract_season(title),
        "source": source,
        "url": url,
        "date_posted": None,
        "date_added": date.today().isoformat(),
        "active": True,
    }
