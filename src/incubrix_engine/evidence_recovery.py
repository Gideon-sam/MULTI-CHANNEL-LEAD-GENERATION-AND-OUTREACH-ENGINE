"""Recover dated publisher invitations from preserved source bytes; never approve leads."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from .contact_evidence import publisher_contact_hints
from .exporters import _write_csv
from .files import write_text
from .review import PROOF_KINDS


def _host(value: str) -> str:
    return (urlparse(value).hostname or "").casefold().removeprefix("www.")


def recover_one(job: tuple[dict, str, str]) -> tuple[dict, str]:
    row, cache, as_of = job
    meta = row.setdefault("metadata", {})
    draft = meta.get("auto_review_draft", {})
    official = str(meta.get("official_site_url") or "")
    feed = row.get("source_feed_url", "")
    if not feed or not official:
        return row, "missing_official_site_or_feed"
    try:
        digest = hashlib.sha256((feed + "?{}").encode()).hexdigest()
        root = Path(cache)
        info = json.loads((root / f"{digest}.json").read_text(encoding="utf-8"))
        path = root / f"{digest}.body.gz"
        body = gzip.decompress(path.read_bytes()) if path.exists() else (root / f"{digest}.body").read_bytes()
        resolved = info.get("url", feed)
        stored = meta.get("auto_evidence_snapshots", {}).get(resolved, {})
        actual_hash = hashlib.sha256(body).hexdigest()
        if not stored or stored.get("sha256") != actual_hash:
            return row, "snapshot_missing_or_changed"
        fetched = datetime.fromtimestamp(float(info["fetched_at"]), UTC)
        if not 200 <= int(info["status_code"]) < 300:
            return row, "source_http_failure"
        if not 0 <= (date.fromisoformat(as_of) - fetched.date()).days <= 30:
            return row, "source_stale_or_future"
        known = set()
        contact = str(draft.get("channel_handle_or_url") or "")
        contact_url = str(draft.get("contact_url") or "")
        if "@" in contact and contact_url and _host(contact_url) == _host(official):
            known.add(contact)
        hints = publisher_contact_hints(
            body[:1024 * 1024].decode("utf-8", errors="replace"), official, known, as_of
        )
        if not hints:
            return row, "no_owned_dated_business_invitation_found"
        hint = next((item for item in hints if item["contact"] == contact), hints[0])
        draft.update(
            best_channel="Email", channel_handle_or_url=hint["contact"],
            contact_url=resolved, contact_quote=hint["contact_quote"],
            contact_activity_url=resolved, contact_activity_quote=hint["contact_activity_quote"],
            contact_active_date=hint["contact_active_date"],
        )
        if draft.get("backup_handle_or_url", "").casefold() == hint["contact"].casefold():
            for field in ("backup_channel", "backup_handle_or_url", "backup_url", "backup_quote"):
                draft[field] = ""
        meta["auto_review_draft"] = draft
        meta["auto_evidence_missing"] = [kind for kind in PROOF_KINDS if not (
            draft.get(f"{kind}_url") and draft.get(f"{kind}_quote")
        )]
        meta["contact_evidence_recovery"] = {
            "as_of": as_of, "source_url": resolved,
            "source_fetched_at": fetched.isoformat(), "source_sha256": actual_hash,
            "episode_title": hint["episode_title"], "semantic_verdict": "UNREVIEWED",
            "note": "Preserved source snapshot; no new live fetch or email-deliverability claim.",
        }
        # Research recovery never changes an eligibility or qualification decision.
        return row, "dated_publisher_invitation_recovered"
    except (OSError, ValueError, TypeError, KeyError) as error:
        meta["contact_evidence_recovery_error"] = type(error).__name__
        return row, "source_unavailable_or_invalid"


def recover(queue: Path, cache: Path, destination: Path, as_of: str, resume: bool = False) -> dict:
    date.fromisoformat(as_of)
    original = queue.read_bytes()
    rows = json.loads(original)
    ids = [row["stable_creator_id"] for row in rows]
    if not rows or len(ids) != len(set(ids)):
        raise ValueError("Queue must contain nonempty, unique stable IDs")
    contract = {"queue_sha256": hashlib.sha256(original).hexdigest(), "as_of": as_of, "method": 1}
    contract_path = destination / "recovery_contract.json"
    if (destination / "report.json").exists():
        raise FileExistsError("Completed recovery is protected; choose a new output directory")
    if destination.exists():
        if not resume or not contract_path.exists() or json.loads(contract_path.read_text(encoding="utf-8")) != contract:
            raise ValueError("Resume requires the original queue and checked date")
    else:
        destination.mkdir(parents=True)
        write_text(contract_path, json.dumps(contract, indent=2))
    records = destination / "records"
    records.mkdir(exist_ok=True)
    started = time.perf_counter()
    results, jobs = [], []
    reused = 0
    for row in rows:
        key = hashlib.sha256(row["stable_creator_id"].encode()).hexdigest()
        path = records / f"{key}.json"
        if resume and path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            results.append((saved["record"], saved["result"]))
            reused += 1
        else:
            jobs.append((row, str(cache), as_of))
    with ProcessPoolExecutor(max_workers=4) as workers:
        for row, result in workers.map(recover_one, jobs, chunksize=5):
            key = hashlib.sha256(row["stable_creator_id"].encode()).hexdigest()
            write_text(records / f"{key}.json", json.dumps({"record": row, "result": result}, ensure_ascii=False))
            results.append((row, result))
            if len(results) % 100 == 0:
                progress = {"processed": len(results), "total": len(rows), "reused": reused}
                write_text(destination / "progress.json", json.dumps(progress))
                print(json.dumps(progress), flush=True)
    results.sort(key=lambda item: item[0]["stable_creator_id"])
    recovered = [row for row, _ in results]
    write_text(destination / "auto_enriched_queue.json", json.dumps(recovered, ensure_ascii=False))
    gaps = []
    proofs = []
    for row in recovered:
        meta = row.get("metadata", {})
        draft = meta.get("auto_review_draft", {})
        missing = meta.get("auto_evidence_missing", list(PROOF_KINDS))
        gaps.append({
            "stable_creator_id": row["stable_creator_id"], "creator_name": row["creator_name"],
            "missing_proofs": ";".join(missing), "proof_hints": 8 - len(missing),
            "country_hint": draft.get("country_iso2", ""),
            "primary_contact_hint": draft.get("channel_handle_or_url", ""),
            "contact_activity_date_hint": draft.get("contact_active_date", ""),
            "official_site": meta.get("official_site_url", ""), "my_decision": "",
        })
        for kind in PROOF_KINDS:
            url = draft.get(f"{kind}_url", "")
            snapshot = meta.get("auto_evidence_snapshots", {}).get(url, {})
            proofs.append({
                "stable_creator_id": row["stable_creator_id"], "check": kind, "url": url,
                "verbatim_snippet": draft.get(f"{kind}_quote", ""),
                "fetch_date": snapshot.get("retrieved_at", ""), "sha256": snapshot.get("sha256", ""),
                "semantic_verdict": "UNREVIEWED",
            })
    _write_csv(destination / "evidence_gaps.csv", gaps, list(gaps[0]))
    _write_csv(destination / "proof_hints.csv", proofs, list(proofs[0]))
    # Preserve URL aliases so the separate source-byte audit can reproduce redirected fetches.
    links = [check for row in recovered for check in row.get("metadata", {}).get("auto_link_checks", [])]
    _write_csv(destination / "link_checks.csv", links, list(links[0]) if links else [])
    report = {
        "as_of": as_of, "processed": len(recovered), "reused_checkpoints": reused,
        "results": dict(Counter(result for _, result in results)),
        "original_contact_activity_hints": sum(bool(row.get("metadata", {}).get("auto_review_draft", {}).get("contact_active_date")) for row in rows),
        "recovered_contact_activity_hints": sum(bool(row["contact_activity_date_hint"]) for row in gaps),
        "qualification_changes": 0, "network_requests": 0, "api_calls": 0,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "note": "Cached source-byte recovery only; every semantic claim awaits review and live recheck.",
    }
    write_text(destination / "report.json", json.dumps(report, indent=2))
    write_text(destination / "progress.json", json.dumps({"processed": len(rows), "total": len(rows), "completed": True}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".cache/http"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(recover(args.queue, args.cache, args.out, args.as_of, args.resume), indent=2))


if __name__ == "__main__":
    main()
