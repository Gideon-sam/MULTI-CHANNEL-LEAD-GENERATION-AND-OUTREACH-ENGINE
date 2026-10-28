"""Add a targeted, rate-limited Apple discovery pass without duplicating the base pool."""

from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import asdict, replace
from pathlib import Path

from incubrix_engine.config import Config
from incubrix_engine.http_client import HttpClient
from incubrix_engine.inputs import load_candidates
from incubrix_engine.models import PodcastCandidate
from incubrix_engine.sources.apple_podcasts import deduplicate, discover

EXTRA_TERMS = [
    "weekly business podcast",
    "entrepreneur podcast",
    "founder podcast",
    "leadership podcast",
    "management podcast",
    "marketing podcast",
    "sales podcast",
    "consultant podcast",
    "coach podcast",
    "educator podcast",
    "career podcast",
    "technology podcast",
    "artificial intelligence podcast",
    "finance podcast",
    "investing podcast",
    "real estate podcast",
    "health podcast",
    "fitness podcast",
    "wellness podcast",
    "psychology podcast",
    "parenting podcast",
    "author podcast",
    "public speaker podcast",
    "video podcast host",
]


def write_candidates(path: Path, rows: list[PodcastCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PodcastCandidate.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("inputs/cached_discovery.csv"))
    parser.add_argument(
        "--combined", type=Path, default=Path("inputs/cached_discovery_expanded.csv")
    )
    parser.add_argument("--new-only", type=Path, default=Path("inputs/additional_discovery.csv"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.combined.exists() or args.new_only.exists():
        raise ValueError("Discovery outputs already exist; move them before creating a new pass")
    root = Path.cwd()
    base = deduplicate(load_candidates(args.base))
    config = replace(
        Config.load(root / "config/production.json"),
        search_terms=EXTRA_TERMS,
        max_candidates=12000,
    )
    async with HttpClient(
        root / config.cache_dir,
        config.network_concurrency,
        config.per_host_concurrency,
        config.request_timeout_seconds,
        config.request_retries,
        config.cache_max_age_hours,
    ) as http:
        discovered = deduplicate(await discover(config, http, refresh=args.refresh))
        base_ids = {row.apple_id for row in base}
        new_rows = [row for row in discovered if row.apple_id not in base_ids]
        combined = deduplicate([*base, *new_rows])
        write_candidates(args.new_only, new_rows)
        write_candidates(args.combined, combined)
        print(
            {
                "base": len(base),
                "targeted_discovery": len(discovered),
                "new": len(new_rows),
                "combined": len(combined),
                "http": http.stats,
            }
        )


if __name__ == "__main__":
    asyncio.run(main())
