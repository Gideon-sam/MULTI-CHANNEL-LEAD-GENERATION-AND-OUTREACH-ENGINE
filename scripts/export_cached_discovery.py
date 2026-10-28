"""Recover actual API discovery records from this project's HTTP cache; no network calls.

The resulting CSV is a research input, never an approved lead list.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from incubrix_engine.models import PodcastCandidate
from incubrix_engine.sources.apple_podcasts import _plain_text, deduplicate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/http"))
    parser.add_argument("--output", type=Path, default=Path("inputs/cached_discovery.csv"))
    parser.add_argument("--limit", type=int, default=12000)
    args = parser.parse_args()
    candidates = []
    for metadata_path in sorted(args.cache.glob("*.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            parsed = urlparse(metadata.get("url", ""))
            if parsed.hostname != "itunes.apple.com" or parsed.path != "/search":
                continue
            compressed = metadata_path.with_suffix(".body.gz")
            legacy = metadata_path.with_suffix(".body")
            data = json.loads(
                gzip.decompress(compressed.read_bytes())
                if compressed.exists()
                else legacy.read_bytes()
            )
        except (OSError, ValueError, TypeError):
            continue
        for item in data.get("results", []):
            feed_url = str(item.get("feedUrl", ""))
            apple_id = str(item.get("collectionId", ""))
            if not apple_id.isdigit() or not feed_url.startswith(("http://", "https://")):
                continue
            candidates.append(
                PodcastCandidate(
                    apple_id=apple_id,
                    artist_name=_plain_text(str(item.get("artistName", ""))),
                    collection_name=_plain_text(str(item.get("collectionName", ""))),
                    country_iso2="",
                    feed_url=feed_url,
                    apple_url=str(item.get("collectionViewUrl", "")),
                    genre=str(item.get("primaryGenreName", "")),
                    release_date=str(item.get("releaseDate", "")),
                )
            )
    candidates = deduplicate(candidates)
    # Recent release hints are useful for prioritization, never used as activity proof.
    candidates.sort(key=lambda c: (c.release_date, c.apple_id), reverse=True)
    candidates = candidates[: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PodcastCandidate.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(candidate) for candidate in candidates)
    print(json.dumps({"actual_discovered_candidates": len(candidates), "output": str(args.output)}))


if __name__ == "__main__":
    main()
