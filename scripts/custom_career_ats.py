from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


MAX_DEPTH = 1
MAX_PAGES_PER_COMPANY = 8
DISCOVERY_HINTS = (
    "career",
    "careers",
    "job",
    "jobs",
    "opening",
    "openings",
    "position",
    "positions",
    "engineering",
    "technology",
    "software",
    "security",
    "intern",
    "student",
    "graduate",
    "new-grad",
)
STRONG_DISCOVERY_HINTS = (
    "job",
    "jobs",
    "opening",
    "openings",
    "position",
    "positions",
)
SKIP_LINK_HINTS = (
    "login",
    "log-in",
    "signin",
    "sign-in",
    "privacy",
    "legal",
    "terms",
    "cookie",
    "blog",
    "news",
    "press",
)
SOFT_SKIP_LINK_HINTS = ("benefit", "culture", "team", "life-at", "life at")
SOCIAL_HOSTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)
SKIP_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".zip",
)
ATS_HOST_PATTERNS = {
    "greenhouse": ("greenhouse.io",),
    "lever": ("lever.co",),
    "workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "ashby": ("ashbyhq.com",),
    "smartrecruiters": ("smartrecruiters.com",),
    "bamboohr": ("bamboohr.com",),
    "icims": ("icims.com", "jibeapply.com"),
    "jobvite": ("jobvite.com",),
    "phenom": ("phenompeople.com",),
    "jazzhr": ("jazzhr.com", "applytojob.com"),
    "recruitee": ("recruitee.com",),
    "comeet": ("comeet.com",),
    "breezyhr": ("breezy.hr",),
    "workable": ("workable.com",),
    "oracle_hcm": ("oraclecloud.com",),
    "rippling": ("ats.rippling.com",),
}
URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+", flags=re.IGNORECASE)
QUOTED_PATH_PATTERN = re.compile(
    r"""["']((?:/|\.\.?/)[^"'<>\\\s]+)["']""",
    flags=re.IGNORECASE,
)
ROLE_TITLE_PATTERN = re.compile(
    r"\b(intern|graduate|developer|engineer|scientist|analyst|architect|"
    r"designer|administrator|specialist|coordinator|researcher|manager|"
    r"consultant|technician|programmer|product owner)\b",
    flags=re.IGNORECASE,
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchResult:
    html: str
    final_url: str
    status_code: int


@dataclass(frozen=True)
class DiscoveredPage:
    original_url: str
    fetch_url: str
    link_text: str
    score: int


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_http_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def _normalized_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def normalize_page_url(url: str) -> str:
    parsed = urlsplit(clean_text(url))
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            parsed.query,
            "",
        )
    )


def detect_ats(url: str) -> str:
    host = _normalized_host(url)
    for name, patterns in ATS_HOST_PATTERNS.items():
        if any(host == pattern or host.endswith(f".{pattern}") for pattern in patterns):
            return name
    return ""


