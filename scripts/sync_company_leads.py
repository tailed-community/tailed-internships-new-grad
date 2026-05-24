from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from sync_companies import (
    build_company_config,
    load_company_sources,
    normalize_url,
    save_company_sources,
)


EXPECTED_COLUMNS = ["company", "url", "title", "location", "query", "native_url", "notes"]
DEFAULT_DISCOVERY_URL = "https://www.glassdoor.ca/Job/canada-internship-jobs-SRCH_IL.0,6_IN3_KO7,17.htm"
DEFAULT_QUERY = "internship"
DEFAULT_LOCATION = "Canada"
DEFAULT_MAX_RESULTS = 25


class _GlassdoorTokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[dict[str, str]] = []
        self._current_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        href = attr_map.get("href", "").strip()
        self._current_href = href or None

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._current_href = None

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split()).strip()
        if not text:
            return
        if self._current_href:
            self.tokens.append({"kind": "link", "text": text, "href": self._current_href})
        else:
            self.tokens.append({"kind": "text", "text": text})


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in '{path}'.")

    return [item for item in data if isinstance(item, dict)]


def save_json_list(path: Path, data: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def load_glassdoor_leads(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(
                f"Expected CSV columns {EXPECTED_COLUMNS}, found {reader.fieldnames!r}."
            )

        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({key: (value or "").strip() for key, value in row.items()})
        return rows


def save_glassdoor_leads(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "")).strip() for field in EXPECTED_COLUMNS})


def _slug(value: str) -> str:
    cleaned = value.strip().lower()
    token = "".join(char if char.isalnum() else "-" for char in cleaned)
    while "--" in token:
        token = token.replace("--", "-")
    return token.strip("-") or "unknown"


def _build_lead_id(
    *,
    company: str,
    source_url: str,
    title: str,
    location: str,
    query: str,
) -> str:
    if source_url:
        token = _slug(source_url)
        return f"glassdoor-{token}"

    fingerprint = "||".join([company, title, location, query])
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"glassdoor-{_slug(company)}-{digest}"


def _normalize_lead_type(title: str) -> str:
    return "job" if title.strip() else "company"


def _is_glassdoor_job_href(href: str) -> bool:
    lowered = href.strip().lower()
    return "glassdoor" in lowered and "/job-listing/" in lowered


