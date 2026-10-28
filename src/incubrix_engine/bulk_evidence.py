"""Bulk-fetch public creator evidence and prefill review fields without approving rows."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import Config
from .exporters import _write_csv
from .files import write_text
from .http_client import HttpClient
from .inputs import load_candidates
from .models import Lead
from .review import PROOF_KINDS
from .review_workflow import export_review_workbook
from .sources.apple_podcasts import (
    COMMERCIAL_SIGNALS,
    GENERIC_EMAIL_PREFIXES,
    LOCATION_PATTERNS,
    enrich,
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+(?:[1-9]|[12]\d|3[01]),?\s+20\d{2})\b",
    re.IGNORECASE,
)
SOCIAL_HOSTS = {
    "instagram.com": "Instagram",
    "linkedin.com": "LinkedIn",
    "x.com": "X",
    "twitter.com": "X",
    "facebook.com": "Facebook",
    "threads.net": "Threads",
    "tiktok.com": "TikTok",
    "youtube.com": "YouTube",
}
AUTO_FIELDS = [
    "stable_creator_id",
    "creator_name",
    "discovery_provider",
    "research_status",
    "country_iso2",
    "content_count_30d",
    "longform_count_60d",
    "official_site",
    "best_channel",
    "channel_handle_or_url",
    "backup_channel",
    "backup_handle_or_url",
    "proofs_prefilled",
    "missing_proofs",
    "fetch_warnings",
]


@dataclass(frozen=True)
class Snapshot:
    url: str
    raw: str
    visible: str
    title: str
    fetched_at: str
    sha256: str


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _public_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username


def _snippet(text: str, needle: str, radius: int = 130) -> str:
    if not text or not needle:
        return ""
    position = text.casefold().find(needle.casefold())
    if position < 0:
        return ""
    start = max(0, position - radius)
    end = min(len(text), position + len(needle) + radius)
    value = " ".join(text[start:end].split())
    return value[:400]


def _term_snippet(text: str, terms: tuple[str, ...] | list[str]) -> str:
    lowered = text.casefold()
    for term in terms:
        position = lowered.find(term.casefold())
        if position >= 0:
            return _snippet(text, text[position : position + len(term)])
    return ""


def _snapshot(url: str, content: bytes, fetched_at: float) -> Snapshot:
    raw = content[: 1024 * 1024].decode("utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.select("script, style, noscript, [id*='comment' i], [class*='comment' i]"):
        tag.decompose()
    visible = " ".join(soup.get_text(" ", strip=True).split())
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return Snapshot(
        url=url,
        raw=raw,
        visible=visible,
        title=title,
        fetched_at=datetime.fromtimestamp(fetched_at, UTC).isoformat(),
        sha256=hashlib.sha256(content).hexdigest(),
    )


async def _get_snapshot(
    http: HttpClient, url: str, *, respect_robots: bool
) -> tuple[Snapshot | None, str]:
    if not _public_url(url):
        return None, "invalid_or_missing_url"
    try:
        async with asyncio.timeout(30):
            response = await http.get(url, refresh=False, respect_robots=respect_robots)
        if response.stale:
            return None, "stale_fallback"
        return _snapshot(response.url, response.content, response.fetched_at), ""
    except httpx.HTTPStatusError as error:
        return None, f"http_{error.response.status_code}"
    except (httpx.HTTPError, OSError, ValueError, TimeoutError) as error:
        return None, type(error).__name__


def _internal_pages(home: Snapshot) -> list[str]:
    soup = BeautifulSoup(home.raw, "html.parser")
    pages = []
    for anchor in soup.find_all("a", href=True):
        label = f"{anchor.get_text(' ', strip=True)} {anchor.get('href', '')}".casefold()
        if not any(term in label for term in ("about", "contact", "work with", "services")):
            continue
        value = urljoin(home.url, str(anchor["href"])).split("#", 1)[0]
        if _host(value) == _host(home.url) and value not in pages:
            pages.append(value)
    return pages[:2]


def _routes(pages: list[Snapshot]) -> list[tuple[str, str, str, str]]:
    routes = []
    seen = set()
    for page in pages:
        soup = BeautifulSoup(page.raw, "html.parser")
        for anchor in soup.find_all("a", href=True):
            original = str(anchor["href"]).strip()
            lowered = original.casefold()
            if lowered.startswith("mailto:"):
                value = original.split(":", 1)[1].split("?", 1)[0].strip().lower()
                if (
                    not EMAIL_RE.fullmatch(value)
                    or value.split("@", 1)[0] in GENERIC_EMAIL_PREFIXES
                ):
                    continue
                route = ("Email", value, page.url, _snippet(page.raw, value))
            else:
                value = urljoin(page.url, original)
                host = _host(value)
                channel = next(
                    (
                        label
                        for domain, label in SOCIAL_HOSTS.items()
                        if host == domain or host.endswith("." + domain)
                    ),
                    "",
                )
                label = anchor.get_text(" ", strip=True)
                if not channel and not re.search(
                    r"contact|book|work.with|inquir", label, re.IGNORECASE
                ):
                    continue
                if not _public_url(value):
                    continue
                # The verifier requires the exact full route in the cited source.
                quote = _snippet(page.raw, value)
                if not quote and original.startswith(("http://", "https://")):
                    quote = _snippet(page.raw, original)
                if not quote:
                    continue
                route = (channel or "Website", value, page.url, quote)
            key = route[1].casefold().rstrip("/")
            if key not in seen and route[3]:
                seen.add(key)
                routes.append(route)
    return routes


def _find_in_snapshots(snapshots: list[Snapshot], needle: str) -> tuple[str, str]:
    for page in snapshots:
        quote = _snippet(page.visible, needle) or _snippet(page.raw, needle)
        if quote:
            return page.url, quote
    return "", ""


def _commercial_proof(snapshots: list[Snapshot]) -> tuple[str, str]:
    for page in snapshots:
        for _label, terms in COMMERCIAL_SIGNALS:
            quote = _term_snippet(page.visible, terms) or _term_snippet(page.raw, terms)
            if quote:
                return page.url, quote
    return "", ""


def _country_proof(country: str, snapshots: list[Snapshot]) -> tuple[str, str]:
    if country not in LOCATION_PATTERNS:
        return "", ""
    for page in snapshots:
        quote = _term_snippet(page.visible, list(LOCATION_PATTERNS[country]))
        if not quote:
            quote = _term_snippet(page.raw, list(LOCATION_PATTERNS[country]))
        if quote:
            return page.url, quote
    return "", ""


def _language_proof(feed: Snapshot | None) -> tuple[str, str]:
    if feed is None:
        return "", ""
    match = re.search(r"<(?:\w+:)?language\b[^>]*>\s*([^<]+?)\s*</", feed.raw, re.IGNORECASE)
    if match and match.group(1).strip().casefold().startswith("en"):
        return feed.url, match.group(1).strip()[:400]
    return "", ""


def _activity_contact_proof(snapshots: list[Snapshot], contact: str) -> tuple[str, str]:
    if not contact:
        return "", ""
    for page in snapshots:
        position = page.visible.casefold().find(contact.casefold())
        if position < 0:
            continue
        window = page.visible[max(0, position - 220) : position + len(contact) + 220]
        if DATE_RE.search(window):
            return page.url, " ".join(window.split())[:400]
    return "", ""


def auto_review_draft(lead: Lead, snapshots: list[Snapshot]) -> tuple[dict, list[str]]:
    """Return exact-source hints only; never a decision or reviewer assertion."""
    feed = next((page for page in snapshots if page.url == lead.source_feed_url), None)
    official = str(lead.metadata.get("official_site_url") or "")
    routes = _routes([page for page in snapshots if page is not feed])
    primary = lead.channel_handle_or_url
    primary_channel = lead.best_channel
    if not primary and routes:
        primary_channel, primary, _url, _quote = routes[0]
    primary_url, primary_quote = _find_in_snapshots(snapshots, primary)
    backups = [
        route
        for route in routes
        if route[1].casefold().rstrip("/") != primary.casefold().rstrip("/")
    ]
    backup_channel, backup, backup_url, backup_quote = backups[0] if backups else ("", "", "", "")
    identity_url, identity_quote = _find_in_snapshots(snapshots, lead.creator_name)
    country_url, country_quote = _country_proof(lead.country_iso2, snapshots)
    language_url, language_quote = _language_proof(feed)
    commercial_url, commercial_quote = _commercial_proof(snapshots)
    need_url, need_quote = _find_in_snapshots(snapshots, lead.personalization_hook)
    if not need_quote and lead.metadata.get("activity_items"):
        need_url, need_quote = _find_in_snapshots(
            snapshots, str(lead.metadata["activity_items"][0].get("title") or "")
        )
    activity_url, activity_quote = _activity_contact_proof(snapshots, primary)
    draft = {
        "creator_identity_key": official if _public_url(official) else "",
        "creator_name": lead.creator_name,
        "country_iso2": lead.country_iso2,
        "best_channel": primary_channel,
        "channel_handle_or_url": primary,
        "backup_channel": backup_channel,
        "backup_handle_or_url": backup,
        "need_description": lead.incubrix_need,
        "identity_url": identity_url,
        "identity_quote": identity_quote,
        "country_url": country_url,
        "country_quote": country_quote,
        "language_url": language_url,
        "language_quote": language_quote,
        "commercial_url": commercial_url,
        "commercial_quote": commercial_quote,
        "need_url": need_url,
        "need_quote": need_quote,
        "contact_url": primary_url,
        "contact_quote": primary_quote,
        "contact_activity_url": activity_url,
        "contact_activity_quote": activity_quote,
        "backup_url": backup_url,
        "backup_quote": backup_quote,
    }
    missing = [
        kind
        for kind in PROOF_KINDS
        if not draft.get(f"{kind}_url") or not draft.get(f"{kind}_quote")
    ]
    return draft, missing


async def collect(
    input_path: Path,
    config_path: Path,
    destination: Path,
    limit: int | None = None,
) -> dict:
    if destination.exists():
        raise FileExistsError("Choose a new output directory to preserve prior research")
    started = time.perf_counter()
    config = Config.load(config_path)
    candidates = load_candidates(input_path)
    if limit is not None:
        candidates = candidates[:limit]
    destination.mkdir(parents=True)
    rows: list[Lead] = []
    evidence_rows = []
    warnings = Counter()
    semaphore = asyncio.Semaphore(min(24, config.network_concurrency))
    async with HttpClient(
        Path(config.cache_dir),
        concurrency=min(32, config.network_concurrency),
        per_host_concurrency=min(4, config.per_host_concurrency),
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
        max_age_hours=config.cache_max_age_hours,
    ) as http:

        async def one(candidate):
            async with semaphore:
                result = await enrich(
                    candidate,
                    config,
                    http,
                    refresh=False,
                    identity_reviewed=True,
                )
                lead = result.lead
                lead.metadata["bulk_research_only"] = True
                lead.metadata["bulk_research_identity_not_approved"] = True
                snapshots = []
                issues = []
                feed, issue = await _get_snapshot(http, lead.source_feed_url, respect_robots=False)
                if feed:
                    snapshots.append(feed)
                elif issue:
                    issues.append(f"feed:{issue}")
                official = str(lead.metadata.get("official_site_url") or "")
                home, issue = await _get_snapshot(http, official, respect_robots=True)
                if home:
                    snapshots.append(home)
                    for page_url in _internal_pages(home):
                        page, page_issue = await _get_snapshot(http, page_url, respect_robots=True)
                        if page:
                            snapshots.append(page)
                        elif page_issue:
                            issues.append(f"site:{page_issue}")
                elif official and issue:
                    issues.append(f"site:{issue}")
                draft, missing = auto_review_draft(lead, snapshots)
                lead.metadata["auto_review_draft"] = draft
                lead.metadata["auto_evidence_snapshots"] = {
                    page.url: {
                        "retrieved_at": page.fetched_at,
                        "sha256": page.sha256,
                    }
                    for page in snapshots
                }
                lead.metadata["auto_evidence_missing"] = missing
                lead.metadata["auto_evidence_warnings"] = issues
                # Research bypasses only the identity heuristic and never constitutes approval.
                if lead.candidate_status == "Qualified":
                    lead.candidate_status = "Needs review"
                    lead.rejection_reason = "creator_specific_evidence_review_required"
                return lead, draft, missing, issues

        tasks = [asyncio.create_task(one(candidate)) for candidate in candidates]
        for completed, task in enumerate(asyncio.as_completed(tasks), 1):
            try:
                lead, draft, missing, issues = await task
            except Exception as error:  # noqa: BLE001 - isolate individual public sources
                warnings[type(error).__name__] += 1
                continue
            rows.append(lead)
            for issue in issues:
                warnings[issue] += 1
            evidence_rows.append(
                {
                    "stable_creator_id": lead.stable_creator_id,
                    "creator_name": lead.creator_name,
                    "discovery_provider": lead.metadata.get("discovery_provider", ""),
                    "research_status": lead.candidate_status,
                    "country_iso2": lead.country_iso2,
                    "content_count_30d": lead.content_count_30d,
                    "longform_count_60d": lead.longform_count_60d,
                    "official_site": lead.metadata.get("official_site_url", ""),
                    "best_channel": draft.get("best_channel", ""),
                    "channel_handle_or_url": draft.get("channel_handle_or_url", ""),
                    "backup_channel": draft.get("backup_channel", ""),
                    "backup_handle_or_url": draft.get("backup_handle_or_url", ""),
                    "proofs_prefilled": len(PROOF_KINDS) - len(missing),
                    "missing_proofs": ";".join(missing),
                    "fetch_warnings": ";".join(issues),
                }
            )
            if completed % 100 == 0:
                write_text(
                    destination / "progress.json",
                    json.dumps({"processed": completed, "total": len(tasks)}, indent=2),
                )
        stats = dict(http.stats)
    rows.sort(key=lambda lead: lead.stable_creator_id)
    evidence_rows.sort(key=lambda row: row["stable_creator_id"])
    queue = destination / "auto_enriched_queue.json"
    write_text(queue, json.dumps([asdict(lead) for lead in rows], ensure_ascii=False, indent=2))
    _write_csv(destination / "auto_evidence.csv", evidence_rows, AUTO_FIELDS)
    workbook = destination / "Master_Auto_Enriched.xlsx"
    export_review_workbook(queue, workbook)
    proof_distribution = Counter(int(row["proofs_prefilled"]) for row in evidence_rows)
    report = {
        "input_candidates": len(candidates),
        "processed_candidates": len(rows),
        "failed_tasks": len(candidates) - len(rows),
        "status_counts": dict(Counter(lead.candidate_status for lead in rows)),
        "proof_count_distribution": dict(sorted(proof_distribution.items())),
        "rows_with_all_eight_proofs_prefilled": proof_distribution[8],
        "field_coverage": {
            "country": sum(bool(row["country_iso2"]) for row in evidence_rows),
            "primary_contact": sum(bool(row["channel_handle_or_url"]) for row in evidence_rows),
            "backup_contact": sum(bool(row["backup_handle_or_url"]) for row in evidence_rows),
            "official_site": sum(bool(row["official_site"]) for row in evidence_rows),
        },
        "warnings": dict(warnings),
        "http": stats,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "qualification_changes": 0,
        "note": "Automated public-source extraction only. Decisions remain Pending; blank values were not fabricated.",
    }
    write_text(destination / "coverage_report.json", json.dumps(report, indent=2))
    write_text(
        destination / "progress.json",
        json.dumps({"processed": len(rows), "total": len(candidates), "completed": True}, indent=2),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/review_recheck_3000.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    print(json.dumps(asyncio.run(collect(args.input, args.config, args.out, args.limit)), indent=2))


if __name__ == "__main__":
    main()
