from __future__ import annotations

import csv
from pathlib import Path

from sync_companies import load_company_sources, save_company_sources
from sync_company_leads import (
    canonicalize_existing_source_identities,
    canonicalize_existing_source_urls,
)


def load_company_leads(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        expected_columns = [
            "company",
            "url",
            "source",
            "job_count",
            "example_job_url",
            "lead_source",
            "identity",
        ]
        if reader.fieldnames != expected_columns:
            raise ValueError(
                f"Expected CSV columns {expected_columns}, found {reader.fieldnames!r}."
            )

        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({key: (value or "").strip() for key, value in row.items()})
        return rows


def parse_identity(raw_identity: str) -> tuple[str, ...] | None:
    parts = [part.strip() for part in raw_identity.split("::")]
    cleaned = tuple(part for part in parts if part)
    if not cleaned:
        return None
    return cleaned


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    company_sources_path = repo_root / "data" / "company_sources.csv"
    company_leads_path = repo_root / "data" / "company_leads.csv"

    company_sources = load_company_sources(company_sources_path)
    company_leads = load_company_leads(company_leads_path)

    existing_urls = canonicalize_existing_source_urls(company_sources)
    existing_identities = canonicalize_existing_source_identities(company_sources)

    appended_count = 0
    skipped_url_count = 0
    skipped_identity_count = 0

    for lead in company_leads:
        company_name = str(lead.get("company", "")).strip()
        url = str(lead.get("url", "")).strip()
        identity = parse_identity(str(lead.get("identity", "")))

        if not company_name or not url:
            continue

        if identity is not None and identity in existing_identities:
            skipped_identity_count += 1
            continue

        if url in existing_urls:
            skipped_url_count += 1
            continue

        company_sources.append(
            {
                "company": company_name,
                "url": url,
                "enabled": "true",
            }
        )
        appended_count += 1
        existing_urls.add(url)
        if identity is not None:
            existing_identities.add(identity)

    save_company_sources(company_sources_path, company_sources)

    print("Company lead promotion summary")
    print(f"- Lead rows processed: {len(company_leads)}")
    print(f"- Appended to company_sources.csv: {appended_count}")
    print(f"- Skipped existing identities: {skipped_identity_count}")
    print(f"- Skipped existing URLs: {skipped_url_count}")
    print(f"- Output: {company_sources_path}")


if __name__ == "__main__":
    main()
