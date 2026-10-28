"""Check evidence links without changing source data, decisions, or contacts."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .audit_support import evidence_chain, read_rows
from .exporters import _write_csv
from .files import write_text
from .http_client import HttpClient


def collect_links(rows: list[dict]) -> dict[str, list[str]]:
    links: dict[str, list[str]] = {}
    for row in rows:
        identity = row.get("lead_id") or row.get("stable_creator_id", "")
        values = [
            row.get(key, "")
            for key in (
                "profile_url",
                "recent_content_url",
                "monetization_evidence_url",
                "need_evidence_url",
                "channel_evidence_url",
                "source_feed_url",
            )
        ]
        values += [entry["url"] for entry in evidence_chain(row)]
        for key in ("channel_handle_or_url", "backup_channel"):
            match = re.search(r"https?://\S+", row.get(key, ""))
            if match:
                values.append(match.group(0))
        for url in filter(None, values):
            if identity not in links.setdefault(url, []):
                links[url].append(identity)
    return links


async def check_link(url: str, http: HttpClient) -> dict:
    result = {
        "url": url,
        "resolved_url": "",
        "http_status": None,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "unavailable",
        "detail": "",
        "my_manual_verdict": "",
        "my_evidence_path": "",
    }
    if urlparse(url).scheme not in {"https", "http"}:
        result.update(status="malformed", detail="Missing valid HTTP(S) scheme")
        return result
    try:
        response = await http.get(url, refresh=True, respect_robots=True)
        result["resolved_url"] = response.url
        if response.stale:
            result.update(
                status="unverified_stale_fallback",
                detail="Live check failed; cached success is not live proof",
            )
        else:
            result["http_status"] = response.status_code
            body = response.content[:100000].decode("utf-8", errors="replace").lower()
            soft_error = bool(
                re.search(r"<title[^>]*>[^<]*(?:404|not found|unavailable|sign in|log in)", body)
            )
            result["status"] = "manual_check_soft_error" if soft_error else "http_ok"
            result["detail"] = "HTTP success only; manually confirm the cited claim and identity"
    except httpx.HTTPStatusError as error:
        result["http_status"] = error.response.status_code
        result["status"] = "not_found" if error.response.status_code in {404, 410} else "http_error"
        result["detail"] = type(error).__name__
    except (httpx.HTTPError, OSError, ValueError) as error:
        result["status"] = "blocked_or_unavailable"
        result["detail"] = type(error).__name__
    return result


async def check_file(path: Path, destination: Path, cache: Path, sample: int | None = None) -> dict:
    rows = sorted(read_rows(path), key=lambda row: row.get("stable_creator_id", ""))
    population = len(rows)
    if sample is not None:
        rows = random.Random(2027).sample(rows, min(sample, len(rows)))
    links = collect_links(rows)
    semaphore = asyncio.Semaphore(16)
    async with HttpClient(
        cache, concurrency=16, per_host_concurrency=3, timeout_seconds=8, retries=1
    ) as http:

        async def check(url: str) -> dict:
            async with semaphore:
                result = await check_link(url, http)
                result["lead_ids"] = " | ".join(links[url])
                return result

        results = await asyncio.gather(*(check(url) for url in sorted(links)))
    fields = [
        "url",
        "lead_ids",
        "resolved_url",
        "http_status",
        "checked_at",
        "status",
        "detail",
        "my_manual_verdict",
        "my_evidence_path",
    ]
    if destination.exists():
        raise FileExistsError(
            "Link report exists; choose a new destination to preserve manual verdicts"
        )
    _write_csv(destination, results, fields)
    report = {
        "source": str(path),
        "population_rows": population,
        "checked_rows": len(rows),
        "unique_urls": len(links),
        "status_counts": dict(Counter(row["status"] for row in results)),
        "http": http.stats,
        "note": "No source links rewritten. Not-found and blocked links require another public source or manual review. HTTP 200 does not certify a business contact.",
    }
    write_text(destination.with_suffix(".json"), json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path("output/evidence_ledger.csv"))
    parser.add_argument("--out", type=Path, default=Path("output/link_checks.csv"))
    parser.add_argument("--sample", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(check_file(args.ledger, args.out, Path(".cache/link_health"), args.sample)),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
