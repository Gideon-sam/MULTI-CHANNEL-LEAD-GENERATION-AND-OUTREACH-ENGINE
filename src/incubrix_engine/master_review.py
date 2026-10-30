"""Build one exact-size, evidence-first manual review workbook from preserved research runs."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .audit_support import read_rows
from .files import write_text
from .manual_decisions import load_decisions
from .models import Lead
from .review import PROOF_KINDS
from .review_expansion import _lead
from .review_workflow import export_review_workbook

HARD_FAILURES = (
    "no_dated_public_episodes_in_last_60_days",
    "no_recent_public_videos",
    "activity_threshold_not_met",
    "content_not_mainly_english",
)
APPROVED_COUNTRIES = {"US", "CA", "GB", "IE", "AU", "NZ", "SG"}


def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _proof_state(lead: Lead) -> tuple[int, list[str]]:
    draft = lead.metadata.get("auto_review_draft", {})
    if not isinstance(draft, dict):
        draft = {}
    missing = [
        kind
        for kind in PROOF_KINDS
        if not draft.get(f"{kind}_url") or not draft.get(f"{kind}_quote")
    ]
    return len(PROOF_KINDS) - len(missing), missing


def _eligible_youtube(lead: Lead) -> bool:
    return lead.stable_creator_id.startswith("youtube-channel:") and not any(
        reason in lead.rejection_reason for reason in HARD_FAILURES
    )


def _rank(lead: Lead, source: str) -> tuple:
    proof_count, _ = _proof_state(lead)
    activity = lead.content_count_30d >= 8 or lead.longform_count_60d >= 2
    return (
        source == "source_rechecked",
        lead.candidate_status == "Qualified",
        proof_count,
        activity,
        lead.country_iso2 in APPROVED_COUNTRIES,
        bool(lead.channel_handle_or_url),
        bool(lead.backup_channel),
        lead.lead_score,
    )


def _load_json(path: Path) -> list[Lead]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError(f"Expected a JSON array: {path}")
    return [Lead(**row) for row in payload]


def _source_reviewed_ids(path: Path) -> set[str]:
    return {row["stable_creator_id"] for row in read_rows(path)} if path.exists() else set()


def select_candidates(
    base: list[Lead],
    increment: list[Lead],
    youtube: list[Lead],
    rejected_ids: set[str],
    source_reviewed_ids: set[str],
    target: int,
) -> tuple[list[Lead], list[dict]]:
    staged = []
    for source, rows in (("base_research", base), ("incremental_research", increment)):
        staged.extend((row, "source_rechecked" if row.stable_creator_id in source_reviewed_ids else source) for row in rows)
    staged.extend((row, "youtube_research") for row in youtube if _eligible_youtube(row))
    best_by_id: dict[str, tuple[Lead, str]] = {}
    for lead, source in staged:
        if lead.stable_creator_id in rejected_ids:
            continue
        current = best_by_id.get(lead.stable_creator_id)
        if current is None or _rank(lead, source) > _rank(*current):
            best_by_id[lead.stable_creator_id] = (lead, source)
    ordered = sorted(best_by_id.values(), key=lambda item: _rank(*item), reverse=True)
    selected = []
    index = []
    seen_names = set()
    for lead, source in ordered:
        name = _normal_name(lead.creator_name)
        if not name or name in {"unknown", "none", "na"} or name in seen_names:
            continue
        seen_names.add(name)
        proof_count, missing = _proof_state(lead)
        selected.append(lead)
        index.append(
            {
                "review_rank": len(selected),
                "stable_creator_id": lead.stable_creator_id,
                "creator_name": lead.creator_name,
                "source_group": source,
                "current_engine_status": lead.candidate_status,
                "current_reason": lead.rejection_reason,
                "proof_hints_present": proof_count,
                "missing_proof_checks": ";".join(missing),
                "activity_gate_measured": "PASS" if lead.content_count_30d >= 8 or lead.longform_count_60d >= 2 else "UNRESOLVED",
                "country_hint": lead.country_iso2,
                "primary_contact_hint": lead.channel_handle_or_url,
                "backup_contact_hint": lead.backup_channel,
                "profile_url": lead.profile_url,
                "recent_content_url": lead.recent_content_url,
                "manual_decision": "",
                "manual_notes": "",
            }
        )
        if len(selected) == target:
            break
    if len(selected) != target:
        raise ValueError(f"Only {len(selected)} unique review candidates were available; need {target}")
    return selected, index


def _style_sheet(sheet, freeze: str = "A2") -> None:
    sheet.freeze_panes = freeze
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 85
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="123D45")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def _finish_workbook(path: Path, index: list[dict], counts: dict) -> None:
    book = openpyxl.load_workbook(path)
    summary = book.create_sheet("REVIEW_DASHBOARD", 0)
    summary.append(["IncuBrix 5,000-creator evidence review", "Measured value"])
    rows = [
        ("Rows in this workbook", counts["total"]),
        ("Source-rechecked; independent audit pending", counts["source_rechecked"]),
        ("Candidates requiring manual evidence review", counts["needs_review"]),
        ("User-rejected creators excluded", counts["user_rejected"]),
        ("Podcast candidates", counts["podcast"]),
        ("YouTube candidates", counts["youtube"]),
        ("Final qualified count", counts["qualified"]),
        ("Final random 40-row audit", "TODO after a qualified leads.csv exists"),
    ]
    for row in rows:
        summary.append(row)
    summary.append([])
    summary.append(["How to review", "Use REVIEW_INDEX to prioritize, then enter facts, proof URLs, exact excerpts and Approve/Reject only in Reviews. Every required proof must pass. Do not send outreach."])
    summary.append(["Approval rule", "Approve only an individual creator in an approved country who passes activity, English, commercial, workflow-need, active business-contact, separate backup, uniqueness and working-source checks."])
    summary.append(["Audit rule", "This workbook is a candidate review pool. It is not the final independent audit. Generate the fixed-seed 40-row audit from the final qualified leads.csv."])
    summary.column_dimensions["A"].width = 48
    summary.column_dimensions["B"].width = 120
    for row in summary.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    _style_sheet(summary, "A2")

    sheet = book.create_sheet("REVIEW_INDEX", 1)
    fields = list(index[0])
    sheet.append(fields)
    for item in index:
        row = sheet.max_row + 1
        for column, field in enumerate(fields, 1):
            cell = sheet.cell(row, column, item[field])
            if isinstance(item[field], str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=field in {"current_reason", "missing_proof_checks", "manual_notes"})
            if field.endswith("_url") and str(item[field]).startswith(("http://", "https://")):
                cell.hyperlink = item[field]
                cell.style = "Hyperlink"
    decision_col = fields.index("manual_decision") + 1
    validation = DataValidation(type="list", formula1='"Pending,Approve,Reject"')
    sheet.add_data_validation(validation)
    validation.add(f"{sheet.cell(2, decision_col).coordinate}:{sheet.cell(sheet.max_row, decision_col).coordinate}")
    for column, field in enumerate(fields, 1):
        sheet.column_dimensions[sheet.cell(1, column).column_letter].width = 45 if field.endswith("_url") else 24
    _style_sheet(sheet, "D2")
    book.active = 0
    book.properties.title = "IncuBrix 5,000 creator manual evidence review"
    book.save(path)
    book.close()


def build(
    base_queue: Path,
    increment_queue: Path,
    run: Path,
    decisions: Path,
    reviewed_leads: Path,
    destination: Path,
    target: int = 5000,
) -> dict:
    if destination.exists():
        raise FileExistsError("Choose a new destination; preserve reviewer edits")
    destination.mkdir(parents=True)
    base = _load_json(base_queue)
    increment = _load_json(increment_queue)
    youtube = []
    for name in ("leads.csv", "review_queue.csv", "rejections.csv"):
        youtube.extend(_lead(row) for row in read_rows(run / name) if row.get("stable_creator_id", "").startswith("youtube-channel:"))
    ledger = load_decisions(decisions)
    rejected_ids = {stable_id for stable_id, item in ledger.items() if item.get("decision") == "Reject"}
    source_reviewed = _source_reviewed_ids(reviewed_leads)
    selected, index = select_candidates(base, increment, youtube, rejected_ids, source_reviewed, target)
    queue = destination / "manual_review_queue_5000.json"
    write_text(queue, json.dumps([asdict(row) for row in selected], ensure_ascii=False))
    workbook = destination / "IncuBrix_Manual_Review_5000.xlsx"
    export_review_workbook(queue, workbook)
    counts = {
        "total": len(selected),
        "source_rechecked": sum(row["source_group"] == "source_rechecked" for row in index),
        "needs_review": sum(row["source_group"] != "source_rechecked" for row in index),
        "user_rejected": len(rejected_ids),
        "podcast": sum(row["stable_creator_id"].startswith("apple-podcast:") for row in index),
        "youtube": sum(row["stable_creator_id"].startswith("youtube-channel:") for row in index),
        "qualified": 0,
    }
    _finish_workbook(workbook, index, counts)
    report = {
        **counts,
        "workbook": str(workbook),
        "queue": str(queue),
        "qualification_changes": 0,
        "note": "Exactly 5,000 unique-name candidates are organized for review. Only a complete approval followed by live source recheck can enter final leads.csv.",
    }
    write_text(destination / "report.json", json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--increment", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, default=Path("config/review_decisions.json"))
    parser.add_argument("--reviewed-leads", type=Path, default=Path("output_reviewed_3000/leads.csv"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target", type=int, default=5000)
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.increment, args.run, args.decisions, args.reviewed_leads, args.out, args.target), indent=2))


if __name__ == "__main__":
    main()
