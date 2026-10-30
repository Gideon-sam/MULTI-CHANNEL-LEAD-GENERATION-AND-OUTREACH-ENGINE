"""Record explicit user verdicts without inventing evidence or qualifying other rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .files import atomic_destination, write_text
from .manual_forms import CHECKS, FIELDS, FIRST_CHECK, FIRST_FIELD
from .models import Lead
from .review_workflow import _text_cell


def load_decisions(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("decisions"), list):
        raise ValueError("Invalid manual decision ledger")
    result = {}
    for item in data["decisions"]:
        stable_id = item.get("stable_creator_id", "")
        if not stable_id or stable_id in result or item.get("decision") not in {"Pending", "Approve", "Reject"}:
            raise ValueError("Invalid or duplicate manual decision")
        if item["decision"] == "Reject" and not item.get("reason"):
            raise ValueError("Rejected records need a reason")
        result[stable_id] = item
    return result


def apply_rejection(lead: Lead, decisions: dict[str, dict]) -> bool:
    decision = decisions.get(lead.stable_creator_id, {})
    if decision.get("decision") != "Reject":
        return False
    lead.candidate_status = "Rejected"
    lead.rejection_reason = "manual_rejection:missing_backup_contact"
    lead.completeness_check = "REJECTED BY REVIEWER"
    lead.metadata["manual_rejection"] = decision
    return True


def record_decisions(source: Path, destination: Path, ledger: Path, rejected_numbers: set[int],
                     passed_checks: set[str], reviewer: str, reviewed_at: str, reason: str) -> dict:
    date.fromisoformat(reviewed_at)
    if destination.exists():
        raise FileExistsError("Choose a new output; the existing review workbook is protected")
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer and the stated rejection reason are required")
    valid_checks = {kind for kind, _ in CHECKS}
    if not passed_checks <= valid_checks:
        raise ValueError("Unknown review check")
    original = source.read_bytes()
    book = openpyxl.load_workbook(source)
    decisions = load_decisions(ledger)
    recorded = []
    try:
        forms = [s for s in book if s.title.startswith("Creator_")]
        numbers = {int(s.title.split("_")[1]) for s in forms}
        if not rejected_numbers <= numbers:
            raise ValueError("Rejected number does not exist in this workbook")
        mapping = dict(book["_FORM_MAP"].iter_rows(min_row=4, max_col=2, values_only=True))
        book["START_HERE"]["B10"] = reviewer
        book["START_HERE"]["B11"] = reviewed_at
        for sheet in forms:
            number = int(sheet.title.split("_")[1])
            stable_id = sheet["B3"].value
            if mapping.get(sheet.title) != stable_id:
                raise ValueError("Workbook stable IDs changed; resolve before recording decisions")
            if any(sheet.cell(FIRST_FIELD + i, 1).value != label for i, (_, label) in enumerate(FIELDS)):
                raise ValueError("Workbook fields changed; preserve their original layout")
            checks = {}
            for row, (kind, _) in enumerate(CHECKS, FIRST_CHECK):
                if sheet.cell(row, 1).value != kind:
                    raise ValueError("Workbook check rows changed")
                if kind in passed_checks:
                    sheet.cell(row, 6, "Pass")
                    existing_note = str(sheet.cell(row, 7).value or "")
                    sheet.cell(row, 7, existing_note + f" User-attested Pass by {reviewer} on {reviewed_at}; no new engine fetch implied.")
                if number in rejected_numbers and kind == "backup":
                    sheet.cell(row, 6, "Fail")
                    sheet.cell(row, 7, reason)
                checks[kind] = str(sheet.cell(row, 6).value or "")
            if number in rejected_numbers:
                sheet["B16"] = "Reject"
                sheet["B15"] = reason
            decision = str(sheet["B16"].value or "Pending")
            entry = {
                "stable_creator_id": stable_id, "creator_name": sheet["B6"].value,
                "form_number": number, "decision": decision,
                "reason": reason if number in rejected_numbers else "Only explicitly stated check verdicts recorded; other evidence remains unresolved.",
                "reviewer": reviewer, "reviewed_at": reviewed_at, "checks": checks,
                "source": "User instruction in conversation", "source_workbook_sha256": hashlib.sha256(original).hexdigest(),
            }
            decisions[stable_id] = entry
            recorded.append(entry)
            sheet.sheet_view.showGridLines = False
        summary_name = "REVIEW_SUMMARY"
        if summary_name in book.sheetnames:
            raise ValueError("Workbook already has a review summary; preserve it and use the original input")
        summary = book.create_sheet(summary_name, 1)
        summary.append(["No.", "Creator", "Decision", "Freshness / links", "Backup", "Checks still unset", "Open form", "Reason"])
        for entry in recorded:
            row = summary.max_row + 1
            values = [entry["form_number"], entry["creator_name"], entry["decision"], entry["checks"]["freshness_links"], entry["checks"]["backup"], sum(not v for v in entry["checks"].values()), "OPEN FORM", entry["reason"]]
            for column, value in enumerate(values, 1):
                cell = _text_cell(summary, row, column, value)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            summary.cell(row, 7).hyperlink = f"#'Creator_{entry['form_number']:03d}'!A1"
            summary.cell(row, 7).style = "Hyperlink"
            summary.cell(row, 3).fill = PatternFill("solid", fgColor="F8CBAD" if entry["decision"] == "Reject" else "FFF2CC")
            summary.row_dimensions[row].height = 48
        summary.freeze_panes = "C2"
        summary.auto_filter.ref = summary.dimensions
        summary.sheet_view.showGridLines = False
        summary.sheet_view.zoomScale = 85
        for cell in summary[1]:
            cell.fill, cell.font = PatternFill("solid", fgColor="123D45"), Font(bold=True, color="FFFFFF")
            summary.column_dimensions[cell.column_letter].width = 22
        summary.column_dimensions["A"].width = 7
        summary.column_dimensions["B"].width = 40
        summary.column_dimensions["H"].width = 65
        book.active = book.sheetnames.index(summary_name)
        with atomic_destination(destination) as temporary:
            book.save(temporary)
        write_text(ledger, json.dumps({"schema_version": 1, "decisions": list(decisions.values())}, indent=2, ensure_ascii=False))
    finally:
        book.close()
    return {"workbook": str(destination), "recorded": len(recorded), "rejected": len(rejected_numbers),
            "freshness_pass": sum(r["checks"]["freshness_links"] == "Pass" for r in recorded),
            "backup_pass": sum(r["checks"]["backup"] == "Pass" for r in recorded),
            "new_qualified_leads": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=Path("config/review_decisions.json"))
    parser.add_argument("--reject", type=int, action="append", required=True)
    parser.add_argument("--pass-check", action="append", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    print(json.dumps(record_decisions(args.input, args.out, args.ledger, set(args.reject), set(args.pass_check), args.reviewer, args.reviewed_at, args.reason), indent=2))


if __name__ == "__main__":
    main()
