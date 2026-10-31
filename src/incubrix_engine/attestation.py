"""Record a reviewer's bulk attestation without bypassing evidence qualification gates."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .files import atomic_destination
from .review import PROOF_KINDS


def _headers(sheet) -> dict[str, int]:
    return {
        str(cell.value or "").strip(): cell.column
        for cell in sheet[1]
        if str(cell.value or "").strip()
    }


def record_attestation(
    source: Path,
    destination: Path,
    *,
    count: int,
    reviewer: str,
    reviewed_at: str,
    note: str,
) -> dict:
    """Copy the workbook and record human verdicts in REVIEW_INDEX only.

    The importable Reviews sheet remains untouched. A reviewer attestation is useful audit
    provenance, but it is not a substitute for the eight evidence URL/excerpt pairs required by
    the qualification engine.
    """
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    if count < 1:
        raise ValueError("Attestation count must be positive")
    try:
        date.fromisoformat(reviewed_at)
    except ValueError:
        raise ValueError("reviewed_at must be YYYY-MM-DD") from None
    if not reviewer.strip() or not note.strip():
        raise ValueError("reviewer and note are required")

    book = openpyxl.load_workbook(source)
    try:
        required = {"REVIEW_DASHBOARD", "REVIEW_INDEX", "Reviews"}
        missing_sheets = required.difference(book.sheetnames)
        if missing_sheets:
            raise ValueError(f"Workbook lacks sheets: {', '.join(sorted(missing_sheets))}")

        index = book["REVIEW_INDEX"]
        index_headers = _headers(index)
        required_index = {"stable_creator_id", "manual_decision", "manual_notes"}
        if not required_index.issubset(index_headers):
            raise ValueError("REVIEW_INDEX lacks attestation columns")
        available = index.max_row - 1
        if count > available:
            raise ValueError(f"Attestation count {count} exceeds {available} candidates")

        statement = (
            f"User attestation recorded {reviewed_at} by {reviewer.strip()}: {note.strip()} "
            "This verdict does not bypass evidence or live-source qualification gates."
        )
        for row in range(2, count + 2):
            decision = index.cell(row, index_headers["manual_decision"], "Approve")
            decision.data_type = "s"
            notes = index.cell(row, index_headers["manual_notes"], statement)
            notes.data_type = "s"

        reviews = book["Reviews"]
        review_headers = _headers(reviews)
        evidence_complete = 0
        for row in range(2, count + 2):
            complete = all(
                str(reviews.cell(row, review_headers[f"{kind}_url"]).value or "").strip()
                and str(reviews.cell(row, review_headers[f"{kind}_quote"]).value or "").strip()
                for kind in PROOF_KINDS
            )
            evidence_complete += int(complete)

        if "ATTESTATION_SUMMARY" in book.sheetnames:
            del book["ATTESTATION_SUMMARY"]
        summary = book.create_sheet("ATTESTATION_SUMMARY", 1)
        rows = [
            ("User review attestation", "Measured value"),
            ("Reviewer", reviewer.strip()),
            ("Review date", reviewed_at),
            ("Rows marked Approve in REVIEW_INDEX", count),
            ("Attested rows with all eight stored URL/excerpt pairs", evidence_complete),
            ("Attested rows still missing stored evidence", count - evidence_complete),
            ("Engine-qualified by this action", 0),
            ("Reviewer statement", note.strip()),
            (
                "Important",
                (
                    "The attestation is preserved as reviewer provenance. Reviews remains "
                    "unchanged; only evidence-complete rows can be imported and live-source "
                    "rechecked."
                ),
            ),
        ]
        for item in rows:
            summary.append(item)
        summary.freeze_panes = "A2"
        summary.sheet_view.showGridLines = False
        summary.column_dimensions["A"].width = 56
        summary.column_dimensions["B"].width = 110
        for cell in summary[1]:
            cell.fill = PatternFill("solid", fgColor="123D45")
            cell.font = Font(bold=True, color="FFFFFF")
        for row in summary.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        dashboard = book["REVIEW_DASHBOARD"]
        dashboard.append(["User-attested approvals", count])
        dashboard.append(["Evidence-complete among attested rows", evidence_complete])
        dashboard.append(["Engine-qualified by attestation", 0])
        dashboard.append(
            [
                "Attestation status",
                (
                    "Recorded in REVIEW_INDEX; final qualification still requires complete "
                    "evidence and live source recheck."
                ),
            ]
        )
        book.active = book.sheetnames.index("ATTESTATION_SUMMARY")
        with atomic_destination(destination) as temporary:
            book.save(temporary)
    finally:
        book.close()
    return {
        "attested": count,
        "evidence_complete": evidence_complete,
        "evidence_incomplete": count - evidence_complete,
        "engine_qualified": 0,
        "destination": str(destination),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--note", required=True)
    args = parser.parse_args()
    print(
        record_attestation(
            args.input,
            args.output,
            count=args.count,
            reviewer=args.reviewer,
            reviewed_at=args.date,
            note=args.note,
        )
    )


if __name__ == "__main__":
    main()
