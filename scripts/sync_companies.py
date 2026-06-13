from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit, urlunsplit


WORKDAY_SEARCH_TERMS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "co op",
    "student",
    "summer student",
    "new grad",
    "new graduate",
    "graduate",
]

ICIMS_SEARCH_TERMS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "student",
    "new grad",
    "new graduate",
    "early career",
    "entry level",
]

ORACLE_HCM_SEARCH_TERMS = [
    "intern",
    "internship",
    "co-op",
    "coop",
    "student",
    "new grad",
    "new graduate",
    "early career",
    "entry level",
]

TRUE_VALUES = {"true", "yes", "1"}
FALSE_VALUES = {"false", "no", "0"}


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        raw_text = file.read()

    if not raw_text.strip():
        return []

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"[warn] Could not parse '{path}': {error}. Rebuilding from CSV.")
        return []

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in '{path}'.")

    return [item for item in data if isinstance(item, dict)]


def save_json_list(path: Path, data: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def load_company_sources(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        expected_columns = ["company", "url", "enabled"]
        if reader.fieldnames != expected_columns:
            raise ValueError(
                f"Expected CSV columns {expected_columns}, found {reader.fieldnames!r}."
            )

        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({key: (value or "").strip() for key, value in row.items()})
        return rows


def save_company_sources(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["company", "url", "enabled"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "")).strip() for field in fieldnames})


def parse_enabled(raw_value: str) -> bool | None:
    value = raw_value.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return None


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def detect_source(url: str) -> str | None:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    query = parsed.query.lower()
    if "myworkdayjobs.com" in hostname:
        return "workday"
    if hostname in {"jobs.lever.co", "jobs.eu.lever.co"}:
        return "lever"
    if hostname in {
        "boards.greenhouse.io",
        "boards-api.greenhouse.io",
        "job-boards.greenhouse.io",
    }:
        return "greenhouse"
    if hostname == "jobs.ashbyhq.com":
        return "ashby"
    if (
        hostname == "api.ashbyhq.com"
        and len(path_segments) >= 3
        and path_segments[0].lower() == "posting-api"
        and path_segments[1].lower() == "job-board"
    ):
        return "ashby"
    if hostname.endswith(".icims.com"):
        return "icims"
    if hostname.endswith(".jibeapply.com") or "icims=1" in query:
        return "icims"
    if (
        (hostname.endswith(".oraclecloud.com") or hostname.endswith(".ocs.oraclecloud.com"))
        and "candidateexperience" in {segment.lower() for segment in path_segments}
        and "sites" in {segment.lower() for segment in path_segments}
    ):
        return "oracle_hcm"
    return None


def extract_workday_parts(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    segments = hostname.split(".")
    if not segments or not segments[0]:
        raise ValueError("missing Workday tenant in hostname")

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        raise ValueError("missing Workday site in URL path")

    canonical_segments = path_segments
    for index, segment in enumerate(path_segments):
        if segment.lower() == "job":
            canonical_segments = path_segments[:index]
            break

    if not canonical_segments:
        raise ValueError("missing Workday site in URL path")

    tenant = segments[0].lower()
    site = canonical_segments[-1]
    canonical_url = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            f"/{'/'.join(canonical_segments)}",
            "",
            "",
        )
    )
    return tenant, site, canonical_url


def extract_lever_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        raise ValueError("missing Lever site slug in URL path")

    slug = path_segments[0].strip().lower()
    if not slug:
        raise ValueError("missing Lever site slug in URL path")

    canonical_url = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), f"/{slug}", "", ""))
    return slug, canonical_url


def extract_greenhouse_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    path_segments = [segment for segment in parsed.path.split("/") if segment]

    slug = ""
    if hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if path_segments:
            slug = path_segments[0].strip().lower()
    elif hostname == "boards-api.greenhouse.io":
        if len(path_segments) >= 3 and path_segments[0].lower() == "v1" and path_segments[1].lower() == "boards":
            slug = path_segments[2].strip().lower()

    if not slug:
        raise ValueError("missing Greenhouse board token in URL path")

    canonical_url = f"https://boards.greenhouse.io/{slug}"
    return slug, canonical_url


def extract_ashby_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    path_segments = [segment for segment in parsed.path.split("/") if segment]

    slug = ""
    if hostname == "jobs.ashbyhq.com":
        if path_segments:
            slug = unquote(path_segments[0]).strip()
    elif hostname == "api.ashbyhq.com":
        if (
            len(path_segments) >= 3
            and path_segments[0].lower() == "posting-api"
            and path_segments[1].lower() == "job-board"
        ):
            slug = unquote(path_segments[2]).strip()

    if not slug:
        raise ValueError("missing Ashby job board name in URL path")

    canonical_url = f"https://jobs.ashbyhq.com/{quote(slug, safe='')}"
    return slug, canonical_url


