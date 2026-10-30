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


def test_converter_rejects_changed_queue_before_writing_outputs(tmp_path):
    queue, path = make_forms(tmp_path)
    queue.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="Source queue changed"):
        convert_forms(path, tmp_path / "blocked.xlsx")
    assert not (tmp_path / "blocked.xlsx").exists()
    assert not (tmp_path / "blocked.validation.json").exists()


@pytest.mark.parametrize("change", ["decision", "field", "check", "formula"])
def test_accidental_workbook_changes_fail_with_clear_errors(tmp_path, change):
    _, path = make_forms(tmp_path)
    book = openpyxl.load_workbook(path)
    sheet = book["Creator_001"]
    if change == "decision":
        sheet["B16"] = "Approoved"
    elif change == "field":
        sheet.insert_rows(7)
    elif change == "check":
        sheet["A23"] = "different check"
    else:
        sheet["B6"] = '=HYPERLINK("https://example.test")'
    book.save(path)
    book.close()
    with pytest.raises(ValueError):
        convert_forms(path, tmp_path / "blocked.xlsx")


def test_offset_batch_is_reproducible_and_does_not_repeat_candidates(tmp_path):
    queue, _path = make_forms(tmp_path)
    rows = json.loads(queue.read_text(encoding="utf-8"))
    rows.append({**rows[0], "stable_creator_id": "synthetic:2"})
    queue.write_text(json.dumps(rows), encoding="utf-8")
    other = tmp_path / "batch2.xlsx"
    export_forms(queue, other, limit=1, offset=1)
    book = openpyxl.load_workbook(other)
    assert book["Creator_001"]["B3"].value == "synthetic:2"
    book.close()
    with pytest.raises(ValueError, match="offset"):
        export_forms(queue, tmp_path / "invalid.xlsx", offset=10)
