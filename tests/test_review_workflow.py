"""Synthetic .test records verify that a spreadsheet cannot silently approve discovery hints."""

import asyncio
import csv
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

import openpyxl
import pytest
from test_dedupe_and_validation import config, lead

from incubrix_engine.models import Lead, PodcastCandidate
from incubrix_engine.pipeline import run_pipeline
from incubrix_engine.review import PROOF_KINDS, load_reviews
from incubrix_engine.review_workflow import (
    REVIEW_COLUMNS,
    export_review_workbook,
    import_review_workbook,
)
from incubrix_engine.sources.apple_podcasts import EnrichmentResult
from incubrix_engine.workbook import build_workbook


def review_files(tmp_path):
    candidate = lead("apple-podcast:123", "Synthetic Tester", "owned@example.test", "US")
    candidate.candidate_status = "Needs review"
    candidate.creator_name = '=HYPERLINK("https://example.test","Synthetic")'
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps([asdict(candidate)]), encoding="utf-8")
    workbook = tmp_path / "review.xlsx"
    export_review_workbook(queue, workbook)
    reviews = tmp_path / "reviews.json"
    reviews.write_text('{"schema_version":1,"reviews":[]}', encoding="utf-8")
    return queue, workbook, reviews


def set_review(workbook_path, *, incomplete=False):
    book = openpyxl.load_workbook(workbook_path)
    sheet = book["Reviews"]
    values = {
        "decision": "Approve",
        "stable_creator_id": "apple-podcast:123",
        "creator_identity_key": "https://example.test/creator",
        "creator_name": "Synthetic Tester",
        "country_iso2": "US",
        "reviewer": "Synthetic test",
        "reviewed_at": "2026-10-26",
        "rationale": "Synthetic evidence",
        "best_channel": "Email",
        "channel_handle_or_url": "owned@example.test",
        "backup_channel": "Website",
        "backup_handle_or_url": "https://example.test/contact",
        "contact_active_date": "2026-10-25",
        "need_description": "Synthetic workflow evidence",
    }
    for kind in PROOF_KINDS:
        values[f"{kind}_url"] = "https://example.test/proof"
        values[f"{kind}_quote"] = "Synthetic evidence"
    if incomplete:
        values["country_quote"] = ""
    for column, name in enumerate(REVIEW_COLUMNS, 1):
        sheet.cell(2, column, values.get(name, ""))
    book.save(workbook_path)
    book.close()


def test_review_export_is_safe_and_never_auto_approves(tmp_path):
    queue, workbook, reviews = review_files(tmp_path)
    book = openpyxl.load_workbook(workbook)
    assert book["Reviews"]["A2"].value == "Pending"
    assert book["Candidates"]["B2"].data_type == "s"
    book.close()
    assert import_review_workbook(workbook, reviews, queue)["imported"] == 0
    assert load_reviews(reviews) == {}
    with pytest.raises(ValueError, match="preserve edits"):
        export_review_workbook(queue, workbook)


def test_review_import_is_atomic_and_idempotent(tmp_path):
    queue, workbook, reviews = review_files(tmp_path)
    before = reviews.read_bytes()
    set_review(workbook, incomplete=True)
    with pytest.raises(ValueError, match="country"):
        import_review_workbook(workbook, reviews, queue)
    assert reviews.read_bytes() == before
    set_review(workbook)
    assert import_review_workbook(workbook, reviews, queue)["imported"] == 1
    assert import_review_workbook(workbook, reviews, queue)["total_reviews"] == 1
    assert len(load_reviews(reviews)) == 1


def test_review_import_rejects_formula_and_unknown_identity(tmp_path):
    queue, workbook, reviews = review_files(tmp_path)
    set_review(workbook)
    book = openpyxl.load_workbook(workbook)
    book["Reviews"].cell(2, REVIEW_COLUMNS.index("rationale") + 1, "=1+1")
    book.save(workbook)
    book.close()
    with pytest.raises(ValueError, match="formulas"):
        import_review_workbook(workbook, reviews, queue)
    assert load_reviews(reviews) == {}


def test_full_workbook_keeps_all_2000_rows_and_duplicate_formulas(tmp_path):
    template = Path(__file__).parents[1] / "assets/IncuBrix_Submission_Workbook_Template.xlsx"
    rows = [lead(str(i), f"Synthetic {i}", f"owned-{i}@example.test", "US") for i in range(2000)]
    target = tmp_path / "submission.xlsx"
    build_workbook(template, target, rows, replace(config(), target_leads=2000), {})
    book = openpyxl.load_workbook(target)
    assert book["02_LEADS"]["A2004"].value == "1999"
    assert "$H$2004" in book["02_LEADS"]["AC5"].value
    assert "H2004" in book["02_LEADS"]["AC2004"].value
    assert book["02_LEADS"]["AD2004"].data_type == "f"
    assert "AA2004" in book["04_SELF_CHECK"]["D6"].value
    assert book["04_SELF_CHECK"]["C6"].value == 2000
    book.close()


def test_pipeline_finishes_other_sources_after_one_failure(tmp_path, monkeypatch):
    records = [
        PodcastCandidate(
            str(i),
            "Synthetic Person",
            "Synthetic Show",
            "",
            f"https://example.test/{i}",
            f"https://example.test/p/{i}",
            "Test",
        )
        for i in range(4)
    ]
    input_path = tmp_path / "input.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(records[0])))
        writer.writeheader()
        writer.writerows(asdict(row) for row in records)

    async def fake_enrich(candidate, *_args, **_kwargs):
        if candidate.apple_id == "2":
            raise OSError("Synthetic source unavailable")
        await asyncio.sleep(0.01)
        return EnrichmentResult(
            Lead(
                stable_creator_id=f"apple-podcast:{candidate.apple_id}",
                candidate_status="Needs review",
                checked_date="2026-10-26",
            )
        )

    monkeypatch.setattr("incubrix_engine.pipeline.enrich", fake_enrich)
    result = asyncio.run(
        run_pipeline(tmp_path, config(), logging.getLogger("test"), input_path=input_path)
    )
    assert result.metrics["pending_review"] == 3
    assert result.metrics["rejected"] == 1
    assert result.metrics["input_size"] == 4
    assert not result.all_checks_passed
    assert len(json.loads((tmp_path / "output/research_queue.json").read_text())) == 3
    assert (tmp_path / "output/Human_Review.xlsx").is_file()
    progress = json.loads((tmp_path / "output/progress.json").read_text())
    assert progress["status"] == "completed"
