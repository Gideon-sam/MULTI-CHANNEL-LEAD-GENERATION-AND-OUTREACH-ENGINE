"""Check every extracted excerpt against stored source bytes; never certify its meaning."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path

from .audit_support import read_rows
from .bulk_evidence import _snapshot
from .exporters import _write_csv
from .files import write_text
from .review import PROOF_KINDS


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def check_source(job: tuple[str, list[dict], str, str]) -> list[dict]:
    url, claims, cache_dir, as_of = job
    cache = Path(cache_dir)
    body = b""
    cached = {}
    cache_error = ""
    cache_urls = list(dict.fromkeys([url, *[claim.get("requested_url", "") for claim in claims]]))
    for cache_url in filter(None, cache_urls):
        digest = hashlib.sha256((cache_url + "?{}").encode()).hexdigest()
        archive = cache / f"{digest}.body.gz"
        legacy = cache / f"{digest}.body"
        meta_path = cache / f"{digest}.json"
        try:
            body = (
                gzip.decompress(archive.read_bytes()) if archive.exists() else legacy.read_bytes()
            )
            cached = json.loads(meta_path.read_text(encoding="utf-8"))
            cache_error = ""
            break
        except (OSError, ValueError, TypeError) as error:
            cache_error = type(error).__name__
    actual_hash = hashlib.sha256(body).hexdigest() if body else ""
    raw = _normal(body[: 1024 * 1024].decode("utf-8", errors="replace"))
    visible = None
    results = []
    for claim in claims:
        status = ""
        quote = _normal(claim["verbatim_snippet"])
        if cache_error or not body:
            status = "source_bytes_unavailable"
        elif not 200 <= int(cached.get("status_code", 0)) < 300:
            status = "source_http_failure"
        elif claim["sha256"] != actual_hash:
            status = "source_snapshot_changed"
        else:
            try:
                fetched = datetime.fromisoformat(claim["fetch_date"]).date()
                fresh = 0 <= (date.fromisoformat(as_of) - fetched).days <= 30
            except (ValueError, TypeError):
                fresh = False
            if not fresh:
                status = "source_date_invalid_or_stale"
            elif quote and quote in raw:
                status = "exact_excerpt_and_snapshot_match"
            else:
                if visible is None:
                    visible = _normal(_snapshot(url, body, float(cached["fetched_at"])).visible)
                status = (
                    "exact_excerpt_and_snapshot_match"
                    if quote and quote in visible
                    else "excerpt_not_found"
                )
        results.append(
            {
                "stable_creator_id": claim["stable_creator_id"],
                "check": claim["check"],
                "url": url,
                "fetch_date": claim["fetch_date"],
                "integrity_status": status,
                "semantic_verdict": "UNREVIEWED",
            }
        )
    return results


def verify(directory: Path, cache: Path, as_of: str, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("Choose a new integrity report directory")
    claims = read_rows(directory / "proof_hints.csv")
    aliases = {
        (row["stable_creator_id"], row["resolved_url"]): row["requested_url"]
        for row in read_rows(directory / "link_checks.csv")
        if row["resolved_url"]
    }
    scope = "completed_research_export"
    if not claims and (directory / "records").is_dir():
        scope = "partial_checkpoint_snapshot"
        for path in sorted((directory / "records").glob("*.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            meta = row.get("metadata", {})
            aliases.update(
                {
                    (row["stable_creator_id"], check["resolved_url"]): check["requested_url"]
                    for check in meta.get("auto_link_checks", [])
                    if check["resolved_url"]
                }
            )
            draft = meta.get("auto_review_draft", {})
            for kind in PROOF_KINDS:
                url = draft.get(f"{kind}_url", "")
                snapshot = meta.get("auto_evidence_snapshots", {}).get(url, {})
                claims.append(
                    {
                        "stable_creator_id": row["stable_creator_id"],
                        "check": kind,
                        "url": url,
                        "verbatim_snippet": draft.get(f"{kind}_quote", ""),
                        "fetch_date": snapshot.get("retrieved_at", ""),
                        "sha256": snapshot.get("sha256", ""),
                    }
                )
    if not claims:
        raise ValueError("No completed proof_hints.csv to verify")
    groups = defaultdict(list)
    results = []
    for claim in claims:
        claim["requested_url"] = aliases.get((claim["stable_creator_id"], claim["url"]), "")
        if claim["url"] and claim["verbatim_snippet"]:
            groups[claim["url"]].append(claim)
        else:
            results.append(
                {
                    "stable_creator_id": claim["stable_creator_id"],
                    "check": claim["check"],
                    "url": claim["url"],
                    "fetch_date": claim["fetch_date"],
                    "integrity_status": "missing_hint",
                    "semantic_verdict": "UNREVIEWED",
                }
            )
    jobs = [(url, rows, str(cache), as_of) for url, rows in groups.items()]
    with ProcessPoolExecutor(max_workers=4) as workers:
        for rows in workers.map(check_source, jobs, chunksize=5):
            results.extend(rows)
    results.sort(key=lambda row: (row["stable_creator_id"], row["check"]))
    destination.mkdir(parents=True)
    _write_csv(destination / "excerpt_integrity.csv", results, list(results[0]))
    count = Counter(row["integrity_status"] for row in results)
    report = {
        "scope": scope,
        "checked_as_of": as_of,
        "proof_slots": len(results),
        "source_urls": len(groups),
        "candidate_ids": len({row["stable_creator_id"] for row in results}),
        "status_counts": dict(count),
        "all_available_excerpts_match": all(
            row["integrity_status"] in {"missing_hint", "exact_excerpt_and_snapshot_match"}
            for row in results
        ),
        "semantic_approval_count": 0,
        "note": "This checks source bytes, exact excerpts and dates. It does not establish creator ownership, business purpose, or other semantic qualification.",
    }
    write_text(destination / "report.json", json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".cache/http"))
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.research, args.cache, args.as_of, args.out), indent=2))


if __name__ == "__main__":
    main()
