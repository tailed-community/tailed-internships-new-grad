from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlsplit, urlunsplit

import requests


OUTPUT_COLUMNS = [
    "company",
    "career_url",
    "discovered_from",
    "source_type",
    "existing_known_source",
    "reason",
    "enabled",
]
DUPLICATE_REPORT_COLUMNS = [
    "company",
    "host",
    "kept_url",
    "duplicate_url",
    "duplicate_reason",
    "discovered_from",
]
SUPPORTED_ATS = {
    "workday",
    "lever",
    "greenhouse",
    "ashby",
    "smartrecruiters",
    "icims",
    "jobvite",
    "bamboohr",
    "workable",
    "recruitee",
    "comeet",
    "oracle_hcm",
    "rippling",
}
REMOTE_ARCHIVE_URL = (
    "https://raw.githubusercontent.com/"
    "tailed-community/tech-internships-2025-2026/"
    "refs/heads/main/data/archived.json"
)
ATS_HOSTS = {
    "workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "lever": ("lever.co",),
    "greenhouse": ("greenhouse.io",),
    "ashby": ("ashbyhq.com",),
    "smartrecruiters": ("smartrecruiters.com",),
    "icims": ("icims.com", "jibeapply.com"),
    "jobvite": ("jobvite.com",),
    "bamboohr": ("bamboohr.com",),
    "workable": ("workable.com",),
    "recruitee": ("recruitee.com",),
    "comeet": ("comeet.com",),
    "oracle_hcm": ("oraclecloud.com",),
    "rippling": ("ats.rippling.com",),
}
UNSUPPORTED_ATS_HOSTS = {
    "breezyhr": ("breezy.hr",),
    "phenom": ("phenompeople.com",),
    "jazzhr": ("jazzhr.com", "applytojob.com"),
}
CAREER_HINTS = ("career", "careers", "job", "jobs", "position", "positions", "opening")
URL_PATTERN = re.compile(r"https?://[^\s\"'<>|\])]+", re.IGNORECASE)
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
COMPANY_FIELDS = ("company", "company_name", "employer", "organization", "name")
URL_FIELDS = (
    "career_url",
    "careers_url",
    "jobs_url",
    "job_url",
    "apply_url",
    "example_job_url",
    "url",
)
GENERATED_OUTPUT_FILES = {
    "custom_ats_candidates.csv",
    "custom_ats_promotion_review.csv",
    "custom_company_duplicates.csv",
    "custom_companies_discovered.csv",
}


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_company(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", clean_text(value).casefold())


def normalize_url(value: str) -> str:
    parsed = urlsplit(clean_text(value).rstrip(".,;"))
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, "")
    )


def ats_source_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    host = host[4:] if host.startswith("www.") else host
    for source, suffixes in ATS_HOSTS.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return source
    return ""


def unsupported_ats_source_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    host = host[4:] if host.startswith("www.") else host
    for source, suffixes in UNSUPPORTED_ATS_HOSTS.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return source
    return ""


def looks_like_career_url(url: str) -> bool:
    parsed = urlsplit(url)
    text = f"{parsed.hostname or ''} {parsed.path} {parsed.query}".casefold()
    return any(hint in text for hint in CAREER_HINTS)


def career_page_from_url(url: str) -> str:
    normalized = normalize_url(url)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    segments = [segment for segment in parsed.path.split("/") if segment]
    lowered = [segment.casefold() for segment in segments]
    query = parsed.query.casefold()

    for marker in (
        "careers",
        "career",
        "jobs",
        "job",
        "positions",
        "position",
        "openings",
        "opening",
    ):
        if marker in lowered:
            index = lowered.index(marker)
            keep = index + 1
            if keep < len(segments):
                next_segment = lowered[keep]
                if next_segment in {"search", "all", "open", "openings", "positions"}:
                    keep += 1
            path = "/" + "/".join(segments[:keep])
            return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    if any(key in query for key in ("gh_jid=", "job_id=", "jobid=", "reqid=")):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return normalized


