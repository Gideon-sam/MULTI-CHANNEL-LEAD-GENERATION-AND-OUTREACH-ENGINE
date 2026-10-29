"""Bulk-fetch public creator evidence and prefill review fields without approving rows."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
import warnings as py_warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import openpyxl
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from openpyxl.styles import Alignment, Font, PatternFill

from .config import Config
from .exporters import _write_csv
from .files import write_text
from .http_client import HttpClient
from .inputs import load_candidates
from .models import Lead
from .review import PROOF_KINDS
from .review_workflow import _text_cell, export_review_workbook
from .sources.apple_podcasts import (
    COMMERCIAL_SIGNALS,
    GENERIC_EMAIL_PREFIXES,
    LOCATION_PATTERNS,
    _country_from_text,
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
    requested_url: str = ""


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
    with py_warnings.catch_warnings():
        py_warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.select(
        "script, style, noscript, [id*='comment' i], [class*='comment' i], "
        "[id*='review' i], [class*='review' i]"
    ):
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
    http: HttpClient,
    url: str,
    *,
    respect_robots: bool,
    refresh: bool = False,
    executor: ProcessPoolExecutor | None = None,
) -> tuple[Snapshot | None, str]:
    if not _public_url(url):
        return None, "invalid_or_missing_url"
    try:
        async with asyncio.timeout(30):
            response = await http.get(url, refresh=refresh, respect_robots=respect_robots)
        if response.stale:
            return None, "stale_fallback"
        from dataclasses import replace

        if executor is None:
            page = _snapshot(response.url, response.content, response.fetched_at)
        else:
            page = await asyncio.get_running_loop().run_in_executor(
                executor, _snapshot, response.url, response.content, response.fetched_at
            )
        if respect_robots and (
            re.search(
                r"404|not found|access denied|sign in|log in|just a moment",
                page.title,
                re.IGNORECASE,
            )
            or re.search(r"lorem ipsum|neque porro", page.visible, re.IGNORECASE)
        ):
            return None, "soft_error_or_placeholder"
        return replace(page, requested_url=url), ""
    except httpx.HTTPStatusError as error:
        return None, f"http_{error.response.status_code}"
    except (httpx.HTTPError, OSError, ValueError, TimeoutError) as error:
        return None, type(error).__name__


def _internal_pages(home: Snapshot) -> list[str]:
    if re.search(r"<(?:rss|feed|channel)\b", home.raw[:2000], re.IGNORECASE):
        return []
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
        if re.search(r"<(?:rss|feed|channel)\b", page.raw[:2000], re.IGNORECASE):
            continue
        soup = BeautifulSoup(page.raw, "html.parser")
        for tag in soup.select("[id*='comment' i], [class*='comment' i]"):
            tag.decompose()
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
                route_path = urlparse(value).path.rstrip("/")
                if channel and (
                    not route_path
                    or re.search(
                        r"/(?:share|sharer|intent|watch|embed|reel|shorts|posts?)(?:/|$|\.php)",
                        route_path,
                    )
                    or urlparse(value).query
                ):
                    continue
                label = anchor.get_text(" ", strip=True)
                if not channel and not re.search(
                    r"contact|book.(?:a.call|now|consult)|work.with|inquir",
                    label,
                    re.IGNORECASE,
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


def _country_names_creator(name: str, quote: str) -> bool:
    """A location for a guest or staff member is not a creator-country prefill."""
    tokens = re.findall(r"[a-z]+", name.casefold())
    return len(tokens) >= 2 and all(
        re.search(rf"\b{re.escape(token)}\b", quote.casefold()) for token in tokens[:2]
    )


def _guard_country_draft(lead: Lead) -> None:
    draft = lead.metadata.get("auto_review_draft", {})
    quote = draft.get("country_quote", "")
    if quote and not _country_names_creator(lead.creator_name, quote):
        lead.metadata["unattributed_country_hint"] = {
            "url": draft.get("country_url", ""),
            "quote": quote,
            "reason": "Location excerpt does not name this creator",
        }
        for key in ("country_iso2", "country_url", "country_quote"):
            draft[key] = ""
        missing = lead.metadata.setdefault("auto_evidence_missing", [])
        if "country" not in missing:
            missing.append("country")


def _language_proof(feed: Snapshot | None) -> tuple[str, str]:
    if feed is None:
        return "", ""
    match = re.search(r"<(?:\w+:)?language\b[^>]*>\s*([^<]+?)\s*</", feed.raw, re.IGNORECASE)
    if match and match.group(1).strip().casefold().startswith("en"):
        return feed.url, match.group(1).strip()[:400]
    return "", ""


def _activity_contact_proof(
    snapshots: list[Snapshot], contact: str, checked_date: str
) -> tuple[str, str, str]:
    if not contact or not checked_date:
        return "", "", ""
    today = date.fromisoformat(checked_date)
    for page in snapshots:
        if re.search(r"<(?:rss|feed|channel)\b", page.raw[:2000], re.IGNORECASE):
            continue
        position = page.visible.casefold().find(contact.casefold())
        if position < 0:
            continue
        window = page.visible[max(0, position - 220) : position + len(contact) + 220]
        match = DATE_RE.search(window)
        if not match or not re.search(
            r"business|inquir|contact|sponsor|booking", window, re.IGNORECASE
        ):
            continue
        text = match.group(0)
        parsed = None
        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y.%m.%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%B %d %Y",
            "%b %d %Y",
        ):
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is not None and 0 <= (today - parsed).days <= 60:
            excerpt = " ".join(window.split())[:400]
            if text in excerpt and contact.casefold() in excerpt.casefold():
                return page.url, excerpt, parsed.isoformat()
    return "", "", ""


def auto_review_draft(lead: Lead, snapshots: list[Snapshot]) -> tuple[dict, list[str]]:
    """Return exact-source hints only; never a decision or reviewer assertion."""
    feed = next(
        (page for page in snapshots if lead.source_feed_url in {page.url, page.requested_url}), None
    )
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
    country_hint = ""
    country_url, country_quote = "", ""
    for page in snapshots:
        if page is feed:
            continue
        found, location = _country_from_text(page.visible)
        if found:
            quote = _snippet(page.visible, location)
            if _country_names_creator(lead.creator_name, quote):
                country_hint = found
                country_url, country_quote = page.url, quote
                break
    language_url, language_quote = _language_proof(feed)
    commercial_url, commercial_quote = _commercial_proof(snapshots)
    need_url, need_quote = _find_in_snapshots(snapshots, lead.personalization_hook)
    if not need_quote and lead.metadata.get("activity_items"):
        need_url, need_quote = _find_in_snapshots(
            snapshots, str(lead.metadata["activity_items"][0].get("title") or "")
        )
    activity_url, activity_quote, contact_active_date = _activity_contact_proof(
        snapshots, primary, lead.checked_date
    )
    draft = {
        "creator_identity_key": official if _public_url(official) else "",
        "creator_name": lead.creator_name,
        "country_iso2": country_hint,
        "best_channel": primary_channel,
        "channel_handle_or_url": primary,
        "backup_channel": backup_channel,
        "backup_handle_or_url": backup,
        "contact_active_date": contact_active_date,
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
    *,
    refresh: bool = False,
    resume: bool = False,
) -> dict:
    if destination.exists() and not resume:
        raise FileExistsError("Choose a new output directory to preserve prior research")
    started = time.perf_counter()
    config = Config.load(config_path)
    candidates = load_candidates(input_path)
    if limit is not None:
        candidates = candidates[:limit]
    destination.mkdir(parents=True, exist_ok=resume)
    checkpoints = destination / "records"
    checkpoints.mkdir(exist_ok=resume)
    run_contract = {
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "checked_date": config.checked_date,
        "limit": limit,
        "refresh": refresh,
    }
    contract_path = destination / "run_contract.json"
    if resume:
        if json.loads(contract_path.read_text(encoding="utf-8")) != run_contract:
            raise ValueError("Resume requires the same input, config, date and refresh option")
    else:
        write_text(contract_path, json.dumps(run_contract, indent=2))
    if (destination / "Master_Auto_Enriched.xlsx").exists():
        raise FileExistsError("Completed workbook already exists; preserve reviewer edits")
    rows: list[Lead] = []
    evidence_rows = []
    proof_rows = []
    link_rows = []
    failed_tasks = 0
    resumed_records = 0
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
        executor = ProcessPoolExecutor(max_workers=4)

        async def research_one(candidate):
            result = await enrich(
                candidate,
                config,
                http,
                refresh=refresh,
                identity_reviewed=True,
                parse_executor=executor,
            )
            lead = result.lead
            lead.metadata["bulk_research_only"] = True
            lead.metadata["bulk_research_identity_not_approved"] = True
            snapshots = []
            issues = []
            checks = []

            async def fetch(url, kind, live=False):
                if not url:
                    return None
                page, issue = await _get_snapshot(
                    http, url, respect_robots=kind != "feed", refresh=live, executor=executor
                )
                checks.append(
                    {
                        "stable_creator_id": lead.stable_creator_id,
                        "kind": kind,
                        "requested_url": url,
                        "resolved_url": page.url if page else "",
                        "status": "fetched" if page else issue,
                        "fetched_at": page.fetched_at if page else "",
                        "sha256": page.sha256 if page else "",
                    }
                )
                if issue:
                    issues.append(f"{kind}:{issue}")
                return page

            # Reuse the feed fetched by enrich; preserve any failed live-refresh flag.
            if not lead.metadata.get("feed_stale"):
                feed = await fetch(lead.source_feed_url, "feed")
                if feed:
                    snapshots.append(feed)
            else:
                issues.append("feed:stale_fallback")
            official = str(lead.metadata.get("official_site_url") or "")
            home = await fetch(official, "site", refresh)
            if home:
                snapshots.append(home)
                for page_url in _internal_pages(home):
                    if page_url not in {page.url for page in snapshots}:
                        page = await fetch(page_url, "site", refresh)
                        if page:
                            snapshots.append(page)
            draft, missing = auto_review_draft(lead, snapshots)
            for role in ("channel_handle_or_url", "backup_handle_or_url"):
                route = draft.get(role, "")
                if _public_url(route) and route not in {page.url for page in snapshots}:
                    await fetch(route, role, refresh)
            lead.metadata["auto_review_draft"] = draft
            lead.metadata["auto_evidence_snapshots"] = {
                page.url: {"retrieved_at": page.fetched_at, "sha256": page.sha256}
                for page in snapshots
            }
            lead.metadata["auto_evidence_missing"] = missing
            lead.metadata["auto_evidence_warnings"] = issues
            lead.metadata["auto_link_checks"] = checks
            lead.metadata["auto_semantic_review_required"] = list(PROOF_KINDS)
            # All input rows have an unresolved creator-specific review.
            if lead.candidate_status == "Qualified":
                lead.candidate_status = "Needs review"
                lead.rejection_reason = "creator_specific_evidence_review_required"
            return lead

        async def one(candidate):
            record_path = checkpoints / f"{candidate.apple_id}.json"
            if resume and record_path.exists():
                lead = Lead(**json.loads(record_path.read_text(encoding="utf-8")))
                _guard_country_draft(lead)
                write_text(record_path, json.dumps(asdict(lead), ensure_ascii=False, indent=2))
                return lead, True
            async with semaphore:
                try:
                    async with asyncio.timeout(180):
                        lead = await research_one(candidate)
                except Exception as error:  # noqa: BLE001 - preserve each failed identity
                    lead = Lead(
                        stable_creator_id=f"apple-podcast:{candidate.apple_id}",
                        creator_name=candidate.artist_name,
                        source_feed_url=candidate.feed_url,
                        profile_url=candidate.apple_url,
                        checked_date=config.checked_date,
                        candidate_status="Needs review",
                        rejection_reason="research_unavailable",
                        metadata={
                            "auto_evidence_warnings": [type(error).__name__],
                            "auto_evidence_missing": list(PROOF_KINDS),
                            "auto_review_draft": {},
                            "research_error": type(error).__name__,
                            "discovery_provider": candidate.discovery_provider,
                        },
                    )
                write_text(record_path, json.dumps(asdict(lead), ensure_ascii=False, indent=2))
                return lead, False

        tasks = [asyncio.create_task(one(candidate)) for candidate in candidates]
        for completed, task in enumerate(asyncio.as_completed(tasks), 1):
            lead, reused = await task
            resumed_records += int(reused)
            failed_tasks += int(bool(lead.metadata.get("research_error")))
            draft = lead.metadata["auto_review_draft"]
            missing = lead.metadata["auto_evidence_missing"]
            issues = lead.metadata["auto_evidence_warnings"]
            rows.append(lead)
            link_rows.extend(lead.metadata.get("auto_link_checks", []))
            for kind in PROOF_KINDS:
                url = draft.get(f"{kind}_url", "")
                proof_rows.append(
                    {
                        "stable_creator_id": lead.stable_creator_id,
                        "check": kind,
                        "url": url,
                        "verbatim_snippet": draft.get(f"{kind}_quote", ""),
                        "fetch_date": lead.metadata.get("auto_evidence_snapshots", {})
                        .get(url, {})
                        .get("retrieved_at", ""),
                        "sha256": lead.metadata.get("auto_evidence_snapshots", {})
                        .get(url, {})
                        .get("sha256", ""),
                        "semantic_verdict": "UNREVIEWED",
                        "reviewer": "",
                    }
                )
            for issue in issues:
                warnings[issue] += 1
            evidence_rows.append(
                {
                    "stable_creator_id": lead.stable_creator_id,
                    "creator_name": lead.creator_name,
                    "discovery_provider": lead.metadata.get("discovery_provider", ""),
                    "research_status": lead.candidate_status,
                    "country_iso2": draft.get("country_iso2", ""),
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
            if completed % 25 == 0 or completed == len(tasks):
                progress = {
                    "processed": completed,
                    "total": len(tasks),
                    "failed_tasks": failed_tasks,
                    "runtime_seconds": round(time.perf_counter() - started, 2),
                }
                write_text(
                    destination / "progress.json",
                    json.dumps(progress, indent=2),
                )
                if completed % 100 == 0:
                    print(json.dumps(progress), flush=True)
        stats = dict(http.stats)
        await asyncio.to_thread(executor.shutdown, wait=True)
    rows.sort(key=lambda lead: lead.stable_creator_id)
    evidence_rows.sort(key=lambda row: row["stable_creator_id"])
    queue = destination / "auto_enriched_queue.json"
    write_text(queue, json.dumps([asdict(lead) for lead in rows], ensure_ascii=False, indent=2))
    _write_csv(destination / "auto_evidence.csv", evidence_rows, AUTO_FIELDS)
    _write_csv(
        destination / "proof_hints.csv", proof_rows, list(proof_rows[0]) if proof_rows else []
    )
    _write_csv(destination / "link_checks.csv", link_rows, list(link_rows[0]) if link_rows else [])
    workbook = destination / "Master_Auto_Enriched.xlsx"
    export_review_workbook(queue, workbook)
    proof_distribution = Counter(int(row["proofs_prefilled"]) for row in evidence_rows)
    report = {
        "input_candidates": len(candidates),
        "processed_candidates": len(rows),
        "failed_tasks": failed_tasks,
        "resumed_records": resumed_records,
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
        "fully_verified_creators_added": 0,
        "target_verified_creators": 3000,
        "actual_billed_cost": None,
        "refresh_requested": refresh,
        "missing_proof_counts": dict(
            Counter(kind for lead in rows for kind in lead.metadata["auto_evidence_missing"])
        ),
        "source_link_statuses": dict(Counter(row["status"] for row in link_rows)),
        "note": "Automated public-source extraction only. Decisions remain Pending; blank values were not fabricated.",
    }
    write_text(destination / "coverage_report.json", json.dumps(report, indent=2))
    book = openpyxl.load_workbook(workbook)
    for name, data in (
        ("Coverage", evidence_rows),
        ("Evidence", proof_rows),
        ("Link Checks", link_rows),
    ):
        sheet = book.create_sheet(name)
        if data:
            fields = list(data[0])
            sheet.append(fields)
            for number, item in enumerate(data, 2):
                for column, field in enumerate(fields, 1):
                    _text_cell(sheet, number, column, item[field])
            sheet.auto_filter.ref = sheet.dimensions
            sheet.freeze_panes = "C2"
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="123D45")
                sheet.column_dimensions[cell.column_letter].width = 28
    start = book["START_HERE"]
    start.append(
        ["AUTO-FILLED: every proof is an extracted hint requiring creator-specific interpretation."]
    )
    start.append(
        [
            "Coverage lists gaps; Evidence gives exact excerpts and fetch dates; Link Checks records availability."
        ]
    )
    for sheet in book:
        for row in sheet.iter_rows(min_row=2):
            if sheet.title != "START_HERE":
                sheet.row_dimensions[row[0].row].height = 30
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=False)
    book.save(workbook)
    book.close()
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
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    print(
        json.dumps(
            asyncio.run(
                collect(
                    args.input,
                    args.config,
                    args.out,
                    args.limit,
                    refresh=args.refresh,
                    resume=args.resume,
                )
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