def extract_icims_parts(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("missing iCIMS hostname")

    if hostname.endswith(".icims.com"):
        return hostname, "classic", f"https://{hostname}/jobs/search"

    if hostname.endswith(".jibeapply.com") or "icims=1" in parsed.query.lower():
        return hostname, "jibe", f"https://{hostname}?icims=1"

    raise ValueError("unsupported iCIMS URL")


def extract_oracle_hcm_parts(url: str) -> tuple[str, str, str, str]:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("missing Oracle HCM hostname")

    path_segments = [unquote(segment).strip() for segment in parsed.path.split("/") if segment]
    lowered_segments = [segment.lower() for segment in path_segments]
    try:
        candidate_experience_index = lowered_segments.index("candidateexperience")
        sites_index = lowered_segments.index("sites")
    except ValueError as error:
        raise ValueError("missing Oracle HCM CandidateExperience site path") from error

    if candidate_experience_index + 1 >= len(path_segments):
        raise ValueError("missing Oracle HCM language in URL path")
    if sites_index + 1 >= len(path_segments):
        raise ValueError("missing Oracle HCM site in URL path")

    language = path_segments[candidate_experience_index + 1]
    site = path_segments[sites_index + 1]
    if not language or not site:
        raise ValueError("missing Oracle HCM language or site in URL path")

    canonical_url = (
        f"https://{hostname}/hcmUI/CandidateExperience/"
        f"{quote(language, safe='')}/sites/{quote(site, safe='')}"
    )
    return hostname, language, site, canonical_url


def build_workday_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    tenant, site, canonical_url = extract_workday_parts(url)
    return {
        "company": company,
        "source": "workday",
        "url": canonical_url,
        "tenant": tenant,
        "site": site,
        "enabled": enabled,
        "search_terms": WORKDAY_SEARCH_TERMS,
    }


def build_lever_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    slug, canonical_url = extract_lever_parts(url)
    return {
        "company": company,
        "source": "lever",
        "url": canonical_url,
        "slug": slug,
        "enabled": enabled,
    }


def build_greenhouse_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    slug, canonical_url = extract_greenhouse_parts(url)
    return {
        "company": company,
        "source": "greenhouse",
        "url": canonical_url,
        "slug": slug,
        "enabled": enabled,
    }


def build_ashby_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    slug, canonical_url = extract_ashby_parts(url)
    return {
        "company": company,
        "source": "ashby",
        "url": canonical_url,
        "slug": slug,
        "enabled": enabled,
    }


def build_icims_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    host, mode, canonical_url = extract_icims_parts(url)
    config: dict[str, Any] = {
        "company": company,
        "source": "icims",
        "url": canonical_url,
        "host": host,
        "mode": mode,
        "enabled": enabled,
    }
    if mode == "classic":
        config["search_terms"] = ICIMS_SEARCH_TERMS
    return config


def build_oracle_hcm_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    host, language, site, canonical_url = extract_oracle_hcm_parts(url)
    return {
        "company": company,
        "source": "oracle_hcm",
        "url": canonical_url,
        "host": host,
        "language": language,
        "site": site,
        "enabled": enabled,
        "search_terms": ORACLE_HCM_SEARCH_TERMS,
    }


def build_company_config(company: str, url: str, enabled: bool) -> dict[str, Any] | None:
    source = detect_source(url)
    if source == "workday":
        return build_workday_company(company, url, enabled)
    if source == "lever":
        return build_lever_company(company, url, enabled)
    if source == "greenhouse":
        return build_greenhouse_company(company, url, enabled)
    if source == "ashby":
        return build_ashby_company(company, url, enabled)
    if source == "icims":
        return build_icims_company(company, url, enabled)
    if source == "oracle_hcm":
        return build_oracle_hcm_company(company, url, enabled)
    return None


def sort_company_configs(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        companies,
        key=lambda company: (
            str(company.get("company", "")).casefold(),
            str(company.get("source", "")).casefold(),
            normalize_url(str(company.get("url", ""))) if company.get("url") else "",
        ),
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    csv_path = repo_root / "data" / "company_sources.csv"
    companies_path = repo_root / "data" / "companies.json"

    source_rows = load_company_sources(csv_path)
    existing_companies = load_json_list(companies_path)

    seen_urls: dict[str, tuple[str, str]] = {}
    existing_index_by_company_source: dict[tuple[str, str], int] = {}
    seen_csv_urls: dict[str, tuple[int, str]] = {}
    seen_csv_company_sources: dict[tuple[str, str], int] = {}
    cleaned_source_rows: list[dict[str, str]] = []

    for index, company in enumerate(existing_companies):
        source = str(company.get("source", "")).strip().lower()
        company_name = str(company.get("company", "")).strip()
        if not company_name or not source:
            continue

        company_source_key = (company_name.casefold(), source)
        existing_index_by_company_source[company_source_key] = index

        raw_url = company.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            continue

        normalized_url = normalize_url(raw_url)
        seen_urls.setdefault(normalized_url, company_source_key)

    added_count = 0
    updated_count = 0
    skipped_count = 0
    warned_count = 0

    for index, row in enumerate(source_rows, start=2):
        company_name = row.get("company", "").strip()
        raw_url = row.get("url", "").strip()
        raw_enabled = row.get("enabled", "").strip()
        cleaned_csv_row = {
            "company": company_name,
            "url": raw_url,
            "enabled": raw_enabled,
        }

        if not company_name or not raw_url:
            warned_count += 1
            print(f"[warn] Row {index}: missing company or url, skipping.")
            cleaned_source_rows.append(cleaned_csv_row)
            continue

        normalized_url = normalize_url(raw_url)
        source = detect_source(normalized_url)
        previous_csv_url = seen_csv_urls.get(normalized_url)
        if previous_csv_url is not None:
            previous_row, previous_company = previous_csv_url
            warned_count += 1
            skipped_count += 1
            print(
                f"[warn] Row {index} ({company_name}): duplicate URL in "
                f"data/company_sources.csv; first seen on row {previous_row} "
                f"for {previous_company}. Skipping later row."
            )
            continue

        seen_csv_urls[normalized_url] = (index, company_name)

        enabled = parse_enabled(raw_enabled)
        if enabled is None:
            warned_count += 1
            print(
                f"[warn] Row {index} ({company_name}): unsupported enabled value "
                f"'{raw_enabled}', skipping company sync but keeping CSV row."
            )
            cleaned_source_rows.append(cleaned_csv_row)
            continue

        if source is None:
            warned_count += 1
            print(
                f"[warn] Row {index} ({company_name}): unsupported URL "
                f"'{normalized_url}', skipping company sync but keeping CSV row."
            )
            cleaned_source_rows.append(
                {
                    "company": company_name,
                    "url": normalized_url,
                    "enabled": "true" if enabled else "false",
                }
            )
            continue

        company_source_key = (company_name.casefold(), source)
        previous_csv_company_source_row = seen_csv_company_sources.get(company_source_key)
        if previous_csv_company_source_row is not None:
            warned_count += 1
            skipped_count += 1
            print(
                f"[warn] Row {index} ({company_name}): duplicate company/source entry in "
                f"data/company_sources.csv; first seen on row {previous_csv_company_source_row}. "
                f"Skipping later row."
            )
            continue

        seen_csv_company_sources[company_source_key] = index

        try:
            config = build_company_config(company_name, normalized_url, enabled)
        except ValueError as error:
            warned_count += 1
            print(f"[warn] Row {index} ({company_name}): {error}, skipping.")
            cleaned_source_rows.append(
                {
                    "company": company_name,
                    "url": normalized_url,
                    "enabled": "true" if enabled else "false",
                }
            )
            continue

        if config is None:
            warned_count += 1
            print(
                f"[warn] Row {index} ({company_name}): unsupported URL "
                f"'{normalized_url}', skipping."
            )
            cleaned_source_rows.append(
                {
                    "company": company_name,
                    "url": normalized_url,
                    "enabled": "true" if enabled else "false",
                }
            )
            continue

        config_url = str(config.get("url", "")).strip()
        if config_url:
            existing_owner = seen_urls.get(config_url)
            if existing_owner is not None and existing_owner != company_source_key:
                skipped_count += 1
                print(
                    f"[skip] Row {index} ({company_name}): URL already belongs to "
                    f"another company/source entry ({config_url})."
                )
                continue

        cleaned_source_rows.append(
            {
                "company": company_name,
                "url": config_url or normalized_url,
                "enabled": "true" if enabled else "false",
            }
        )

        existing_index = existing_index_by_company_source.get(company_source_key)
        if existing_index is not None:
            existing_entry = existing_companies[existing_index]
            if existing_entry == config:
                skipped_count += 1
                print(
                    f"[skip] Row {index} ({company_name}): company/source entry is "
                    f"already up to date."
                )
                continue

            existing_companies[existing_index] = config
            updated_count += 1
            print(f"[update] Row {index} ({company_name}): synced existing {source} config.")
        else:
            existing_companies.append(config)
            existing_index_by_company_source[company_source_key] = len(existing_companies) - 1
            added_count += 1
            print(f"[add] Row {index} ({company_name}): added {source} config.")

        if config_url:
            seen_urls[config_url] = company_source_key

    sorted_companies = sort_company_configs(existing_companies)
    save_company_sources(csv_path, cleaned_source_rows)
    save_json_list(companies_path, sorted_companies)

    print("\nCompany sync summary")
    print(f"- CSV rows processed: {len(source_rows)}")
    print(f"- Added: {added_count}")
    print(f"- Updated: {updated_count}")
    print(f"- Skipped duplicates: {skipped_count}")
    print(f"- Warnings: {warned_count}")
    print(f"- Total companies saved: {len(sorted_companies)}")


if __name__ == "__main__":
    main()