def source_label(path: Path, row: dict[str, object] | None = None) -> str:
    text = f"{path.as_posix()} {json.dumps(row or {}, default=str)}".casefold()
    if path.name.casefold() == "custom_companies.csv":
        return "manual_custom_companies"
    if "simplify" in text:
        return "simplify"
    if "archive" in text or "archived" in text:
        return "tailed_archive"
    return "existing_data"


def _dict_records(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dict_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dict_records(child)


def _records_from_csv(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as file:
        yield from csv.DictReader(file)


def _records_from_json(path: Path) -> Iterator[dict[str, object]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return
    yield from _dict_records(value)


def _records_from_markdown(path: Path) -> Iterator[dict[str, object]]:
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if "|" not in line:
            continue
        cells = [clean_text(cell) for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        for _label, url in MARKDOWN_LINK_PATTERN.findall(line):
            yield {"company": cells[0], "url": url}


def iter_source_records(path: Path) -> Iterator[dict[str, object]]:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        yield from _records_from_csv(path)
    elif suffix == ".json":
        yield from _records_from_json(path)
    elif suffix in {".md", ".markdown"}:
        yield from _records_from_markdown(path)


def fetch_remote_archive_records(
    url: str = REMOTE_ARCHIVE_URL,
    *,
    requester: object = requests.get,
) -> list[dict[str, object]]:
    response = requester(url, timeout=90)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list from {url!r}.")
    return [record for record in payload if isinstance(record, dict)]


def record_company(record: dict[str, object]) -> str:
    lowered = {clean_text(key).casefold(): value for key, value in record.items()}
    for field in COMPANY_FIELDS:
        value = clean_text(lowered.get(field, ""))
        if value:
            return value
    return ""


def record_urls(record: dict[str, object]) -> Iterator[str]:
    lowered = {clean_text(key).casefold(): value for key, value in record.items()}
    seen: set[str] = set()
    for field in URL_FIELDS:
        value = lowered.get(field)
        if isinstance(value, str):
            candidates = URL_PATTERN.findall(value)
            if value.startswith(("http://", "https://")):
                candidates.insert(0, value)
            for candidate in candidates:
                normalized = normalize_url(candidate)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    yield normalized


def find_source_files(repo_root: Path) -> list[Path]:
    files: set[Path] = set()
    for relative_root in ("data", "scripts", "archive", "generated"):
        root = repo_root / relative_root
        if not root.exists():
            continue
        for pattern in ("*.csv", "*.json", "*.md", "*.markdown"):
            files.update(root.rglob(pattern))
    return sorted(
        path
        for path in files
        if path.name.casefold() not in GENERATED_OUTPUT_FILES
    )


def load_known_sources(
    paths: Iterable[Path],
) -> tuple[set[str], dict[str, set[str]]]:
    known_urls: set[str] = set()
    company_sources: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        for record in iter_source_records(path):
            company = record_company(record)
            declared_source = clean_text(record.get("source", "")).casefold()
            for url in record_urls(record):
                detected_source = ats_source_for_url(url)
                source = detected_source or declared_source
                if source in SUPPORTED_ATS:
                    known_urls.add(normalize_url(url))
                    if company:
                        company_sources[normalize_company(company)].add(source)
    return known_urls, company_sources


def _source_type(url: str) -> str:
    if unsupported_ats_source_for_url(url):
        return "unsupported_url"
    if "gh_jid=" in url.casefold():
        return "branded_ats_page"
    return "custom_career_page" if looks_like_career_url(url) else "unknown_career_page"


def _candidate_from_record(
    record: dict[str, object],
    origin: str,
    known_urls: set[str],
    company_sources: dict[str, set[str]],
) -> Iterator[dict[str, str]]:
    company = record_company(record)
    if not company:
        return
    for raw_url in record_urls(record):
        if ats_source_for_url(raw_url) in SUPPORTED_ATS:
            continue
        career_url = career_page_from_url(raw_url)
        if (
            not career_url
            or normalize_url(raw_url) in known_urls
            or not looks_like_career_url(career_url)
        ):
            continue
        source_type = _source_type(raw_url)
        reason = {
            "manual_custom_companies": "not_in_existing_ats_sources",
            "simplify": "company_career_url_from_simplify",
            "tailed_archive": "found_in_archive",
        }.get(origin, "likely_custom_or_branded_ats")
        if source_type == "unsupported_url":
            reason = f"unsupported_{unsupported_ats_source_for_url(raw_url)}_url"
        yield {
            "company": company,
            "career_url": career_url,
            "discovered_from": origin,
            "source_type": source_type,
            "existing_known_source": ";".join(
                sorted(company_sources.get(normalize_company(company), set()))
            ),
            "reason": reason,
            "enabled": "true",
        }


def discover_candidates(
    repo_root: Path,
    source_paths: Iterable[Path] | None = None,
    *,
    remote_archive_records: Iterable[dict[str, object]] | None = None,
) -> list[dict[str, str]]:
    paths = list(source_paths) if source_paths is not None else find_source_files(repo_root)
    known_urls, company_sources = load_known_sources(paths)
    candidates: list[dict[str, str]] = []

    for path in paths:
        for record in iter_source_records(path):
            origin = source_label(path, record)
            candidates.extend(
                _candidate_from_record(record, origin, known_urls, company_sources)
            )
    for record in remote_archive_records or ():
        candidates.extend(
            _candidate_from_record(
                record,
                "tailed_archive",
                known_urls,
                company_sources,
            )
        )
    return deduplicate_candidates(candidates)


def _url_quality(row: dict[str, str]) -> tuple[int, int, int]:
    url = row["career_url"]
    parsed = urlsplit(url)
    return (
        1 if "manual_custom_companies" in row["discovered_from"].split(";") else 0,
        1 if not parsed.query else 0,
        -len([segment for segment in parsed.path.split("/") if segment]),
    )


def _normalized_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _platform_group_key(url: str) -> tuple[str, ...]:
    parsed = urlsplit(url)
    host = _normalized_host(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    lowered = [segment.casefold() for segment in segments]

    if host.endswith(".taleo.net") and "careersection" in lowered:
        index = lowered.index("careersection")
        section = lowered[index + 1] if index + 1 < len(lowered) else ""
        return host, "taleo", section
    if "ultipro." in host and "jobboard" in lowered:
        index = lowered.index("jobboard")
        tenant = lowered[0] if lowered else ""
        board = lowered[index + 1] if index + 1 < len(lowered) else ""
        return host, "ultipro", tenant, board
    if host.endswith(".applytojob.com"):
        return host, "jazzhr"
    if host == "app.careerpuck.com" and "job-board" in lowered:
        index = lowered.index("job-board")
        board = lowered[index + 1] if index + 1 < len(lowered) else ""
        return host, "careerpuck", board
    return host, "company_host"


def _canonical_group_url(url: str) -> str:
    parsed = urlsplit(url)
    host = _normalized_host(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    lowered = [segment.casefold() for segment in segments]
    netloc = parsed.netloc

    if host.endswith(".taleo.net") and "careersection" in lowered:
        index = lowered.index("careersection")
        if index + 1 < len(segments):
            path = "/" + "/".join(segments[: index + 2]) + "/jobsearch.ftl"
            return urlunsplit((parsed.scheme, netloc, path, "", ""))
    if "ultipro." in host and "jobboard" in lowered:
        index = lowered.index("jobboard")
        if index + 1 < len(segments):
            path = "/" + "/".join(segments[: index + 2])
            return urlunsplit((parsed.scheme, netloc, path, "", ""))
    if host.endswith(".applytojob.com"):
        return urlunsplit((parsed.scheme, netloc, "/apply", "", ""))
    if host == "app.careerpuck.com" and "job-board" in lowered:
        index = lowered.index("job-board")
        if index + 1 < len(segments):
            path = "/" + "/".join(segments[: index + 2])
            return urlunsplit((parsed.scheme, netloc, path, "", ""))
    return normalize_url(url)


def _merge_traceability(existing: dict[str, str], incoming: dict[str, str]) -> None:
    origins = set(existing["discovered_from"].split(";"))
    origins.update(incoming["discovered_from"].split(";"))
    reasons = set(existing["reason"].split(";"))
    reasons.update(incoming["reason"].split(";"))
    sources = set(existing["existing_known_source"].split(";"))
    sources.update(incoming["existing_known_source"].split(";"))
    sources.discard("")
    existing["discovered_from"] = ";".join(sorted(origins))
    existing["reason"] = ";".join(sorted(reason for reason in reasons if reason))
    existing["existing_known_source"] = ";".join(sorted(sources))


def deduplicate_candidates_with_report(
    rows: Iterable[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_identity: dict[tuple[str, str], dict[str, str]] = {}
    for incoming in rows:
        company_key = normalize_company(incoming["company"])
        url_key = normalize_url(incoming["career_url"])
        if not company_key or not url_key:
            continue
        identity = (company_key, url_key)
        existing = by_identity.get(identity)
        if existing is None:
            by_identity[identity] = dict(incoming)
            continue
        _merge_traceability(existing, incoming)

    grouped: dict[tuple[str, tuple[str, ...]], list[dict[str, str]]] = defaultdict(list)
    for row in by_identity.values():
        grouped[
            (
                normalize_company(row["company"]),
                _platform_group_key(row["career_url"]),
            )
        ].append(row)

    deduplicated: list[dict[str, str]] = []
    duplicate_report: list[dict[str, str]] = []
    for group_rows in grouped.values():
        selected = max(group_rows, key=_url_quality)
        kept = dict(selected)
        kept["career_url"] = _canonical_group_url(kept["career_url"])
        for row in group_rows:
            _merge_traceability(kept, row)
            if row is selected:
                continue
            duplicate_report.append(
                {
                    "company": row["company"],
                    "host": _normalized_host(row["career_url"]),
                    "kept_url": kept["career_url"],
                    "duplicate_url": row["career_url"],
                    "duplicate_reason": "same_normalized_company_and_career_host",
                    "discovered_from": row["discovered_from"],
                }
            )
        collapsed_count = len(group_rows) - 1
        if collapsed_count:
            reasons = set(kept["reason"].split(";"))
            reasons.add(f"collapsed_{collapsed_count}_duplicate_urls")
            kept["reason"] = ";".join(sorted(reason for reason in reasons if reason))
        deduplicated.append(kept)

    return sorted(
        deduplicated,
        key=lambda row: (row["company"].casefold(), row["career_url"]),
    ), sorted(
        duplicate_report,
        key=lambda row: (
            row["company"].casefold(),
            row["host"],
            row["duplicate_url"],
        ),
    )


def deduplicate_candidates(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    deduplicated, _report = deduplicate_candidates_with_report(rows)
    return deduplicated


def write_discovered_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in OUTPUT_COLUMNS} for row in rows)


def write_duplicate_report(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=DUPLICATE_REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in DUPLICATE_REPORT_COLUMNS}
            for row in rows
        )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Discover custom company career pages from repository data.")
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "data" / "custom_companies_discovered.csv",
    )
    parser.add_argument(
        "--archive-url",
        default=REMOTE_ARCHIVE_URL,
        help="Remote Tail'ed archived jobs JSON to include.",
    )
    parser.add_argument(
        "--no-remote-archive",
        action="store_true",
        help="Use repository files only.",
    )
    parser.add_argument(
        "--duplicates-output",
        type=Path,
        default=repo_root / "data" / "custom_company_duplicates.csv",
    )
    args = parser.parse_args()
    remote_records = (
        []
        if args.no_remote_archive
        else fetch_remote_archive_records(args.archive_url)
    )
    paths = find_source_files(repo_root)
    known_urls, company_sources = load_known_sources(paths)
    candidates: list[dict[str, str]] = []
    for path in paths:
        for record in iter_source_records(path):
            candidates.extend(
                _candidate_from_record(
                    record,
                    source_label(path, record),
                    known_urls,
                    company_sources,
                )
            )
    for record in remote_records:
        candidates.extend(
            _candidate_from_record(
                record,
                "tailed_archive",
                known_urls,
                company_sources,
            )
        )
    rows, duplicates = deduplicate_candidates_with_report(candidates)
    write_discovered_csv(args.output, rows)
    write_duplicate_report(args.duplicates_output, duplicates)
    print(f"Wrote {len(rows)} custom career-page candidates to {args.output}")
    print(
        f"Collapsed {len(duplicates)} duplicate URLs; "
        f"audit report: {args.duplicates_output}"
    )


if __name__ == "__main__":
    main()
