"""Readable per-creator forms; approvals require explicit verdicts and complete evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .files import atomic_destination
from .review import PROOF_KINDS, REVIEW_FIELDS, load_reviews
from .review_workflow import REVIEW_COLUMNS, _make_clickable, _text_cell

FIELDS = [
    ("creator_name", "Creator's real/public professional name"),
    ("country_iso2", "Creator country: US, CA, GB, IE, AU, NZ or SG"),
    ("creator_identity_key", "Canonical official creator URL (same person across shows)"),
    ("best_channel", "Best business channel: Email, Website, LinkedIn, Instagram, etc."),
    ("channel_handle_or_url", "Exact public business email or full contact URL"),
    ("backup_channel", "Backup channel type"),
    ("backup_handle_or_url", "Exact, different backup contact address or URL"),
    ("contact_active_date", "Date proving the primary contact was active: YYYY-MM-DD"),
    ("need_description", "Specific content-workflow need; label any supported inference"),
    ("rationale", "Your reason for approving/rejecting; explain corrections or uncertainty"),
    ("decision", "Final decision: Approve only after every check below passes"),
]
CHECKS = [
    ("identity", "Real creator, official profile, stable ID; not an agency, publication or generic brand."),
    ("country", "Location describes THIS creator, not a guest, storefront or audience."),
    ("language", "Recent content is mainly English; inspect the actual content."),
    ("commercial", "Creator's own sponsorship, service, course, product, membership or similar."),
    ("need", "Specific evidence of creation, editing, repurposing or publishing/workflow need."),
    ("contact", "Exact public primary contact is offered for business and belongs to this creator."),
    ("contact_activity", "Evidence the chosen contact was active within 60 days; not only an RSS owner tag."),
    ("backup", "A second usable public contact route; not a share/review link."),
    ("activity", "8 content items in 30 days OR 2 long-form items in 60 days. Check dates and durations."),
    ("personalization", "Draft names a recent piece, identifies the independent sender and includes opt-out."),
    ("complete_unique", "Details refer to one creator; note other shows/duplicate identities. Engine rechecks globally."),
    ("freshness_links", "Evidence checked within 30 days; links open to relevant content, not errors or login screens."),
]
FIRST_FIELD = 6
FIRST_CHECK = 23
HEADER_ROW = 22
YELLOW = PatternFill("solid", fgColor="FFF2CC")
BLUE = PatternFill("solid", fgColor="E8F1F7")
DARK = PatternFill("solid", fgColor="123D45")


def _link(sheet, address, target, label):
    cell = _text_cell(sheet, *openpyxl.utils.cell.coordinate_to_tuple(address), label)
    cell.hyperlink = target
    cell.style = "Hyperlink"


def export_forms(queue: Path, destination: Path, limit: int = 40) -> dict:
    if destination.exists():
        raise FileExistsError("Choose a new workbook; existing human edits are protected")
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = json.loads(queue.read_text(encoding="utf-8"))
    integrity = {}
    integrity_path = queue.parent / "integrity_checked" / "excerpt_integrity.csv"
    if integrity_path.exists():
        with integrity_path.open(encoding="utf-8-sig", newline="") as handle:
            integrity = {(r["stable_creator_id"], r["check"]): r["integrity_status"] for r in csv.DictReader(handle)}
    rows.sort(key=lambda r: (
        len(r.get("metadata", {}).get("auto_evidence_missing", PROOF_KINDS)),
        -bool(r.get("metadata", {}).get("auto_review_draft", {}).get("country_iso2")),
        r["stable_creator_id"],
    ))
    selected = rows[:limit]
    book = openpyxl.Workbook()
    start = book.active
    start.title = "START_HERE"
    instructions = {
        1: "MANUAL CREATOR REVIEW — evidence hints are not approval",
        2: "1. Enter your name in B10 and your actual review date (YYYY-MM-DD) in B11.",
        3: "2. Open INDEX, click a creator, then review that creator's form. Work on the first 5 initially.",
        4: "3. Yellow cells are editable. Correct facts, evidence URLs and exact excerpts. Blue cells are supplied context.",
        5: "4. Mark every check Pass, Fail or Unsure in column F. If a source is missing or inaccessible, use Unsure.",
        6: "5. Set the final decision in B16: Approve only if all checks pass; Reject for a known failure; otherwise Pending.",
        7: "6. Save this .xlsx file and tell Codex it is ready. Do not export CSV, rename sheets, or change stable IDs.",
        8: "This is a prioritized evidence-review batch, NOT a random audit. Passing it cannot approve the other candidates.",
        10: "Your name (required once for the batch)",
        11: "Your actual review date (YYYY-MM-DD; required once)",
        13: "Missing proof requires a working public URL AND a short verbatim excerpt (maximum 400 characters). Do not guess.",
        14: "No creator outreach. Viewing public pages is enough. Followers/subscribers are optional; email is not mandatory.",
        15: "Country mix is checked on the FINAL list: >=80% approved markets, >=3 countries, no country >60%.",
        16: "The engine currently defines long-form as >=10 minutes. This is its documented convention; the PDF gives no minute cutoff.",
        17: "Imported approvals are re-fetched and checked by the engine; checking a box alone does not make a lead qualified.",
        18: "Activity dates and source fetch dates are different. A recent episode does not automatically prove an active contact.",
        19: "A different country or ambiguous long-form case should remain Pending with your notes for PDF interpretation.",
    }
    for number, text in instructions.items():
        start.cell(number, 1, text)
        start.row_dimensions[number].height = 38
        start.cell(number, 1).alignment = Alignment(wrap_text=True, vertical="top")
    start.column_dimensions["A"].width = 110
    start.column_dimensions["B"].width = 35
    for cell in ("B10", "B11"):
        start[cell].fill = YELLOW
        start[cell].number_format = "@"
    index = book.create_sheet("INDEX")
    index.append(["Number", "Creator", "Proof hints / 8", "Missing proof hints", "Open form", "Stable ID"])
    activity = book.create_sheet("ACTIVITY")
    activity.append(["Stable ID", "Creator", "Content title", "Published", "Minutes", "Content URL"])
    manifest = book.create_sheet("_FORM_MAP")
    manifest.append(["schema_version", 1])
    manifest.append(["queue", str(queue)])
    manifest.append(["queue_sha256", hashlib.sha256(queue.read_bytes()).hexdigest()])
    for number, row in enumerate(selected, 1):
        meta = row.get("metadata", {})
        draft = meta.get("auto_review_draft", {})
        sheet = book.create_sheet(f"Creator_{number:03d}")
        manifest.append([sheet.title, row["stable_creator_id"]])
        missing = meta.get("auto_evidence_missing", list(PROOF_KINDS))
        index.append([number, row["creator_name"], 8 - len(missing), ", ".join(missing), "OPEN", row["stable_creator_id"]])
        for cell in index[index.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
        _link(index, f"E{number + 1}", f"#'{sheet.title}'!A1", "OPEN FORM")
        _link(sheet, "A1", "#'INDEX'!A1", "BACK TO INDEX")
        _text_cell(sheet, 2, 1, f"{number}. {row['creator_name']} — VERIFY, DO NOT ASSUME")
        _text_cell(sheet, 3, 1, "Stable ID — do not change")
        _text_cell(sheet, 3, 2, row["stable_creator_id"])
        _text_cell(sheet, 4, 1, "Yellow = your facts/verdicts. Existing text is an unverified hint.")
        for offset, (key, label) in enumerate(FIELDS, FIRST_FIELD):
            _text_cell(sheet, offset, 1, label)
            value = "Pending" if key == "decision" else draft.get(key, "")
            cell = _text_cell(sheet, offset, 2, value)
            cell.fill = YELLOW
            cell.number_format = "@"
            sheet.row_dimensions[offset].height = 60 if key in {"need_description", "rationale"} else 45
        decisions = DataValidation(type="list", formula1='"Pending,Approve,Reject"')
        sheet.add_data_validation(decisions)
        decisions.add("B16")
        for number_row, (label, url) in enumerate([
            ("Official website", meta.get("official_site_url", "")),
            ("Platform profile", row.get("profile_url", "")),
            ("Publisher feed", row.get("source_feed_url", "")),
        ], 18):
            _text_cell(sheet, number_row, 1, label)
            _make_clickable(_text_cell(sheet, number_row, 2, url))
        headings = ["Check", "What you must verify", "Evidence URL", "Exact source excerpt", "Fetched (UTC)", "Your verdict", "Your notes"]
        for column, value in enumerate(headings, 1):
            sheet.cell(HEADER_ROW, column, value)
        verdicts = DataValidation(type="list", formula1='"Pass,Fail,Unsure"')
        sheet.add_data_validation(verdicts)
        verdicts.add(f"F{FIRST_CHECK}:F{FIRST_CHECK + len(CHECKS) - 1}")
        for number_row, (kind, rule) in enumerate(CHECKS, FIRST_CHECK):
            url = draft.get(f"{kind}_url", "")
            quote = draft.get(f"{kind}_quote", "")
            fetched = meta.get("auto_evidence_snapshots", {}).get(url, {}).get("retrieved_at", "")
            if kind == "activity":
                url = row.get("source_feed_url", "")
                quote = f"Engine counts as of {row.get('checked_date')}: {row.get('content_count_30d')} in 30d; {row.get('longform_count_60d')} long-form in 60d. See ACTIVITY sheet; verify dates."
            if kind == "personalization":
                url, quote = row.get("recent_content_url", ""), row.get("first_message", "")
            status = integrity.get((row["stable_creator_id"], kind), "")
            note = ""
            if kind in PROOF_KINDS:
                if not url or not quote:
                    note = "MISSING PROOF: find a source and exact excerpt, or mark Unsure."
                elif status and status != "exact_excerpt_and_snapshot_match":
                    note = f"SOURCE WARNING: {status}. Recheck and correct before passing."
            for column, value in enumerate([kind, rule, url, quote, fetched, "", note], 1):
                cell = _text_cell(sheet, number_row, column, value)
                cell.fill = YELLOW if column in {3, 4, 6, 7} else BLUE
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            _make_clickable(sheet.cell(number_row, 3))
            sheet.row_dimensions[number_row].height = 100
        sheet.freeze_panes = "C5"
        sheet.sheet_view.zoomScale = 75
        for column, width in {"A": 29, "B": 48, "C": 40, "D": 65, "E": 23, "F": 15, "G": 38}.items():
            sheet.column_dimensions[column].width = width
        for r in range(FIRST_FIELD, FIRST_FIELD + len(FIELDS)):
            for cell in sheet[r][:2]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        for cell in sheet[HEADER_ROW]:
            cell.fill, cell.font = DARK, Font(color="FFFFFF", bold=True)
        sheet.print_options.horizontalCentered = True
        sheet.page_setup.orientation = "landscape"
        for item in meta.get("activity_items", []):
            activity.append([row["stable_creator_id"], row["creator_name"], item.get("title"), item.get("date"), item.get("duration_minutes"), item.get("url")])
            for cell in activity[activity.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
            _make_clickable(activity.cell(activity.max_row, 6))
    for sheet in (index, activity):
        sheet.freeze_panes = "C2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill, cell.font = DARK, Font(color="FFFFFF", bold=True)
            sheet.column_dimensions[cell.column_letter].width = 30
        sheet.column_dimensions["B"].width = 42
        sheet.column_dimensions["D"].width = 48
    manifest.sheet_state = "hidden"
    with atomic_destination(destination) as temporary:
        book.save(temporary)
    book.close()
    return {"workbook": str(destination), "forms": len(selected), "pool": len(rows), "human_verdicts_filled": 0}


def convert_forms(source: Path, destination: Path) -> dict:
    """Prepare the existing import format without writing to the live review ledger."""
    if destination.exists() or destination.with_suffix(".validation.json").exists():
        raise FileExistsError("Existing converted workbook is protected")
    book = openpyxl.load_workbook(source, data_only=False)
    output = openpyxl.Workbook()
    reviews = output.active
    reviews.title = "Reviews"
    reviews.append(REVIEW_COLUMNS)
    approvals = []

    def literal(cell):
        if cell.data_type == "f":
            raise ValueError("Formulas are not accepted as review evidence")
        value = cell.value
        if hasattr(value, "isoformat"):
            return value.isoformat()[:10]
        return str(value or "").strip()

    try:
        mapping = book["_FORM_MAP"]
        if mapping["A1"].value != "schema_version" or mapping["B1"].value != 1:
            raise ValueError("Unknown form schema")
        seen = set()
        for name, stable_id in mapping.iter_rows(min_row=4, max_col=2, values_only=True):
            sheet = book[name]
            if literal(sheet["B3"]) != stable_id or stable_id in seen:
                raise ValueError("Stable IDs were changed or duplicated")
            seen.add(stable_id)
            values = {key: literal(sheet.cell(FIRST_FIELD + i, 2)) for i, (key, _) in enumerate(FIELDS)}
            if values["decision"].casefold() != "approve":
                continue
            for i, (kind, _) in enumerate(CHECKS, FIRST_CHECK):
                if literal(sheet.cell(i, 6)).casefold() != "pass":
                    raise ValueError(f"{name}: {kind} must explicitly Pass before approval")
                if kind in PROOF_KINDS:
                    values[f"{kind}_url"] = literal(sheet.cell(i, 3))
                    values[f"{kind}_quote"] = literal(sheet.cell(i, 4))
            values.update(stable_creator_id=stable_id, reviewer=literal(book["START_HERE"]["B10"]), reviewed_at=literal(book["START_HERE"]["B11"]))
            review = {key: values[key] for key in REVIEW_FIELDS}
            review["proofs"] = {kind: {"url": values[f"{kind}_url"], "quote": values[f"{kind}_quote"]} for kind in PROOF_KINDS}
            approvals.append(review)
            for column, key in enumerate(REVIEW_COLUMNS, 1):
                _text_cell(reviews, reviews.max_row + 1 if column == 1 else reviews.max_row, column, values.get(key, ""))
        # Reuse full structural validation before emitting anything importable.
        with atomic_destination(destination.with_suffix(".validation.json")) as temporary:
            temporary.write_text(json.dumps({"schema_version": 1, "reviews": approvals}), encoding="utf-8")
            load_reviews(temporary)
        with atomic_destination(destination) as temporary:
            output.save(temporary)
    finally:
        book.close()
        output.close()
    return {"approved_forms": len(approvals), "converted_workbook": str(destination), "source_recheck_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "convert"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    result = export_forms(args.input, args.out, args.limit) if args.action == "export" else convert_forms(args.input, args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
