from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from sync_companies import (
    build_company_config,
    load_company_sources,
    normalize_url,
    save_company_sources,
)


PRODUCTION_SOURCES = {
    "ashby",
    "greenhouse",
    "icims",
    "lever",
    "oracle_hcm",
    "rippling",
    "smartrecruiters",
    "workable",
    "workday",
}
TRUE_VALUES = {"1", "true", "yes"}
REVIEW_COLUMNS = [
    "company",
    "detected_source",
    "candidate_url",
    "canonical_source_url",
    "status",
    "reason",
]


def load_candidates(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


def config_identity(config: dict[str, Any]) -> tuple[str, ...]:
    source = str(config.get("source", "")).casefold()
    if source == "workday":
        return source, str(config.get("tenant", "")).casefold(), str(config.get("site", "")).casefold()
    if source in {"ashby", "greenhouse", "lever", "rippling", "smartrecruiters", "workable"}:
        return source, str(config.get("slug", "")).casefold()
    if source == "icims":
        return source, str(config.get("mode", "")).casefold(), str(config.get("host", "")).casefold()
    if source == "oracle_hcm":
        return (
            source,
            str(config.get("host", "")).casefold(),
            str(config.get("language", "")).casefold(),
            str(config.get("site", "")).casefold(),
        )
    return source, normalize_url(str(config.get("url", "")))


def _contains_template(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in ("{{", "}}", "${", "<%", "%3c", "%7b"))


def _is_public_icims_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    if not host or host in {"icims.com", "www.icims.com", "login.icims.com"}:
        return False
    if ".staging." in host or host.endswith(".staging.jibeapply.com"):
        return False
    first_label = host.split(".", 1)[0]
    blocked_prefixes = (
        "employee",
        "employees",
        "internal",
        "globalemployee",
        "globalemployees",
    )
    return not first_label.startswith(blocked_prefixes)


def _is_public_oracle_hcm_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    first_label = host.split(".", 1)[0]
    return bool(host) and not any(
        marker in first_label for marker in ("dev", "stage", "staging", "test")
    )


def _candidate_urls(row: dict[str, str]) -> list[str]:
    source = row.get("detected_source", "").casefold()
    values = [
        row.get("best_evidence_url", ""),
        row.get("canonical_source_url", ""),
    ]
    if source in {"greenhouse", "lever", "ashby", "smartrecruiters"}:
        values.reverse()
    urls: list[str] = []
    for value in values:
        normalized = normalize_url(value) if value else ""
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls


def _normalize_workday_candidate(row: dict[str, str], url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if "myworkdayjobs.com" not in host:
        return ""
    segments = [segment for segment in parsed.path.split("/") if segment]
    lowered = [segment.casefold().rstrip("&") for segment in segments]
    rejected_segments = {
        "asset",
        "assets",
        "candidate-experience-jobs",
        "client-analytics",
        "introduceyourself",
        "login",
        "logo",
        "jobs",
        "uic-shared-vendors",
        "userhome",
    }
    if any(segment in rejected_segments for segment in lowered):
        return ""
    for marker in ("job", "details"):
        if marker in lowered:
            segments = segments[: lowered.index(marker)]
            lowered = lowered[: lowered.index(marker)]
            break
    if lowered and lowered[-1] == "jobs":
        segments = segments[:-1]
        lowered = lowered[:-1]
    if not segments or any("&" in segment for segment in segments):
        return ""

    source_key = row.get("source_key", "")
    _tenant, separator, source_site = source_key.partition(":")
    bad_site = source_site.casefold() in rejected_segments or not separator
    if bad_site:
        return ""
    if lowered[-1] != source_site.casefold():
        matching_indexes = [
            index for index, segment in enumerate(lowered)
            if segment == source_site.casefold()
        ]
        if not matching_indexes:
            return ""
        segments = segments[: matching_indexes[-1] + 1]
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{'/'.join(segments)}", "", ""))


def validate_candidate(row: dict[str, str]) -> tuple[dict[str, Any] | None, str, str]:
    company = row.get("company", "").strip()
    source = row.get("detected_source", "").casefold()
    if not company or source not in PRODUCTION_SOURCES:
        return None, "", "not_a_supported_production_source"
    if row.get("route_ready", "").casefold() not in TRUE_VALUES:
        return None, "", "candidate_is_not_route_ready"

    errors: list[str] = []
    for url in _candidate_urls(row):
        if source == "workday":
            url = _normalize_workday_candidate(row, url)
            if not url:
                errors.append("invalid_workday_site_url")
                continue
        if source == "icims" and not _is_public_icims_url(url):
            errors.append("non_public_icims_url")
            continue
        if source == "oracle_hcm" and not _is_public_oracle_hcm_url(url):
            errors.append("non_public_oracle_hcm_url")
            continue
        if _contains_template(url):
            errors.append("templated_url")
            continue
        try:
            config = build_company_config(company, url, enabled=True)
        except ValueError as error:
            errors.append(str(error))
            continue
        if config is None:
            errors.append("unsupported_url_shape")
            continue
        configured_source = str(config.get("source", "")).casefold()
        if configured_source != source:
            errors.append(f"source_mismatch:{configured_source}")
            continue
        return config, url, ""
    return None, "", "; ".join(dict.fromkeys(errors)) or "no_candidate_url"


def build_promotion(
    candidates: Iterable[dict[str, str]],
    existing_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    existing_identities: set[tuple[str, ...]] = set()
    existing_urls: set[str] = set()
    for row in existing_rows:
        company = row.get("company", "").strip()
        url = row.get("url", "").strip()
        if not company or not url:
            continue
        existing_urls.add(normalize_url(url))
        try:
            config = build_company_config(company, url, enabled=True)
        except ValueError:
            continue
        if config:
            existing_identities.add(config_identity(config))

    additions: list[dict[str, str]] = []
    review: list[dict[str, str]] = []
    for row in candidates:
        config, candidate_url, rejection = validate_candidate(row)
        review_row = {
            "company": row.get("company", ""),
            "detected_source": row.get("detected_source", ""),
            "candidate_url": candidate_url,
            "canonical_source_url": "",
            "status": "rejected",
            "reason": rejection,
        }
        if config is None:
            review.append(review_row)
            continue

        canonical_url = normalize_url(str(config.get("url", "")))
        identity = config_identity(config)
        review_row["canonical_source_url"] = canonical_url
        if canonical_url in existing_urls:
            review_row.update(status="skipped", reason="existing_url")
        elif identity in existing_identities:
            review_row.update(status="skipped", reason="existing_source_identity")
        else:
            additions.append(
                {
                    "company": str(config.get("company", row.get("company", ""))),
                    "url": canonical_url,
                    "enabled": "true",
                }
            )
            existing_urls.add(canonical_url)
            existing_identities.add(identity)
            review_row.update(status="accepted", reason="")
        review.append(review_row)
    return additions, review


def write_review(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in REVIEW_COLUMNS} for row in rows)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate and promote route-ready custom ATS candidates into the production source workflow."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=repo_root / "data" / "custom_ats_candidates.csv",
    )
    parser.add_argument(
        "--company-sources",
        type=Path,
        default=repo_root / "data" / "company_sources.csv",
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=repo_root / "data" / "custom_ats_promotion_review.csv",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Append accepted candidates to data/company_sources.csv.",
    )
    args = parser.parse_args()

    candidates = load_candidates(args.input)
    company_sources = load_company_sources(args.company_sources)
    additions, review = build_promotion(candidates, company_sources)
    write_review(args.review_output, review)
    if args.apply and additions:
        save_company_sources(args.company_sources, [*company_sources, *additions])

    accepted = sum(row["status"] == "accepted" for row in review)
    skipped = sum(row["status"] == "skipped" for row in review)
    rejected = sum(row["status"] == "rejected" for row in review)
    print("Custom ATS promotion summary")
    print(f"- Candidate rows reviewed: {len(review)}")
    print(f"- Accepted new sources: {accepted}")
    print(f"- Already covered: {skipped}")
    print(f"- Rejected or unsupported: {rejected}")
    print(f"- Review report: {args.review_output}")
    print(
        f"- company_sources.csv: {'updated' if args.apply else 'not changed (dry run)'}"
    )


if __name__ == "__main__":
    main()
