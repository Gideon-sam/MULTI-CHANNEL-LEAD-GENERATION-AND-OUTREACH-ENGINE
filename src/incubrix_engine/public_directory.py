"""Publish an explicit selection of workbook research fields for the creator directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import openpyxl

from .files import write_text
from .review import PROOF_KINDS


def public_url(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(c.isspace() for c in text)
            or any(
                key.casefold() in {"key", "api_key", "apikey", "token", "password", "secret"}
                for key, _ in parse_qsl(parsed.query)
            )
        ):
            return ""
        return text
    except ValueError:
        return ""


def _sheet_rows(book, name: str) -> list[dict]:
    iterator = book[name].iter_rows(values_only=True)
    headers = next(iterator)
    return [dict(zip(headers, row, strict=True)) for row in iterator if any(row)]


def _by_id(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for row in rows:
        stable_id = str(row.get("stable_creator_id") or "")
        if not stable_id or stable_id in result:
            raise ValueError("Every directory row must have a unique stable creator ID")
        result[stable_id] = row
    return result


def _number(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def build_directory(workbook: Path, destination: Path) -> dict:
    """Build versioned JSON, never promote workbook verdicts to qualification."""
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=False)
    try:
        index = _sheet_rows(book, "REVIEW_INDEX")
        candidates = _by_id(_sheet_rows(book, "Candidates"))
        reviews = _by_id(_sheet_rows(book, "Reviews"))
    finally:
        book.close()
    index_by_id = _by_id(index)
    if set(index_by_id) != set(candidates) or set(index_by_id) != set(reviews):
        raise ValueError("Directory sheets must contain the same stable IDs")

    summaries = []
    chunks: dict[int, dict] = {}
    missing_totals: Counter = Counter()
    for position, entry in enumerate(index):
        stable_id = entry["stable_creator_id"]
        candidate, review = candidates[stable_id], reviews[stable_id]
        proofs = []
        for kind in PROOF_KINDS:
            url = public_url(review.get(f"{kind}_url"))
            quote = str(review.get(f"{kind}_quote") or "")
            present = bool(url and quote.strip())
            proofs.append({"kind": kind, "url": url, "quote": quote, "present": present})
            if not present:
                missing_totals[kind] += 1
        missing = [p["kind"] for p in proofs if not p["present"]]
        count30, long60 = (
            _number(candidate.get("content_count_30d")),
            _number(candidate.get("longform_count_60d")),
        )
        activity_pass = (count30 is not None and count30 >= 8) or (
            long60 is not None and long60 >= 2
        )
        raw_verdict = str(entry.get("manual_decision") or "Pending")
        verdict = raw_verdict if raw_verdict in {"Approve", "Reject"} else "Pending"
        platform = "YouTube" if stable_id.startswith("youtube-channel:") else "Podcast"
        key = hashlib.sha256(stable_id.encode()).hexdigest()[:20]
        source_group = str(entry.get("source_group") or "")
        summary = {
            "id": stable_id,
            "key": key,
            "chunk": position // 100,
            "rank": entry.get("review_rank") or position + 1,
            "name": str(review.get("creator_name") or candidate.get("creator_name") or ""),
            "show": str(candidate.get("show") or ""),
            "platform": platform,
            "country": str(review.get("country_iso2") or candidate.get("country_hint") or ""),
            "verdict": verdict,
            "engine_status": str(entry.get("current_engine_status") or "Unresolved"),
            "source_group": source_group,
            "proof_count": len(PROOF_KINDS) - len(missing),
            "missing": missing,
            "activity_pass": activity_pass,
            "items30": count30,
            "long60": long60,
            "latest": str(candidate.get("last_content_date") or ""),
            "channel": str(review.get("best_channel") or ""),
            "contact": str(review.get("channel_handle_or_url") or candidate.get("contact_hint") or ""),
            "profile": public_url(candidate.get("profile_url")),
            "reason": str(entry.get("current_reason") or ""),
        }
        facts = {
            "official_site": public_url(candidate.get("official_site")),
            "canonical_identity": public_url(review.get("creator_identity_key")),
            "feed": public_url(candidate.get("source_feed_url")),
            "recent_content": public_url(candidate.get("recent_content_url")),
            "primary_contact": summary["contact"],
            "primary_contact_url": public_url(summary["contact"]),
            "backup_channel": str(review.get("backup_channel") or ""),
            "backup_contact": str(review.get("backup_handle_or_url") or ""),
            "backup_contact_url": public_url(review.get("backup_handle_or_url")),
            "contact_active_date": str(review.get("contact_active_date") or ""),
            "commercial": str(candidate.get("commercial_hint") or ""),
            "fit_reason": str(review.get("need_description") or candidate.get("need_inference") or ""),
            "checked_date": str(candidate.get("checked_date") or ""),
            "feed_fetched_at": str(candidate.get("feed_fetched_at") or ""),
            "feed_stale": candidate.get("feed_stale"),
            "possible_duplicate": str(candidate.get("possible_duplicate_creator") or ""),
            "import_decision": str(review.get("decision") or "Pending"),
            "messages": [str(candidate.get(f) or "") for f in (
                "first_message_draft", "follow_up_1_draft", "follow_up_2_draft"
            )],
        }
        # No arbitrary metadata, reviewer identities, credentials or account configuration.
        detail = {**summary, "facts": facts, "proofs": proofs}
        summaries.append(summary)
        chunks.setdefault(position // 100, {})[key] = detail

    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
    version = digest[:16]
    snapshot = destination / version
    stats = {
        "total": len(summaries),
        "user_approved": sum(r["verdict"] == "Approve" for r in summaries),
        "user_rejected": sum(r["verdict"] == "Reject" for r in summaries),
        "proof_complete": sum(r["proof_count"] == 8 for r in summaries),
        "activity_pass": sum(r["activity_pass"] for r in summaries),
        "platforms": dict(Counter(r["platform"] for r in summaries)),
        "missing_evidence": dict(missing_totals),
    }
    for number, rows in chunks.items():
        write_text(snapshot / f"details-{number}.json", json.dumps(rows, ensure_ascii=False, default=str))
    write_text(snapshot / "index.json", json.dumps({"stats": stats, "rows": summaries}, ensure_ascii=False, default=str))
    manifest = {
        "version": version,
        "index": f"{version}/index.json",
        "generated_at": datetime.now(UTC).isoformat(),
        "workbook_sha256": digest,
        "qualification_note": "User decisions and stored research; final qualification requires live source verification.",
    }
    write_text(destination / "manifest.json", json.dumps(manifest, indent=2))
    return {**stats, "version": version, "destination": str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_directory(args.workbook, args.out), indent=2))


if __name__ == "__main__":
    main()
