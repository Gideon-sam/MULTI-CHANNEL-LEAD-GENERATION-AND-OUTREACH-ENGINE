"""Build a compact, readable workbook from one immutable production run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .audit_support import read_rows
from .files import atomic_destination

NAVY = "172033"
BLUE = "315BD6"
GREEN = "DDF4E4"
RED = "FCE0E0"
AMBER = "FFF0C2"
LIGHT = "F4F6FA"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _title(sheet, text: str, subtitle: str) -> None:
    sheet["A1"] = text
    sheet["A1"].font = Font(size=20, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor=NAVY)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)
    sheet["A2"] = subtitle
    sheet["A2"].font = Font(size=10, color="4B5563")
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=10)
    sheet.sheet_view.showGridLines = False


def _table(sheet, headers: list[str], rows: list[list], start: int = 4) -> None:
    for column, header in enumerate(headers, 1):
        cell = sheet.cell(start, column, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row_index, values in enumerate(rows, start + 1):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_index, column, value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if row_index % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=LIGHT)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                cell.hyperlink = value
                cell.font = Font(color="0563C1", underline="single")
    sheet.freeze_panes = sheet.cell(start + 1, 1)
    if rows:
        sheet.auto_filter.ref = f"A{start}:{get_column_letter(len(headers))}{start + len(rows)}"
    for index, header in enumerate(headers, 1):
        width = 18
        lowered = header.lower()
        if (
            "url" in lowered
            or "message" in lowered
            or "evidence" in lowered
            or "excerpt" in lowered
        ):
            width = 46
        elif "name" in lowered or "reason" in lowered or "check" in lowered:
            width = 28
        sheet.column_dimensions[get_column_letter(index)].width = width


def _overview(book: Workbook, directory: Path) -> None:
    status = _json(directory / "submission_status.json")
    validation = _json(directory / "validation_report.json")
    sheet = book.active
    sheet.title = "00_OVERVIEW"
    _title(sheet, "IncuBrix reviewer pack", "Real measured results from the current immutable run")
    rows = [
        ["Current run", status.get("output_directory", str(directory)), "INFO"],
        ["Engine-qualified creators", status.get("engine_qualified_rows"), "FAIL: target is 2,000"],
        ["Pending evidence review", status.get("pending_rows"), "REVIEW QUEUE"],
        ["Rejected", status.get("rejected_rows"), "INFO"],
        ["Priority A", status.get("priority_a_rows"), "PASS"],
        ["Human audit pass rate", status.get("human_audit_pass_rate"), "TODO"],
        ["Submission ready", status.get("submission_ready"), "FAIL"],
    ]
    _table(sheet, ["Metric", "Measured value", "Status"], rows)
    start = 14
    checks = validation.get("checks", [])
    _table(
        sheet,
        ["PDF / engine check", "Passed", "Measured value", "Requirement"],
        [
            [row.get("name"), row.get("passed"), row.get("value"), row.get("requirement")]
            for row in checks
        ],
        start,
    )
    for row in range(5, 5 + len(rows)):
        value = str(sheet.cell(row, 3).value)
        color = RED if "FAIL" in value else AMBER if "TODO" in value or "REVIEW" in value else GREEN
        sheet.cell(row, 3).fill = PatternFill("solid", fgColor=color)


def _leads(book: Workbook, directory: Path) -> None:
    selected = [
        "lead_id",
        "creator_name",
        "creator_segment",
        "country_iso2",
        "primary_platform",
        "profile_url",
        "stable_creator_id",
        "last_content_date",
        "recent_content_url",
        "content_count_30d",
        "longform_count_60d",
        "monetization_signal",
        "monetization_evidence_url",
        "incubrix_need",
        "need_evidence_url",
        "best_channel",
        "channel_handle_or_url",
        "channel_evidence_url",
        "backup_channel",
        "priority",
        "lead_score",
        "candidate_status",
    ]
    rows = read_rows(directory / "leads.csv")
    sheet = book.create_sheet("01_QUALIFIED_LEADS")
    _title(
        sheet,
        "Qualified lead export",
        "Engine-qualified records; complete the independent audit before submission",
    )
    _table(sheet, selected, [[row.get(key, "") for key in selected] for row in rows])


def _audit(book: Workbook, directory: Path, sample_name: str) -> None:
    selected = [
        "lead_id",
        "creator_name",
        "country_iso2",
        "profile_url",
        "recent_content_url",
        "best_channel",
        "channel_handle_or_url",
        "backup_channel",
        "content_count_30d",
        "longform_count_60d",
        "monetization_evidence_url",
        "need_evidence_url",
        "channel_evidence_url",
        "my_verdict_identity",
        "my_verdict_country",
        "my_verdict_language",
        "my_verdict_activity",
        "my_verdict_commercial",
        "my_verdict_need",
        "my_verdict_contact",
        "my_verdict_contact_activity",
        "my_verdict_backup",
        "my_verdict_personalized",
        "my_verdict_complete_unique",
        "my_verdict_freshness",
        "my_verdict_working_sources",
        "my_channel_correct",
        "my_contact_correct",
        "my_notes",
    ]
    rows = read_rows(directory / sample_name)
    sheet = book.create_sheet("02_AUDIT_40")
    _title(
        sheet,
        "Independent 40-row audit",
        "Enter PASS or FAIL only after opening the evidence sources",
    )
    _table(sheet, selected, [[row.get(key, "") for key in selected] for row in rows])
    for column, key in enumerate(selected, 1):
        if key.startswith("my_"):
            sheet.column_dimensions[get_column_letter(column)].width = 18
            for row in range(5, 5 + len(rows)):
                sheet.cell(row, column).fill = PatternFill("solid", fgColor=AMBER)


def _evidence(book: Workbook, directory: Path) -> None:
    source = directory / "evidence_research_20261028/fetched_evidence.csv"
    rows = read_rows(source)
    headers = [
        "stable_creator_id",
        "creator_name",
        "url",
        "resolved_url",
        "discovery_basis",
        "status",
        "http_status",
        "fetched_at",
        "page_title",
        "excerpt",
        "public_contact_links",
        "content_dates",
        "review_warning",
    ]
    sheet = book.create_sheet("03_FETCHED_EVIDENCE")
    _title(
        sheet,
        "Fetched public evidence",
        "Exact page text and fetch metadata; interpretation is still required",
    )
    _table(sheet, headers, [[row.get(key, "") for key in headers] for row in rows])


def _rejections(book: Workbook, directory: Path) -> None:
    report = _json(directory / "rejection_report.json")
    headers = ["reason", "source", "country", "count"]
    rows = report.get("grouped", [])
    sheet = book.create_sheet("04_REJECTIONS")
    _title(sheet, "Grouped rejection report", "Counts by reason, source and country")
    _table(sheet, headers, [[row.get(key, "") for key in headers] for row in rows])


def _manual(book: Workbook, directory: Path) -> None:
    status = _json(directory / "submission_status.json")
    rows = [
        [
            "Product evidence",
            "Use IncuBrix and record 5 observations with screenshots or links",
            "TODO",
        ],
        [
            "Growth opportunities",
            "Write the 3 biggest opportunities based on actual product use",
            "TODO",
        ],
        [
            "Audit",
            f"Review {status.get('audit_sample_rows', 0)} sample rows and fill verdicts",
            "TODO",
        ],
        [
            "Seed tests",
            "Use only your own test accounts on email plus 2 other channels; capture proof",
            "TODO",
        ],
        ["Video 1", "Record an unedited product walkthrough up to 5 minutes", "TODO"],
        ["Video 2", "Record an unedited technical demo up to 8 minutes", "TODO"],
        [
            "Identity",
            "Replace [YOUR NAME], complete declaration, and provide private reviewer access",
            "TODO",
        ],
    ]
    sheet = book.create_sheet("05_MANUAL_TODOS")
    _title(sheet, "Candidate-only work", "These items require your own actions and evidence")
    _table(sheet, ["Item", "Exact action", "Status"], rows)
    for row in range(5, 5 + len(rows)):
        sheet.cell(row, 3).fill = PatternFill("solid", fgColor=AMBER)


def build(directory: Path, destination: Path) -> None:
    status = _json(directory / "submission_status.json")
    sample_name = status.get("audit_sample", "")
    if not sample_name:
        raise ValueError("submission_status.json does not name an audit sample")
    book = Workbook()
    try:
        _overview(book, directory)
        _leads(book, directory)
        _audit(book, directory, sample_name)
        _evidence(book, directory)
        _rejections(book, directory)
        _manual(book, directory)
        book.properties.title = "IncuBrix reviewer pack"
        book.properties.subject = "Measured leads, audit, evidence and manual TODOs"
        with atomic_destination(destination) as temporary:
            book.save(temporary)
    finally:
        book.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.run, args.out)
    print(json.dumps({"workbook": str(args.out), "source_run": str(args.run)}, indent=2))


if __name__ == "__main__":
    main()
