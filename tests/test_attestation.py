import json
from dataclasses import asdict
from pathlib import Path

import openpyxl

from incubrix_engine.attestation import record_attestation
from incubrix_engine.master_review import _finish_workbook
from incubrix_engine.models import Lead
from incubrix_engine.review import PROOF_KINDS
from incubrix_engine.review_workflow import export_review_workbook


def test_attestation_records_user_verdict_without_qualifying_or_editing_reviews(tmp_path):
    queue = tmp_path / "queue.json"
    candidate = Lead(
        stable_creator_id="apple-podcast:1",
        creator_name="Example Creator",
        country_iso2="US",
        best_channel="Website",
        channel_handle_or_url="https://example.test/contact",
        profile_url="https://example.test/creator",
        source_feed_url="https://example.test/feed",
        recent_content_url="https://example.test/item",
    )
    queue.write_text(json.dumps([asdict(candidate)]), encoding="utf-8")
    source = tmp_path / "source.xlsx"
    export_review_workbook(queue, source)
    _finish_workbook(
        source,
        [
            {
                "review_rank": 1,
                "stable_creator_id": "apple-podcast:1",
                "creator_name": "Example Creator",
                "source_group": "test",
                "current_engine_status": "Needs review",
                "current_reason": "",
                "proof_hints_present": 0,
                "missing_proof_checks": "country",
                "activity_gate_measured": "PASS",
                "country_hint": "US",
                "primary_contact_hint": "https://example.test/contact",
                "backup_contact_hint": "",
                "profile_url": "https://example.test/creator",
                "recent_content_url": "https://example.test/item",
                "manual_decision": "",
                "manual_notes": "",
            }
        ],
        {"total": 1, "source_rechecked": 0, "needs_review": 1, "user_rejected": 0,
         "podcast": 1, "youtube": 0, "qualified": 0},
    )
    destination = tmp_path / "attested.xlsx"
    result = record_attestation(
        source,
        destination,
        count=1,
        reviewer="Human Reviewer",
        reviewed_at="2026-10-31",
        note="I manually reviewed this candidate and approve the candidate-level verdict.",
    )

    assert result["attested"] == 1
    assert result["evidence_complete"] == 0
    assert result["engine_qualified"] == 0
    book = openpyxl.load_workbook(destination, read_only=True)
    assert book["REVIEW_INDEX"]["O2"].value == "Approve"
    assert "does not bypass evidence" in book["REVIEW_INDEX"]["P2"].value
    assert book["Reviews"]["A2"].value == "Pending"
    assert book["ATTESTATION_SUMMARY"]["B4"].value == 1
    book.close()
    assert Path(result["destination"]) == destination


def test_attestation_matches_evidence_by_id_when_sheets_have_different_order(tmp_path):
    source = tmp_path / "reordered.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "REVIEW_DASHBOARD"
    index = book.create_sheet("REVIEW_INDEX")
    index.append(["stable_creator_id", "manual_decision", "manual_notes"])
    index.append(["synthetic:selected", "Pending", ""])
    index.append(["synthetic:other", "Pending", ""])
    reviews = book.create_sheet("Reviews")
    headers = ["stable_creator_id"]
    for kind in PROOF_KINDS:
        headers.extend([f"{kind}_url", f"{kind}_quote"])
    reviews.append(headers)
    reviews.append(["synthetic:other"] + [None] * 16)
    reviews.append(["synthetic:selected"] + ["https://example.test", "Exact excerpt"] * 8)
    book.save(source)
    book.close()
    result = record_attestation(
        source, tmp_path / "recorded.xlsx", count=1, reviewer="Test reviewer",
        reviewed_at="2026-10-31", note="Reviewed the first index record",
    )
    assert result["evidence_complete"] == 1
    assert result["engine_qualified"] == 0
