import json

from incubrix_engine.delivery_support import outreach_issues, safe_drafts, write_outreach_support
from incubrix_engine.exporters import _write_csv


def test_personalized_draft_uses_exact_title_and_no_claim_of_watching():
    row = {
        "creator_name": "Alex Synthetic",
        "last_content_date": "2026-10-28",
        "metadata": {"activity_items": [{"title": "A specific synthetic lesson"}]},
    }
    draft = {**row, **safe_drafts(row)}
    assert outreach_issues(draft) == []
    assert "A specific synthetic lesson" in draft["first_message"]
    assert "watched" not in draft["first_message"]
    assert "generic_or_missing_specific_recent_title" in outreach_issues(
        {**draft, "first_message": "Hello, love your content"}
    )
    assert "unsubstantiated_personal_consumption_claim" in outreach_issues(
        {**draft, "first_message": "I watched your video"}
    )


def test_missing_content_cannot_become_invented_personalization(tmp_path):
    assert not safe_drafts({"creator_name": "Synthetic"})["first_message"]
    _write_csv(tmp_path / "leads.csv", [], ["lead_id"])
    _write_csv(tmp_path / "evidence_ledger.csv", [], ["lead_id"])
    result = write_outreach_support(tmp_path)
    assert result["priority_a_count"] == 0
    assert not result["best_25_marking_matches"]
    assert result["segment_channel_template_count"] == 9
    assert json.loads((tmp_path / "outreach/quality_report.json").read_text())["messages_sent"] == 0
