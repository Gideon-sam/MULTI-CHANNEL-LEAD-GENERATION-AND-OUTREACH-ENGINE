"""Fetch public evidence behind discovery hints without changing qualification decisions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .audit_support import metadata, read_rows
from .exporters import _write_csv
from .files import write_text
from .http_client import HttpClient

WEB_FIELDS = [
    "stable_creator_id",
    "creator_name",
    "url",
    "resolved_url",
    "discovery_basis",
    "status",
    "http_status",
    "fetched_at",
    "sha256",
    "page_title",
    "excerpt",
    "public_contact_links",
    "content_dates",
    "review_warning",
]
PLATFORM_HOSTS = {
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "facebook.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "podcasts.apple.com",
    "open.spotify.com",
}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _website(url: str) -> bool:
    parsed = urlparse(url)
    host = _host(url)
    return (
        parsed.scheme in {"http", "https"}
        and bool(host)
        and not parsed.username
        and not any(host == name or host.endswith("." + name) for name in PLATFORM_HOSTS)
    )


def seed_urls(row: dict, hints: dict) -> list[tuple[str, str]]:
    """Prioritize supplied sources; label search matches without assuming ownership."""
    meta = metadata(row)
    seeds: dict[str, str] = {}
    for url in (
        meta.get("official_site_url", ""),
        row.get("channel_handle_or_url", ""),
    ):
        if isinstance(url, str) and _website(url):
            seeds.setdefault(url, "existing_candidate_source_requires_review")
    if not seeds:
        for result in hints.get("results", []):
            url = result.get("url", "")
            if _website(url):
                seeds.setdefault(url, "search_match_ownership_unverified")
    return list(seeds.items())[:2]


def page_evidence(content: bytes, url: str) -> dict:
    """Extract verbatim normalized page excerpts; dates and links remain unverified clues."""
    soup = BeautifulSoup(content[: 512 * 1024].decode("utf-8", errors="replace"), "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup.select("script, style, noscript, [id*='comment' i], [class*='comment' i]"):
        tag.decompose()
    visible = " ".join(soup.get_text(" ", strip=True).split())
    pattern = re.compile(
        r"\b(?:business|contact|inquir(?:y|ies)|coaching|sponsor|based in|work with|"
        r"course|consulting|repurpos\w*|editing|publishing|newsletter)\b",
        re.IGNORECASE,
    )
    excerpts = []
    for match in pattern.finditer(visible):
        excerpt = visible[max(0, match.start() - 50) : match.end() + 170]
        if excerpt not in excerpts:
            excerpts.append(excerpt)
        if len(excerpts) >= 3:
            break
    contact_links = []
    next_pages = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, str(anchor["href"]))
        label = anchor.get_text(" ", strip=True)
        if href.startswith("mailto:") or re.search(
            r"contact|work.with|book.a.call", label, re.IGNORECASE
        ):
            contact_links.append(href)
        if (
            _host(href) == _host(url)
            and _website(href)
            and re.search(r"(?:contact|about)", label + " " + urlparse(href).path, re.IGNORECASE)
        ):
            next_pages.append(href.split("#", 1)[0])
    dates = list(
        dict.fromkeys(str(tag.get("datetime")) for tag in soup.find_all("time", datetime=True))
    )[:10]
    warnings = ["Page text, dates and links require creator-specific interpretation"]
    if re.search(r"lorem ipsum|neque porro|loterl poinent", visible, re.IGNORECASE):
        warnings.append("PLACEHOLDER COPY: do not accept as evidence")
    soft_error = bool(
        re.search(r"404|not found|unavailable|sign in|log in|access denied", title, re.IGNORECASE)
    )
    if soft_error:
        warnings.append("Possible soft error or login page")
    return {
        "page_title": title,
        "excerpt": "\n[…]\n".join(excerpts) if excerpts else visible[:220],
        "public_contact_links": "\n".join(dict.fromkeys(contact_links)),
        "content_dates": "\n".join(dates),
        "review_warning": "; ".join(warnings),
        "next_pages": list(dict.fromkeys(next_pages))[:2],
        "soft_error": soft_error,
    }


async def fetch_page(http: HttpClient, row: dict, url: str, basis: str) -> tuple[dict, list[str]]:
    result = dict.fromkeys(WEB_FIELDS, "")
    result.update(
        stable_creator_id=row["stable_creator_id"],
        creator_name=row.get("creator_name", ""),
        url=url,
        discovery_basis=basis,
        status="unavailable",
    )
    try:
        async with asyncio.timeout(25):
            response = await http.get(url, refresh=True, respect_robots=True)
        result.update(
            resolved_url=response.url,
            http_status=response.status_code,
            fetched_at=datetime.fromtimestamp(response.fetched_at, UTC).isoformat(),
            sha256=hashlib.sha256(response.content).hexdigest(),
        )
        if response.stale:
            result.update(status="stale_fallback", review_warning="Live retrieval failed")
            return result, []
        parsed = page_evidence(response.content, response.url)
        next_pages = parsed.pop("next_pages")
        result["status"] = "soft_error" if parsed.pop("soft_error") else "fetched_requires_review"
        result.update(parsed)
        if _host(url) != _host(response.url):
            result["review_warning"] += "; Cross-domain redirect: confirm ownership"
        return result, next_pages
    except httpx.HTTPStatusError as error:
        result.update(http_status=error.response.status_code, status="http_error")
    except (httpx.HTTPError, OSError, ValueError, TimeoutError) as error:
        result.update(status="blocked_or_unavailable", review_warning=type(error).__name__)
    return result, []


async def research(directory: Path, destination: Path, limit: int = 100) -> dict:
    if destination.exists():
        raise FileExistsError("Choose a new research directory to preserve existing annotations")
    started = time.perf_counter()
    hints_path = directory / "web_evidence_hints.json"
    hints = json.loads(hints_path.read_text(encoding="utf-8")) if hints_path.exists() else []
    by_id = {row["stable_creator_id"]: row for row in hints[:limit]}
    pending = read_rows(directory / "review_queue.csv")
    selected = {r["stable_creator_id"]: r for r in pending if r["stable_creator_id"] in by_id}
    selected.update(
        {r["stable_creator_id"]: r for r in read_rows(directory / "evidence_ledger.csv")}
    )
    semaphore = asyncio.Semaphore(8)
    async with HttpClient(Path(".cache/evidence_research"), timeout_seconds=8, retries=1) as http:

        async def one(row: dict) -> list[dict]:
            async with semaphore:
                seeds = seed_urls(row, by_id.get(row["stable_creator_id"], {}))
                seen = set()
                pages = []
                follow = []
                for url, basis in seeds:
                    seen.add(url)
                    result, links = await fetch_page(http, row, url, basis)
                    pages.append(result)
                    follow.extend(links)
                for url in list(dict.fromkeys(follow))[:2]:
                    if url not in seen:
                        result, _ = await fetch_page(
                            http, row, url, "linked_about_or_contact_page_requires_review"
                        )
                        pages.append(result)
                return pages

        batches = await asyncio.gather(*(one(row) for row in selected.values()))
        stats = dict(http.stats)
    pages = [row for batch in batches for row in batch]
    destination.mkdir(parents=True)
    _write_csv(destination / "fetched_evidence.csv", pages, WEB_FIELDS)
    report = {
        "source_run": str(directory),
        "selected_candidates": len(selected),
        "candidates_with_pages": len({r["stable_creator_id"] for r in pages}),
        "page_records": len(pages),
        "statuses": dict(Counter(r["status"] for r in pages)),
        "qualification_changes": 0,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "http": stats,
        "actual_billed_cost": None,
        "note": "Exact page excerpts collected for review. Website ownership, contact purpose/activity, country and need are not inferred from keyword matches.",
    }
    write_text(destination / "report.json", json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("limit must be between 1 and 100")
    print(json.dumps(asyncio.run(research(args.run, args.out, args.limit)), indent=2))


if __name__ == "__main__":
    main()
