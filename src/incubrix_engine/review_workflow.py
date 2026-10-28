"""Editable evidence handoff. Exported hints never imply an approval decision."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .files import atomic_destination, write_text
from .review import PROOF_KINDS, REVIEW_FIELDS, load_reviews

REVIEW_COLUMNS = ["decision", *REVIEW_FIELDS]
for _kind in PROOF_KINDS:
    REVIEW_COLUMNS.extend((f"{_kind}_url", f"{_kind}_quote"))


def _text_cell(sheet, row, column, value):
    # Untrusted publisher text must not become an Excel formula.
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def _make_clickable(cell) -> None:
    value = str(cell.value or "")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
        cell.hyperlink = value
        cell.style = "Hyperlink"


def export_review_workbook(queue_path: Path, destination: Path) -> dict:
    if destination.exists():
        raise ValueError(
            f"Review workbook exists; choose a new output to preserve edits: {destination}"
        )
    rows = json.loads(queue_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise TypeError("Review queue must be a JSON array")
    # Surface candidates with more research signals first. These remain unverified hints.
    rows.sort(
        key=lambda r: (
            -sum(
                bool(r.get(k))
                for k in ("country_iso2", "channel_handle_or_url", "monetization_signal")
            ),
            -r.get("lead_score", 0),
            r["stable_creator_id"],
        )
    )
    book = openpyxl.Workbook()
    instructions = book.active
    instructions.title = "START_HERE"
    for text in [
        "HUMAN REVIEW REQUIRED - these are research candidates, not qualified leads.",
        "Aim: approve only evidence-complete creators; three countries; maximum 60% in one country.",
        "Candidates contains automated findings and links. Treat country/contact as hints.",
        "Reviews contains one row per candidate. Verify and correct the prefilled values.",
        "Enter a canonical creator identity (e.g. official website) shared across their shows.",
        "Fill reviewer, reviewed_at (YYYY-MM-DD), rationale and actual contact_active_date.",
        "Provide a second public business route and a specific observed workflow need.",
        "Each of eight claims needs a working public URL and an exact short excerpt (max 400 chars).",
        "Country must describe the creator, not a guest; contact must be intended for business.",
        "The contact and backup excerpts must contain the exact address or handle/URL.",
        "Set decision to Approve only after checking all evidence. Other rows are not imported.",
        "Import with: python -m incubrix_engine review import --workbook <saved-file.xlsx>",
        "Then: python -m incubrix_engine run --input inputs/cached_discovery_expanded.csv --reviewed-only",
        "Import records decisions; the run rechecks sources before anything reaches leads.csv.",
        "Do not contact creators. Owned-account seed tests and product/video evidence are separate.",
    ]:
        instructions.append([text])
    instructions.column_dimensions["A"].width = 125
    candidates = book.create_sheet("Candidates")
    candidate_columns = [
        "stable_creator_id",
        "creator_name",
        "show",
        "country_hint",
        "contact_hint",
        "official_site",
        "profile_url",
        "source_feed_url",
        "recent_content_url",
        "last_content_date",
        "content_count_30d",
        "longform_count_60d",
        "commercial_hint",
        "commercial_source",
        "contact_source",
        "country_source",
        "country_method",
        "need_inference",
        "first_message_draft",
        "follow_up_1_draft",
        "follow_up_2_draft",
        "checked_date",
        "feed_fetched_at",
        "feed_stale",
        "possible_duplicate_creator",
    ]
    candidates.append(candidate_columns)
    reviews = book.create_sheet("Reviews")
    reviews.append(REVIEW_COLUMNS)
    seen_names: dict[str, str] = {}
    for number, row in enumerate(rows, 2):
        meta = row.get("metadata", {})
        name_key = re.sub(r"[^a-z0-9]", "", row["creator_name"].casefold())
        possible_duplicate = seen_names.get(name_key, "") if name_key else ""
        if name_key:
            seen_names.setdefault(name_key, row["stable_creator_id"])
        values = [
            row["stable_creator_id"],
            row["creator_name"],
            meta.get("collection_name", ""),
            row["country_iso2"],
            row["channel_handle_or_url"],
            meta.get("official_site_url", ""),
            row["profile_url"],
            row["source_feed_url"],
            row["recent_content_url"],
            row["last_content_date"],
            row["content_count_30d"],
            row["longform_count_60d"],
            row["monetization_signal"],
            row["monetization_evidence_url"],
            row["channel_evidence_url"],
            meta.get("country_evidence_url", ""),
            meta.get("country_evidence_method", ""),
            row["incubrix_need"],
            row["first_message"],
            row["follow_up_1"],
            row["follow_up_2"],
            row["checked_date"],
            meta.get("feed_fetched_at", ""),
            meta.get("feed_stale", ""),
            possible_duplicate,
        ]
        for column, value in enumerate(values, 1):
            cell = _text_cell(candidates, number, column, value)
            if candidate_columns[column - 1].endswith(("_url", "_source")) or candidate_columns[
                column - 1
            ] in {"official_site", "profile_url", "source_feed_url", "recent_content_url"}:
                _make_clickable(cell)
        draft = {
            "decision": "Pending",
            "stable_creator_id": row["stable_creator_id"],
            "creator_name": row["creator_name"],
            "country_iso2": row["country_iso2"],
            "best_channel": row["best_channel"],
            "channel_handle_or_url": row["channel_handle_or_url"],
            "identity_url": meta.get("official_site_url", ""),
            "country_url": meta.get("country_evidence_url", ""),
            "language_url": row["source_feed_url"],
            "commercial_url": row["monetization_evidence_url"],
            "need_url": row["need_evidence_url"],
            "need_quote": (meta.get("activity_items") or [{}])[0].get("title", ""),
            "contact_url": row["channel_evidence_url"],
            "contact_quote": row["channel_handle_or_url"],
        }
        auto_draft = meta.get("auto_review_draft", {})
        if isinstance(auto_draft, dict):
            for key, value in auto_draft.items():
                if key in REVIEW_COLUMNS and key not in {"decision", "stable_creator_id"}:
                    draft[key] = value
        for column, key in enumerate(REVIEW_COLUMNS, 1):
            cell = _text_cell(reviews, number, column, draft.get(key, ""))
            if key.endswith("_url") or key == "channel_handle_or_url":
                _make_clickable(cell)
    decision = DataValidation(type="list", formula1='"Pending,Approve,Reject"')
    reviews.add_data_validation(decision)
    if rows:
        decision.add(f"A2:A{len(rows) + 1}")
    for sheet in (candidates, reviews):
        sheet.freeze_panes = "C2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="123D45")
            sheet.column_dimensions[cell.column_letter].width = 28
        sheet.sheet_view.zoomScale = 85
    with atomic_destination(destination) as temporary:
        book.save(temporary)
    book.close()
    return {"workbook": str(destination), "pending_candidates": len(rows), "approved": 0}


def import_review_workbook(workbook_path: Path, reviews_path: Path, queue_path: Path) -> dict:
    known = {r["stable_creator_id"] for r in json.loads(queue_path.read_text(encoding="utf-8"))}
    existing = load_reviews(reviews_path)
    known.update(existing)
    book = openpyxl.load_workbook(workbook_path, read_only=True, data_only=False)
    accepted = {}
    errors = []
    try:
        if "Reviews" not in book.sheetnames:
            raise ValueError("Workbook lacks the Reviews sheet")
        iterator = book["Reviews"].iter_rows()
        headers = [cell.value for cell in next(iterator)]
        if headers != REVIEW_COLUMNS:
            raise ValueError("Reviews columns were changed; use the exported workbook headers")
        for number, cells in enumerate(iterator, 2):
            if str(cells[0].value or "").strip().casefold() != "approve":
                continue
            if any(cell.data_type == "f" for cell in cells):
                errors.append(f"Row {number}: formulas are not evidence; paste literal text")
                continue
            values = {}
            for key, cell in zip(headers, cells, strict=True):
                value = cell.value
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()[:10]
                values[key] = str(value or "").strip()
            stable_id = values["stable_creator_id"]
            if stable_id not in known or stable_id in accepted:
                errors.append(f"Row {number}: unknown or duplicate stable ID {stable_id}")
                continue
            review = {key: values[key] for key in REVIEW_FIELDS}
            review["proofs"] = {
                kind: {"url": values[f"{kind}_url"], "quote": values[f"{kind}_quote"]}
                for kind in PROOF_KINDS
            }
            accepted[stable_id] = review
    finally:
        book.close()
    if errors:
        raise ValueError("Import rejected without changing reviews: " + "; ".join(errors[:20]))
    if not accepted:
        return {"imported": 0, "total_reviews": len(existing), "note": "No Approve rows"}
    merged = {**existing, **accepted}
    payload = json.dumps({"schema_version": 1, "reviews": list(merged.values())}, indent=2)
    # Validate the entire proposed file before replacing the working review ledger.
    with atomic_destination(reviews_path) as temporary:
        temporary.write_text(payload, encoding="utf-8")
        load_reviews(temporary)
        if reviews_path.exists():
            backup = reviews_path.with_suffix(".json.bak")
            write_text(backup, reviews_path.read_text(encoding="utf-8"))
    return {
        "imported": len(accepted),
        "total_reviews": len(merged),
        "source_recheck_required": True,
    }
