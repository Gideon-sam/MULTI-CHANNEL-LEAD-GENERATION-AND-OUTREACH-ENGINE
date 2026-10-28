"""Expand conservative podcast discovery decisions into a ranked human-review pool."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, fields
from pathlib import Path

from .audit_support import metadata, read_rows
from .exporters import _write_csv
from .files import write_text
from .models import Lead, PodcastCandidate
from .review_workflow import export_review_workbook

SOFT_CREATOR_REASON = "not_clearly_creator_led"


def _lead(row: dict) -> Lead:
    values = {field.name: row.get(field.name, "") for field in fields(Lead)}
    values["metadata"] = metadata(row)
    for key in ("content_count_30d", "longform_count_60d"):
        values[key] = int(values.get(key) or 0)
    values["lead_score"] = float(values.get("lead_score") or 0)
    return Lead(**values)


def _score(lead: Lead) -> tuple[int, list[str]]:
    gaps = []
    points = 0
    checks = (
        ("approved_country", lead.country_iso2 in {"US", "CA", "GB", "IE", "AU", "NZ", "SG"}, 20),
        ("activity", lead.content_count_30d >= 8 or lead.longform_count_60d >= 2, 20),
        ("commercial", bool(lead.monetization_signal and lead.monetization_evidence_url), 15),
        ("need", bool(lead.incubrix_need and lead.need_evidence_url), 10),
        (
            "business_contact",
            bool(lead.best_channel and lead.channel_handle_or_url and lead.channel_evidence_url),
            15,
        ),
        ("backup_route", bool(lead.backup_channel), 10),
        ("official_profile", lead.profile_url.startswith(("http://", "https://")), 5),
        ("fresh_check", bool(lead.checked_date), 5),
    )
    for name, passed, weight in checks:
        if passed:
            points += weight
        else:
            gaps.append(name)
    return points, gaps


def _identity(lead: Lead) -> tuple[str, str]:
    return (
        re.sub(r"[^a-z0-9]", "", lead.creator_name.casefold()),
        lead.channel_handle_or_url.casefold().strip(),
    )


def _input_rows(discovery_path: Path, wanted: set[str]) -> list[dict]:
    rows = []
    allowed = list(PodcastCandidate.__dataclass_fields__)
    for row in read_rows(discovery_path):
        if row.get("stable_creator_id") not in wanted or not row.get("apple_id", "").isdigit():
            continue
        values = {key: row.get(key, "") for key in allowed}
        values["country_iso2"] = ""
        rows.append(values)
    return rows


def build(directory: Path, destination: Path, limit: int = 5000, batch_size: int = 500) -> dict:
    if destination.exists():
        raise FileExistsError("Expanded review directory already exists; preserve reviewer edits")
    existing = [_lead(row) for row in read_rows(directory / "review_queue.csv")]
    recovered = [
        _lead(row)
        for row in read_rows(directory / "rejections.csv")
        if row.get("rejection_reason") == SOFT_CREATOR_REASON
        and row.get("stable_creator_id", "").startswith("apple-podcast:")
    ]
    candidates = [
        lead
        for lead in [*existing, *recovered]
        if lead.stable_creator_id.startswith("apple-podcast:")
    ]
    ranked = []
    seen_ids = set()
    seen_names = set()
    seen_contacts = set()
    for lead in sorted(
        candidates, key=lambda item: (-_score(item)[0], -item.lead_score, item.stable_creator_id)
    ):
        name, contact = _identity(lead)
        if (
            lead.stable_creator_id in seen_ids
            or (name and name in seen_names)
            or (contact and contact in seen_contacts)
        ):
            continue
        seen_ids.add(lead.stable_creator_id)
        if name:
            seen_names.add(name)
        if contact:
            seen_contacts.add(contact)
        ranked.append(lead)
        if len(ranked) >= limit:
            break
    destination.mkdir(parents=True)
    payload = [asdict(lead) for lead in ranked]
    queue = destination / "expanded_review_queue.json"
    write_text(queue, json.dumps(payload, ensure_ascii=False, indent=2))
    summary_rows = []
    for lead in ranked:
        score, gaps = _score(lead)
        summary_rows.append(
            {
                "review_rank": len(summary_rows) + 1,
                "review_score": score,
                "missing_automated_fields": ";".join(gaps),
                "stable_creator_id": lead.stable_creator_id,
                "creator_name": lead.creator_name,
                "country_hint": lead.country_iso2,
                "profile_url": lead.profile_url,
                "recent_content_url": lead.recent_content_url,
                "commercial_hint": lead.monetization_signal,
                "contact_hint": lead.channel_handle_or_url,
                "current_reason": lead.rejection_reason,
                "manual_decision": "",
                "manual_notes": "",
            }
        )
    _write_csv(
        destination / "review_index.csv",
        summary_rows,
        list(summary_rows[0]) if summary_rows else [],
    )
    export_review_workbook(queue, destination / "Manual_Review_Master.xlsx")
    batch_files = []
    for start in range(0, len(payload), batch_size):
        batch_number = start // batch_size + 1
        batch_queue = destination / f"batch_{batch_number:02d}.json"
        batch_workbook = destination / f"Manual_Review_Batch_{batch_number:02d}.xlsx"
        write_text(
            batch_queue,
            json.dumps(payload[start : start + batch_size], ensure_ascii=False, indent=2),
        )
        export_review_workbook(batch_queue, batch_workbook)
        batch_files.append(batch_workbook.name)
    inputs = _input_rows(directory / "all_discovered_inputs.csv", seen_ids)
    input_path = destination / "expanded_input.csv"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PodcastCandidate.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(inputs)
    report = {
        "source_run": str(directory),
        "existing_pending_podcast_rows": sum(
            lead.stable_creator_id.startswith("apple-podcast:") for lead in existing
        ),
        "soft_creator_rows_recovered": len(recovered),
        "review_candidates_after_dedupe": len(ranked),
        "expanded_input_rows": len(inputs),
        "batch_size": batch_size,
        "batch_workbooks": batch_files,
        "qualification_changes": 0,
        "note": "Candidates remain unqualified until an Approve row supplies all eight exact proofs and the engine re-fetches them.",
    }
    write_text(destination / "report.json", json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.limit < 1 or args.batch_size < 1:
        parser.error("limit and batch-size must be positive")
    print(json.dumps(build(args.run, args.out, args.limit, args.batch_size), indent=2))


if __name__ == "__main__":
    main()
