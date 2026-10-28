from incubrix_engine.models import Lead
from incubrix_engine.review_expansion import _identity, _score


def test_review_score_ranks_evidence_without_approving_candidate():
    lead = Lead(
        creator_name="Synthetic Creator",
        country_iso2="GB",
        content_count_30d=8,
        profile_url="https://example.test/profile",
        candidate_status="Rejected",
    )
    score, gaps = _score(lead)
    assert score == 45
    assert "commercial" in gaps and "backup_route" in gaps
    assert lead.candidate_status == "Rejected"
    assert _identity(lead)[0] == "syntheticcreator"