def _is_noise_token(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    if lowered in {
        "easy apply",
        "most relevant",
        "show more jobs",
        "create job alert",
        "back to search",
        "loading...",
        "search",
        "for you",
    }:
        return True
    if lowered.endswith("d") or lowered.endswith("d+"):
        return lowered[:-1].isdigit() or lowered[:-2].isdigit()
    if "glassdoor est" in lowered or "employer provided" in lowered:
        return True
    if lowered.replace(".", "", 1).isdigit():
        return True
    return False


def _looks_like_location(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned or _is_noise_token(cleaned):
        return False
    if len(cleaned) > 80:
        return False
    return True


def _find_previous_company(tokens: list[dict[str, str]], start_index: int) -> str:
    for index in range(start_index - 1, max(-1, start_index - 8), -1):
        text = tokens[index].get("text", "").strip()
        if not text or _is_noise_token(text):
            continue
        if _looks_like_location(text) and len(text.split()) <= 6:
            return text
    return ""


def _find_next_location(tokens: list[dict[str, str]], start_index: int) -> str:
    for index in range(start_index + 1, min(len(tokens), start_index + 8)):
        text = tokens[index].get("text", "").strip()
        if not text or _is_noise_token(text):
            continue
        if _looks_like_location(text):
            return text
    return DEFAULT_LOCATION


def _discover_glassdoor_leads(max_results: int) -> list[dict[str, str]]:
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Tail'ed Community Company Discovery/1.0",
        "Referer": "https://www.glassdoor.ca/",
    }
    response = requests.get(DEFAULT_DISCOVERY_URL, headers=headers, timeout=25)
    response.raise_for_status()

    parser = _GlassdoorTokenParser()
    parser.feed(response.text)

    leads: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for index, token in enumerate(parser.tokens):
        href = token.get("href", "")
        title = token.get("text", "").strip()
        if not href or not title or not _is_glassdoor_job_href(href):
            continue
        if title.lower() in {"apply on employer site", "apply now"}:
            continue

        absolute_url = urljoin(DEFAULT_DISCOVERY_URL, href)
        normalized_href = normalize_url(absolute_url)
        if normalized_href in seen_urls:
            continue

        company = _find_previous_company(parser.tokens, index)
        if not company:
            continue

        location = _find_next_location(parser.tokens, index)
        seen_urls.add(normalized_href)
        leads.append(
            {
                "company": company,
                "url": normalized_href,
                "title": title,
                "location": location,
                "query": f"{DEFAULT_QUERY} {DEFAULT_LOCATION}",
                "native_url": "",
                "notes": "Auto-discovered from public Glassdoor Canada internship search.",
            }
        )
        if len(leads) >= max_results:
            break

    return leads


def _resolve_official_company_source(company: str, native_url: str) -> tuple[dict[str, Any] | None, str | None]:
    url = native_url.strip()
    if not url:
        return None, None

    try:
        config = build_company_config(company, normalize_url(url), enabled=True)
    except ValueError as error:
        return None, str(error)

    if config is None:
        return None, "unsupported official source URL"

    return config, None


def build_lead(
    row: dict[str, str],
    *,
    today: str,
    previous_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    company = row.get("company", "").strip()
    source_url = row.get("url", "").strip()
    title = row.get("title", "").strip()
    location = row.get("location", "").strip()
    query = row.get("query", "").strip()
    native_url = row.get("native_url", "").strip()
    notes = row.get("notes", "").strip()

    if not company:
        return None

    lead_id = _build_lead_id(
        company=company,
        source_url=source_url,
        title=title,
        location=location,
        query=query,
    )
    previous = previous_by_id.get(lead_id, {})
    first_seen_at = str(previous.get("first_seen_at", "")).strip() or today

    official_config, official_error = _resolve_official_company_source(company, native_url)
    official_source = str(official_config.get("source", "")).strip() if official_config else None
    official_source_url = str(official_config.get("url", "")).strip() if official_config else None
    promotion_ready = official_config is not None and official_source_url is not None

    return {
        "id": lead_id,
        "provider": "glassdoor",
        "lead_type": _normalize_lead_type(title),
        "company": company,
        "title": title or None,
        "location": location or None,
        "source_url": source_url or None,
        "query": query or None,
        "native_url": native_url or None,
        "notes": notes or None,
        "status": "needs_review",
        "official_source": official_source,
        "official_source_url": official_source_url,
        "promotion_ready": promotion_ready,
        "promotion_error": None if promotion_ready else official_error,
        "first_seen_at": first_seen_at,
        "last_seen_at": today,
    }


def sort_leads(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        leads,
        key=lambda item: (
            str(item.get("company", "")).casefold(),
            str(item.get("title", "") or "").casefold(),
            str(item.get("source_url", "") or "").casefold(),
        ),
    )


def promote_ready_company_sources(
    leads: list[dict[str, Any]],
    existing_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    promoted_count = 0
    cleaned_rows = [
        {
            "company": row.get("company", "").strip(),
            "url": normalize_url(row.get("url", "").strip()) if row.get("url", "").strip() else "",
            "enabled": row.get("enabled", "").strip().lower() or "true",
        }
        for row in existing_rows
    ]

    seen_urls: set[str] = {
        normalize_url(row["url"])
        for row in cleaned_rows
        if row.get("url", "").strip()
    }
    seen_company_sources: set[tuple[str, str]] = set()
    for row in cleaned_rows:
        company = row.get("company", "").strip()
        raw_url = row.get("url", "").strip()
        if not company or not raw_url:
            continue
        config = build_company_config(company, raw_url, enabled=True)
        if config is None:
            continue
        seen_company_sources.add(
            (company.casefold(), str(config.get("source", "")).strip().lower())
        )

    for lead in leads:
        if lead.get("promotion_ready") is not True:
            continue

        company = str(lead.get("company", "")).strip()
        source = str(lead.get("official_source", "")).strip().lower()
        official_source_url = str(lead.get("official_source_url", "")).strip()
        if not company or not source or not official_source_url:
            continue

        normalized_source_url = normalize_url(official_source_url)
        company_source_key = (company.casefold(), source)
        if normalized_source_url in seen_urls or company_source_key in seen_company_sources:
            continue

        cleaned_rows.append(
            {
                "company": company,
                "url": normalized_source_url,
                "enabled": "true",
            }
        )
        seen_urls.add(normalized_source_url)
        seen_company_sources.add(company_source_key)
        promoted_count += 1

    return cleaned_rows, promoted_count


def _build_lead_row_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("company", "").strip().casefold(),
        normalize_url(row.get("url", "").strip()) if row.get("url", "").strip() else "",
        row.get("title", "").strip().casefold(),
        row.get("location", "").strip().casefold(),
    )


def merge_discovered_rows(
    existing_rows: list[dict[str, str]],
    discovered_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    cleaned_rows = [{field: row.get(field, "").strip() for field in EXPECTED_COLUMNS} for row in existing_rows]
    seen_keys = {_build_lead_row_key(row) for row in cleaned_rows}
    added_count = 0

    for row in discovered_rows:
        cleaned_row = {field: row.get(field, "").strip() for field in EXPECTED_COLUMNS}
        row_key = _build_lead_row_key(cleaned_row)
        if row_key in seen_keys:
            continue
        cleaned_rows.append(cleaned_row)
        seen_keys.add(row_key)
        added_count += 1

    return cleaned_rows, added_count


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize Glassdoor discovery leads.")
    parser.add_argument(
        "--promote-ready",
        action="store_true",
        help="Promote resolvable official ATS URLs into data/company_sources.csv.",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip the built-in Glassdoor Canada internship discovery fetch.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help="Maximum number of public Glassdoor search results to append per run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    csv_path = repo_root / "data" / "glassdoor_leads.csv"
    output_path = repo_root / "data" / "company_leads.json"
    company_sources_path = repo_root / "data" / "company_sources.csv"

    source_rows = load_glassdoor_leads(csv_path)
    discovered_count = 0
    discovery_error: str | None = None
    if not args.skip_discovery:
        try:
            discovered_rows = _discover_glassdoor_leads(max(1, args.max_results))
            source_rows, discovered_count = merge_discovered_rows(source_rows, discovered_rows)
        except requests.RequestException as error:
            discovery_error = f"request failed ({error})"
            print(f"[warn] Glassdoor discovery {discovery_error}")
        except Exception as error:
            discovery_error = str(error)
            print(f"[warn] Glassdoor discovery failed ({error})")

    previous_output = load_json_list(output_path)
    previous_by_id = {
        str(item.get("id", "")).strip(): item
        for item in previous_output
        if str(item.get("id", "")).strip()
    }

    today = date.today().isoformat()
    cleaned_rows: list[dict[str, str]] = []
    leads: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    warned_count = 0
    skipped_count = 0

    for index, row in enumerate(source_rows, start=2):
        cleaned_row = {field: row.get(field, "").strip() for field in EXPECTED_COLUMNS}
        cleaned_rows.append(cleaned_row)

        if not cleaned_row["company"]:
            warned_count += 1
            print(f"[warn] Row {index}: missing company, skipping.")
            continue

        lead = build_lead(cleaned_row, today=today, previous_by_id=previous_by_id)
        if lead is None:
            warned_count += 1
            print(f"[warn] Row {index}: invalid lead, skipping.")
            continue

        lead_id = str(lead.get("id", "")).strip()
        if lead_id in seen_ids:
            warned_count += 1
            skipped_count += 1
            print(f"[warn] Row {index} ({cleaned_row['company']}): duplicate lead, skipping later row.")
            continue

        seen_ids.add(lead_id)
        leads.append(lead)

    sorted_leads = sort_leads(leads)
    save_glassdoor_leads(csv_path, cleaned_rows)
    save_json_list(output_path, sorted_leads)

    promoted_count = 0
    if args.promote_ready:
        existing_company_sources = load_company_sources(company_sources_path)
        promoted_rows, promoted_count = promote_ready_company_sources(
            sorted_leads,
            existing_company_sources,
        )
        save_company_sources(company_sources_path, promoted_rows)

    promotion_ready_count = sum(1 for lead in sorted_leads if lead.get("promotion_ready") is True)

    print("\nGlassdoor lead sync summary")
    print(f"- CSV rows processed: {len(source_rows)}")
    print(f"- Newly discovered leads appended: {discovered_count}")
    print(f"- Leads saved: {len(sorted_leads)}")
    print(f"- Promotion-ready leads: {promotion_ready_count}")
    if args.promote_ready:
        print(f"- Company sources promoted: {promoted_count}")
    print(f"- Skipped duplicates: {skipped_count}")
    print(f"- Warnings: {warned_count}")
    if discovery_error:
        print(f"- Discovery status: degraded ({discovery_error})")


if __name__ == "__main__":
    main()
