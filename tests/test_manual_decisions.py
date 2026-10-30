import json

import openpyxl
import pytest
from test_manual_forms import make_forms

from incubrix_engine.manual_decisions import apply_rejection, load_decisions, record_decisions
from incubrix_engine.models import Lead


def test_recording_user_checks_preserves_original_and_other_verdicts(tmp_path):
    _, source = make_forms(tmp_path)
    original = source.read_bytes()
    out, ledger = tmp_path / "recorded.xlsx", tmp_path / "decisions.json"
    result = record_decisions(source, out, ledger, {1}, {"freshness_links", "backup"}, "Synthetic reviewer", "2026-10-30", "No backup contact per reviewer")
    assert source.read_bytes() == original
    assert result["rejected"] == 1 and result["new_qualified_leads"] == 0
    book = openpyxl.load_workbook(out)
    assert book["Creator_001"]["B16"].value == "Reject"
    assert book["Creator_001"]["F30"].value == "Fail"
    assert book["Creator_001"]["F34"].value == "Pass"
    assert book["Creator_001"]["F23"].value is None
    book.close()
    lead = Lead(stable_creator_id="synthetic:1", candidate_status="Qualified")
    assert apply_rejection(lead, load_decisions(ledger))
    assert lead.candidate_status == "Rejected"
    with pytest.raises(FileExistsError):
        record_decisions(source, out, ledger, {1}, {"freshness_links"}, "Reviewer", "2026-10-30", "Reason")


def test_pending_decision_never_qualifies_a_lead(tmp_path):
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps({"schema_version": 1, "decisions": [{"stable_creator_id": "synthetic:1", "decision": "Pending"}]}), encoding="utf-8")
    lead = Lead(stable_creator_id="synthetic:1", candidate_status="Needs review")
    assert not apply_rejection(lead, load_decisions(path))
    assert lead.candidate_status == "Needs review"
