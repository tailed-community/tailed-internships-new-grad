from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
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

TRUE_VALUES = {"true", "yes", "1"}
FALSE_VALUES = {"false", "no", "0"}


def load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

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
    hostname = urlsplit(url).hostname or ""
    if "myworkdayjobs.com" in hostname.lower():
        return "workday"
    return None


def extract_workday_parts(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    segments = hostname.split(".")
    if not segments or not segments[0]:
        raise ValueError("missing Workday tenant in hostname")

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if not path_segments:
        raise ValueError("missing Workday site in URL path")

    tenant = segments[0].lower()
    site = path_segments[0]
    return tenant, site


def build_workday_company(company: str, url: str, enabled: bool) -> dict[str, Any]:
    tenant, site = extract_workday_parts(url)
    return {
        "company": company,
        "source": "workday",
        "url": url,
        "tenant": tenant,
        "site": site,
        "enabled": enabled,
        "search_terms": WORKDAY_SEARCH_TERMS,
    }


def build_company_config(company: str, url: str, enabled: bool) -> dict[str, Any] | None:
    source = detect_source(url)
    if source == "workday":
        return build_workday_company(company, url, enabled)
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

    seen_urls: dict[str, str] = {}
    seen_company_source_urls: set[tuple[str, str, str]] = set()

    for company in existing_companies:
        source = str(company.get("source", "")).strip().lower()
        company_name = str(company.get("company", "")).strip()
        raw_url = company.get("url")
        if not company_name or not source or not isinstance(raw_url, str) or not raw_url.strip():
            continue

        normalized_url = normalize_url(raw_url)
        seen_urls.setdefault(normalized_url, company_name or source or "existing entry")
        seen_company_source_urls.add((company_name.casefold(), source, normalized_url))

    added_count = 0
    skipped_count = 0
    warned_count = 0

    for index, row in enumerate(source_rows, start=2):
        company_name = row.get("company", "").strip()
        raw_url = row.get("url", "").strip()
        raw_enabled = row.get("enabled", "").strip()

        if not company_name or not raw_url:
            warned_count += 1
            print(f"[warn] Row {index}: missing company or url, skipping.")
            continue

        enabled = parse_enabled(raw_enabled)
        if enabled is None:
            warned_count += 1
            print(
                f"[warn] Row {index} ({company_name}): unsupported enabled value "
                f"'{raw_enabled}', skipping."
            )
            continue

        normalized_url = normalize_url(raw_url)
        source = detect_source(normalized_url)
        if source is None:
            warned_count += 1
            print(
                f"[warn] Row {index} ({company_name}): unsupported URL "
                f"'{normalized_url}', skipping."
            )
            continue

        company_source_url_key = (company_name.casefold(), source, normalized_url)
        if normalized_url in seen_urls:
            skipped_count += 1
            print(
                f"[skip] Row {index} ({company_name}): URL already exists in "
                f"data/companies.json ({normalized_url})."
            )
            continue

        if company_source_url_key in seen_company_source_urls:
            skipped_count += 1
            print(
                f"[skip] Row {index} ({company_name}): equivalent company/source/url "
                f"entry already exists, skipping."
            )
            continue

        try:
            config = build_company_config(company_name, normalized_url, enabled)
        except ValueError as error:
            warned_count += 1
            print(f"[warn] Row {index} ({company_name}): {error}, skipping.")
            continue

        if config is None:
            warned_count += 1
            print(
                f"[warn] Row {index} ({company_name}): unsupported URL "
                f"'{normalized_url}', skipping."
            )
            continue

        existing_companies.append(config)
        seen_urls[normalized_url] = company_name
        seen_company_source_urls.add(company_source_url_key)
        added_count += 1
        print(f"[add] Row {index} ({company_name}): added {source} config.")

    sorted_companies = sort_company_configs(existing_companies)
    save_json_list(companies_path, sorted_companies)

    print("\nCompany sync summary")
    print(f"- CSV rows processed: {len(source_rows)}")
    print(f"- Added: {added_count}")
    print(f"- Skipped duplicates: {skipped_count}")
    print(f"- Warnings: {warned_count}")
    print(f"- Total companies saved: {len(sorted_companies)}")


if __name__ == "__main__":
    main()
