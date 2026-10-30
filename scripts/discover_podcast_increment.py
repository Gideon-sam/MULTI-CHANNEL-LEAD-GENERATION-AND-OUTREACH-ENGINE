"""Bounded incremental discovery. Candidates are never labelled qualified here."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import httpx

from incubrix_engine.config import Config
from incubrix_engine.exporters import _write_csv
from incubrix_engine.files import write_text
from incubrix_engine.models import PodcastCandidate
from incubrix_engine.sources.podcast_index import (
    PodcastIndexApi,
    credentials_from_environment,
    discover,
)


async def run(base: Path, output: Path, start: int, limit: int) -> dict:
    if output.exists():
        raise FileExistsError("Choose a new discovery folder; existing research is preserved")
    config = Config.load("config/production.json")
    terms = config.search_terms[start:start + limit]
    if start < 0 or not 1 <= limit <= 100 or not terms:
        raise ValueError("Use a valid term offset and 1-100 queries")
    with base.open(encoding="utf-8-sig", newline="") as handle:
        known = {r.get("apple_id", "") for r in csv.DictReader(handle)} - {""}
    output.mkdir(parents=True)
    started = time.perf_counter()
    key, secret = credentials_from_environment()
    found, new, outcomes = {}, {}, []
    async with PodcastIndexApi(key, secret, Path(".cache/podcast_index"), 168) as api:
        for term in terms:
            try:
                rows = await discover(replace(
                    config, search_terms=[term], podcast_index_max_search_calls=1,
                    podcast_index_result_limit=200,
                ), api)
                for row in rows:
                    found[row.apple_id] = row
                    if row.apple_id not in known:
                        new[row.apple_id] = row
                outcomes.append({"query": term, "status": "completed", "returned_candidates": len(rows)})
            except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as error:
                outcomes.append({"query": term, "status": "failed", "error_type": type(error).__name__})
                # Stop provider-level errors rather than repeatedly consuming quota.
                if isinstance(error, RuntimeError):
                    break
            finally:
                _write_csv(output / "new_candidates.csv", [asdict(r) for r in new.values()], list(PodcastCandidate.__dataclass_fields__))
                write_text(output / "query_results.json", json.dumps(outcomes, indent=2))
                write_text(output / "progress.json", json.dumps({"queries_processed": len(outcomes), "queries_planned": len(terms), "new_candidates": len(new)}))
        report = {
            "as_of": config.checked_date, "source": "Podcast Index API",
            "queries_planned": len(terms), "queries_completed": sum(r["status"] == "completed" for r in outcomes),
            "queries_failed": sum(r["status"] == "failed" for r in outcomes),
            "unique_candidates_found": len(found), "new_candidates": len(new),
            "already_discovered": len(set(found) & known), "new_qualified_leads": 0,
            "successful_api_requests": api.requests, "cache_hits": api.cache_hits,
            "runtime_seconds": round(time.perf_counter() - started, 2), "actual_billed_cost": None,
            "note": "Discovery metadata only. Fetch publisher sources and verify all PDF gates before qualification.",
        }
    write_text(output / "report.json", json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=int, default=40)
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.base, args.out, args.start, args.limit)), indent=2))


if __name__ == "__main__":
    main()