def _is_static_asset_url(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(
        path.endswith(extension)
        for extension in (
            *SKIP_EXTENSIONS,
            ".css",
            ".js",
            ".map",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".mp4",
            ".webm",
        )
    )


def _has_nonempty_gh_jid(url: str) -> bool:
    return bool(re.search(r"(?:^|&)gh_jid=[^&]+", urlsplit(url).query, re.IGNORECASE))


def _is_noisy_greenhouse_internal_url(url: str) -> bool:
    parsed = urlsplit(url)
    if not _normalized_host(url).endswith(".greenhouse.io"):
        return False
    path = parsed.path.casefold()
    return (
        path == "/jobapp"
        or path.endswith("/jobapp")
        or "/plans/" in path
        or "/approvals/" in path
        or any(
            marker in path
            for marker in ("/admin/", "/internal/", "/users/sign_in", "/dashboard/")
        )
    )


def _is_real_ats_evidence(source: str, url: str) -> bool:
    parsed = urlsplit(url)
    lowered = url.casefold()
    if _is_static_asset_url(url):
        return False
    if "gh_jid=" in lowered and not _has_nonempty_gh_jid(url):
        return False
    if _has_nonempty_gh_jid(url):
        return True
    if source == "phenom":
        return any(
            hint in lowered
            for hint in (
                "/api/",
                "/search",
                "/jobs",
                "/job/",
                "jobsearch",
                "requisition",
            )
        )
    if source == "bamboohr":
        return "/careers" in parsed.path.casefold()
    if source == "workday":
        path = parsed.path.casefold()
        if any(
            marker in path
            for marker in (
                "/assets/",
                "/login",
                "/introduceyourself",
                "/userhome",
                "/wday/asset/",
            )
        ):
            return False
    return bool(source)


def _extract_embedded_urls(base_url: str, text: str) -> list[str]:
    urls: set[str] = set()
    decoded = text.replace("\\/", "/").replace("\\u002F", "/")
    for match in URL_PATTERN.findall(decoded):
        urls.add(match.rstrip(".,;"))
    for path in QUOTED_PATH_PATTERN.findall(decoded):
        absolute = urljoin(base_url, path)
        if _is_http_url(absolute):
            urls.add(absolute)
    return sorted(urls)


def detect_ats_from_html(
    company: str,
    source_url: str,
    html: str,
) -> list[dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    detections: dict[tuple[str, str], dict[str, object]] = {}

    def add(url: str, method: str, confidence: str, notes: str = "") -> None:
        normalized_url = normalize_page_url(url)
        source = detect_ats(normalized_url)
        if not source and "gh_jid=" in normalized_url.casefold():
            source = "greenhouse"
            confidence = "medium"
            notes = notes or "Greenhouse job identifier found in URL"
        if not source or not _is_real_ats_evidence(source, normalized_url):
            return
        key = (source, normalized_url)
        candidate = {
            "company": company,
            "source_page": source_url,
            "detected_source": source,
            "detected_url": normalized_url,
            "detection_method": method,
            "confidence": confidence,
            "notes": notes,
        }
        existing = detections.get(key)
        rank = {"low": 1, "medium": 2, "high": 3}
        if existing is None or rank[confidence] > rank[str(existing["confidence"])]:
            detections[key] = candidate

    attribute_map = {
        "a": ("href", "link"),
        "script": ("src", "script_src"),
        "iframe": ("src", "iframe"),
        "form": ("action", "form_action"),
    }
    for tag_name, (attribute, method) in attribute_map.items():
        for tag in soup.find_all(tag_name):
            value = clean_text(str(tag.get(attribute, "")))
            if value:
                add(urljoin(source_url, value), method, "high")

    for script in soup.find_all("script"):
        text = script.string or script.get_text(" ", strip=False)
        for url in _extract_embedded_urls(source_url, text):
            add(url, "inline_script", "medium")

    for url in _extract_embedded_urls(source_url, html):
        add(url, "embedded_url", "medium")

    return sorted(
        detections.values(),
        key=lambda row: (
            str(row["detected_source"]),
            str(row["detected_url"]),
        ),
    )


def _ats_source_key(source: str, url: str) -> str:
    parsed = urlsplit(url)
    host = _normalized_host(url)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    lowered_segments = [segment.casefold() for segment in segments]

    if source == "greenhouse":
        query_match = re.search(r"(?:^|&)for=([^&]+)", parsed.query, flags=re.IGNORECASE)
        if query_match:
            return unquote(query_match.group(1)).strip().casefold()
        if "boards" in lowered_segments:
            index = lowered_segments.index("boards")
            if index + 1 < len(segments):
                return segments[index + 1].strip().casefold()
        if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and segments:
            if segments[0].casefold() != "embed":
                return segments[0].strip().casefold()

    if source == "lever":
        if host in {"jobs.lever.co", "jobs.eu.lever.co"} and segments:
            return segments[0].strip().casefold()
        if host == "api.lever.co" and len(segments) >= 3:
            if lowered_segments[:2] == ["v0", "postings"]:
                return segments[2].strip().casefold()

    if source == "ashby":
        if host == "jobs.ashbyhq.com" and segments:
            return segments[0].strip().casefold()
        if host == "api.ashbyhq.com" and "job-board" in lowered_segments:
            index = lowered_segments.index("job-board")
            if index + 1 < len(segments):
                return segments[index + 1].strip().casefold()

    if source == "smartrecruiters":
        if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"} and segments:
            if lowered_segments[0] == "oneclick-ui" and "company" in lowered_segments:
                index = lowered_segments.index("company")
                if index + 1 < len(segments):
                    return segments[index + 1].strip().casefold()
            return segments[0].strip().casefold()
        if "companies" in lowered_segments:
            index = lowered_segments.index("companies")
            if index + 1 < len(segments):
                return segments[index + 1].strip().casefold()

    if source == "workable":
        if host == "apply.workable.com" and segments:
            if lowered_segments[:3] == ["api", "v3", "accounts"] and len(segments) >= 4:
                return segments[3].strip().casefold()
            if lowered_segments[0] != "api":
                return segments[0].strip().casefold()

    if source == "recruitee" and host.endswith(".recruitee.com"):
        prefix = host.removesuffix(".recruitee.com")
        if prefix not in {"www", "careers"}:
            return prefix

    if source == "breezyhr" and host.endswith(".breezy.hr"):
        return host.removesuffix(".breezy.hr")

    if source == "bamboohr" and host.endswith(".bamboohr.com"):
        return host.removesuffix(".bamboohr.com")

    if source == "comeet":
        if "company" in parsed.query.casefold():
            match = re.search(r"(?:company|company_uid)=([^&]+)", parsed.query, re.IGNORECASE)
            if match:
                return unquote(match.group(1)).strip().casefold()
        if "jobs" in lowered_segments:
            index = lowered_segments.index("jobs")
            if index + 1 < len(segments):
                return segments[index + 1].strip().casefold()

    if source == "icims":
        if host.endswith(".icims.com") or host.endswith(".jibeapply.com"):
            return host

    if source == "workday":
        if host.endswith(".myworkdayjobs.com") or host.endswith(".myworkdaysite.com"):
            tenant = host.split(".", 1)[0]
            canonical_segments = segments
            for index, segment in enumerate(lowered_segments):
                if segment in {"job", "details"}:
                    canonical_segments = segments[:index]
                    break
            site = canonical_segments[-1] if canonical_segments else ""
            return f"{tenant}:{site.casefold()}" if site else tenant

    if source == "oracle_hcm":
        if host.endswith(".oraclecloud.com"):
            if "candidateexperience" in lowered_segments and "sites" in lowered_segments:
                sites_index = lowered_segments.index("sites")
                if sites_index + 1 < len(segments):
                    site = segments[sites_index + 1].strip()
                    candidate_index = lowered_segments.index("candidateexperience")
                    language = (
                        segments[candidate_index + 1].strip()
                        if candidate_index + 1 < len(segments)
                        else "en"
                    )
                    return f"{host}:{language}:{site}"

    if source == "rippling" and host == "ats.rippling.com":
        if len(segments) >= 2 and lowered_segments[1] == "jobs":
            return segments[0].strip()
        if len(segments) >= 3 and lowered_segments[2] == "jobs":
            return segments[1].strip()

    return ""


def _slugify_source_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _infer_branded_greenhouse_source_key(
    company: str,
    original_url: str,
    evidence_rows: list[dict[str, object]],
) -> str:
    gh_jid_rows = [
        row
        for row in evidence_rows
        if str(row.get("detected_source", "")) == "greenhouse"
        and _has_nonempty_gh_jid(str(row.get("detected_url", "")))
    ]
    if not gh_jid_rows:
        return ""

    original_host = _normalized_host(original_url)
    branded_hosts = {
        _normalized_host(str(row.get("detected_url", ""))) for row in gh_jid_rows
    }
    branded_hosts.discard("")
    if len(branded_hosts) != 1 or original_host not in branded_hosts:
        return ""

    host_brand = original_host.removeprefix("www.").split(".", 1)[0]
    company_key = _slugify_source_key(company)
    host_key = _slugify_source_key(host_brand)
    if not company_key or company_key != host_key:
        return ""

    if not all(
        any(
            marker in urlsplit(str(row.get("detected_url", ""))).path.casefold()
            for marker in ("/job", "/jobs", "/career", "/careers", "/apply")
        )
        for row in gh_jid_rows
    ):
        return ""
    return company_key


def _canonical_ats_url(source: str, source_key: str, evidence_url: str) -> str:
    if source == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{source_key}/jobs"
    if source == "lever":
        return f"https://api.lever.co/v0/postings/{source_key}?mode=json"
    if source == "ashby":
        return (
            "https://api.ashbyhq.com/posting-api/job-board/"
            f"{quote(source_key, safe='')}?includeCompensation=false"
        )
    if source == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{source_key}/postings"
    if source == "workable":
        return f"https://apply.workable.com/api/v3/accounts/{source_key}/jobs"
    if source == "recruitee":
        return f"https://{source_key}.recruitee.com"
    if source == "breezyhr":
        return f"https://{source_key}.breezy.hr"
    if source == "bamboohr":
        return f"https://{source_key}.bamboohr.com/careers"
    if source == "workday":
        tenant, _, site = source_key.partition(":")
        host = _normalized_host(evidence_url)
        if tenant and site and host:
            return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    if source == "icims":
        if source_key.endswith(".icims.com"):
            return f"https://{source_key}/jobs/search"
        if source_key.endswith(".jibeapply.com"):
            return f"https://{source_key}?icims=1"
    if source == "oracle_hcm":
        host, _, remainder = source_key.partition(":")
        language, _, site = remainder.partition(":")
        if host and language and site:
            return (
                f"https://{host}/hcmUI/CandidateExperience/"
                f"{quote(language, safe='')}/sites/{quote(site, safe='')}"
            )
    if source == "rippling":
        return f"https://ats.rippling.com/{quote(source_key, safe='')}/jobs"
    return evidence_url


def _ats_route_status(
    source: str,
    source_key: str,
    evidence_url: str,
) -> tuple[bool, str]:
    if not source_key:
        return False, "No reliable ATS source key was extracted"
    if source in {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "workable",
        "workday",
        "icims",
        "oracle_hcm",
        "rippling",
    }:
        return True, ""
    if source == "phenom":
        return False, "No supported public Phenom job-search endpoint was identified"
    if source in {"recruitee", "breezyhr", "bamboohr", "comeet"}:
        return False, f"No existing extraction route for {source}"
    return False, f"No known extraction route for {source}"


def _ats_evidence_quality(source: str, url: str) -> int:
    lowered = url.casefold()
    if source == "greenhouse":
        if _is_noisy_greenhouse_internal_url(url):
            return 0
        if "boards-api.greenhouse.io/" in lowered or "api.greenhouse.io/" in lowered:
            return 5
        if "embed/job_board/js" in lowered:
            return 4
        if "job-boards.greenhouse.io/" in lowered or "boards.greenhouse.io/" in lowered:
            return 3
        if _has_nonempty_gh_jid(url):
            return 1
    if source == "lever":
        if "api.lever.co/v0/postings/" in lowered:
            return 5
        if "jobs.lever.co/" in lowered or "jobs.eu.lever.co/" in lowered:
            return 4
    if "/api/" in lowered:
        return 4
    return 2


def build_ats_source_candidates(
    company: str,
    original_url: str,
    evidence_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    evidence = [
        row
        for row in evidence_rows
        if _is_real_ats_evidence(
            str(row.get("detected_source", "")),
            str(row.get("detected_url", "")),
        )
    ]
    keys_by_source: dict[str, set[str]] = {}
    for row in evidence:
        source = str(row.get("detected_source", ""))
        source_key = _ats_source_key(source, str(row.get("detected_url", "")))
        if source_key:
            keys_by_source.setdefault(source, set()).add(source_key)
    if not keys_by_source.get("greenhouse"):
        inferred_key = _infer_branded_greenhouse_source_key(
            company,
            original_url,
            evidence,
        )
        if inferred_key:
            keys_by_source["greenhouse"] = {inferred_key}

    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in evidence:
        source = str(row.get("detected_source", ""))
        source_key = _ats_source_key(source, str(row.get("detected_url", "")))
        if not source_key and len(keys_by_source.get(source, set())) == 1:
            source_key = next(iter(keys_by_source[source]))
        if not source_key and source == "phenom":
            source_key = re.sub(r"[^a-z0-9]+", "-", company.casefold()).strip("-")
        if source_key:
            grouped.setdefault((source, source_key), []).append(row)

    candidates: list[dict[str, object]] = []
    confidence_rank = {"low": 1, "medium": 2, "high": 3}
    for (source, source_key), rows in sorted(grouped.items()):
        best = max(
            rows,
            key=lambda row: (
                _ats_evidence_quality(
                    source,
                    str(row.get("detected_url", "")),
                ),
                confidence_rank.get(str(row.get("confidence", "low")), 0),
                -len(str(row.get("detected_url", ""))),
            ),
        )
        best_url = str(best.get("detected_url", ""))
        route_ready, route_block_reason = _ats_route_status(
            source,
            source_key,
            best_url,
        )
        confidence = str(best.get("confidence", "medium"))
        if source == "phenom" and not any(
            marker in str(row.get("detected_url", "")).casefold()
            for row in rows
            for marker in ("/api/", "jobsearch", "/search", "requisition")
        ):
            confidence = "medium"
            route_ready = False
        candidates.append(
            {
                "company": company,
                "original_url": original_url,
                "detected_source": source,
                "source_key": source_key,
                "canonical_ats_url": _canonical_ats_url(source, source_key, best_url),
                "evidence_count": len(rows),
                "best_evidence_url": best_url,
                "confidence": confidence,
                "route_ready": route_ready,
                "route_block_reason": route_block_reason,
                "notes": (
                    "Normalized passive ATS source candidate"
                    if not route_ready
                    else "Compatible source candidate; extraction not run"
                ),
            }
        )
    return candidates


def _is_skipped_discovery_link(url: str, combined_text: str) -> bool:
    parsed = urlsplit(url)
    host = _normalized_host(url)
    path = parsed.path.casefold()
    if any(path.endswith(extension) for extension in SKIP_EXTENSIONS):
        return True
    if any(host == social or host.endswith(f".{social}") for social in SOCIAL_HOSTS):
        return True
    if any(hint in combined_text for hint in SKIP_LINK_HINTS):
        return True
    if any(hint in combined_text for hint in SOFT_SKIP_LINK_HINTS) and not any(
        hint in combined_text for hint in STRONG_DISCOVERY_HINTS
    ):
        return True
    return False


def _looks_like_job_detail_url(url: str) -> bool:
    parsed = urlsplit(url)
    query = parsed.query.casefold()
    if re.search(r"(gh_jid|job[_-]?id|requisition|reqid)=", query):
        return True

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return False
    last_segment = segments[-1].casefold()
    if re.fullmatch(r"\d{4,}", last_segment):
        return True
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        last_segment,
    ):
        return True
    if (
        any(segment.casefold() in {"job", "jobs", "position", "positions"} for segment in segments[:-1])
        and last_segment.count("-") >= 4
        and ROLE_TITLE_PATTERN.search(last_segment.replace("-", " "))
    ):
        return True
    return False


def discover_pages(
    base_url: str,
    html: str,
    *,
    depth: int = 0,
    max_depth: int = MAX_DEPTH,
    max_pages: int = MAX_PAGES_PER_COMPANY,
) -> tuple[list[DiscoveredPage], list[str]]:
    if depth >= max_depth:
        return [], []

    soup = BeautifulSoup(html, "html.parser")
    base_host = _normalized_host(base_url)
    collect_internal_pages = max_pages > 1
    pages_by_url: dict[str, DiscoveredPage] = {}
    ats_links: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = clean_text(str(anchor.get("href", "")))
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if re.match(r"^/?www\.", href, flags=re.IGNORECASE):
            href = f"https://{href.lstrip('/')}"

        original_url = urljoin(base_url, href)
        if not _is_http_url(original_url):
            continue
        if re.search(r"/www\.[^/]+/", urlsplit(original_url).path, flags=re.IGNORECASE):
            continue

        link_text = clean_text(anchor.get_text(" ", strip=True))
        combined_text = f"{link_text} {urlsplit(original_url).path} {urlsplit(original_url).fragment}".casefold()
        target_host = _normalized_host(original_url)
        if target_host != base_host:
            ats_name = detect_ats(original_url)
            if ats_name:
                ats_links.add(f"{ats_name}:{normalize_page_url(original_url)}")
            continue

        if not collect_internal_pages:
            continue
        if _is_skipped_discovery_link(original_url, combined_text):
            continue
        if _looks_like_job_detail_url(original_url):
            continue

        matched_hints = [hint for hint in DISCOVERY_HINTS if hint in combined_text]
        if not matched_hints:
            continue

        fetch_url = normalize_page_url(original_url)
        if fetch_url == normalize_page_url(base_url):
            continue

        score = len(set(matched_hints))
        score += 3 * sum(hint in combined_text for hint in STRONG_DISCOVERY_HINTS)
        if urlsplit(original_url).fragment and any(
            hint in urlsplit(original_url).fragment.casefold()
            for hint in STRONG_DISCOVERY_HINTS
        ):
            score += 2

        page = DiscoveredPage(
            original_url=original_url,
            fetch_url=fetch_url,
            link_text=link_text,
            score=score,
        )
        existing = pages_by_url.get(fetch_url)
        if existing is None or (page.score, page.original_url) > (
            existing.score,
            existing.original_url,
        ):
            pages_by_url[fetch_url] = page

    ranked = sorted(
        pages_by_url.values(),
        key=lambda page: (-page.score, page.fetch_url),
    )
    return ranked[: max_pages - 1], sorted(ats_links)


def fetch_page(url: str) -> FetchResult:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=(10, 30),
        allow_redirects=True,
    )
    response.raise_for_status()
    return FetchResult(
        html=response.text,
        final_url=response.url,
        status_code=response.status_code,
    )


def validate_ats_source_candidates(
    candidates: list[dict[str, object]],
    *,
    enabled: bool = False,
    requester: Callable[..., requests.Response] = requests.get,
) -> list[dict[str, object]]:
    validations: list[dict[str, object]] = []
    for candidate in candidates:
        source = str(candidate.get("detected_source", ""))
        route_ready = bool(candidate.get("route_ready"))
        row = {
            "company": candidate.get("company", ""),
            "detected_source": source,
            "source_key": candidate.get("source_key", ""),
            "canonical_ats_url": candidate.get("canonical_ats_url", ""),
            "validation_status": "not_run",
            "validation_error": "",
        }
        if not enabled or not route_ready or source not in {"greenhouse", "lever"}:
            validations.append(row)
            continue
        try:
            response = requester(
                str(candidate["canonical_ats_url"]),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=(5, 15),
                allow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            valid_shape = (
                source == "greenhouse"
                and isinstance(payload, dict)
                and isinstance(payload.get("jobs"), list)
            ) or (source == "lever" and isinstance(payload, list))
            if valid_shape:
                row["validation_status"] = "valid"
            else:
                row["validation_status"] = "invalid_shape"
                row["validation_error"] = "Response did not match the expected jobs/postings shape"
        except (requests.RequestException, ValueError, TypeError) as error:
            row["validation_status"] = "error"
            row["validation_error"] = clean_text(str(error))
        validations.append(row)
    return validations
