import json
from dataclasses import asdict

import openpyxl
import pytest

from incubrix_engine.manual_forms import CHECKS, FIRST_CHECK, convert_forms, export_forms
from incubrix_engine.models import Lead
from incubrix_engine.review import PROOF_KINDS, load_reviews


def make_forms(tmp_path):
    draft = {
        "creator_name": "=Synthetic Creator", "country_iso2": "GB",
        "creator_identity_key": "https://example.test/creator", "best_channel": "Email",
        "channel_handle_or_url": "business@example.test", "backup_channel": "Website",
        "backup_handle_or_url": "https://example.test/contact", "contact_active_date": "2026-10-28",
        "need_description": "Weekly editing workflow", "rationale": "Synthetic test rationale",
    }
    for kind in PROOF_KINDS:
        draft[f"{kind}_url"] = "https://example.test/proof"
        draft[f"{kind}_quote"] = "Synthetic evidence for " + kind
    row = asdict(Lead(stable_creator_id="synthetic:1", creator_name="=Synthetic Creator", metadata={
        "auto_review_draft": draft, "auto_evidence_missing": [],
    }))
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps([row]), encoding="utf-8")
    path = tmp_path / "review.xlsx"
    export_forms(queue, path)
    return queue, path


def test_forms_preserve_blank_verdicts_literal_text_and_existing_edits(tmp_path):
    queue, path = make_forms(tmp_path)
    book = openpyxl.load_workbook(path)
    assert book["INDEX"]["B2"].data_type == "s"
    assert book["Creator_001"]["B6"].data_type == "s"
    assert book["Creator_001"]["B16"].value == "Pending"
    assert all(book["Creator_001"].cell(i, 6).value is None for i in range(FIRST_CHECK, FIRST_CHECK + len(CHECKS)))
    book.close()
    with pytest.raises(FileExistsError):
        export_forms(queue, path)


def test_converter_requires_explicit_checks_then_preserves_all_evidence(tmp_path):
    _, path = make_forms(tmp_path)
    book = openpyxl.load_workbook(path)
    book["START_HERE"]["B10"] = "Synthetic reviewer"
    book["START_HERE"]["B11"] = "2026-10-29"
    book["Creator_001"]["B16"] = "Approve"
    book.save(path)
    with pytest.raises(ValueError, match="explicitly Pass"):
        convert_forms(path, tmp_path / "blocked.xlsx")
    assert not (tmp_path / "blocked.xlsx").exists()
    for row in range(FIRST_CHECK, FIRST_CHECK + len(CHECKS)):
        book["Creator_001"].cell(row, 6, "Pass")
    book.save(path)
    book.close()
    result = convert_forms(path, tmp_path / "converted.xlsx")
    assert result["approved_forms"] == 1
    reviews = load_reviews(tmp_path / "converted.validation.json")
    assert reviews["synthetic:1"]["creator_name"] == "=Synthetic Creator"
    assert reviews["synthetic:1"]["proofs"]["country"]["quote"] == "Synthetic evidence for country"


def test_converter_rejects_changed_identity(tmp_path):
    _, path = make_forms(tmp_path)
    book = openpyxl.load_workbook(path)
    book["Creator_001"]["B3"] = "unrelated:2"
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="Stable IDs"):
        convert_forms(path, tmp_path / "blocked.xlsx")
