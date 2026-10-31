from incubrix_engine.dashboard import write_dashboard
from incubrix_engine.models import Lead


def test_dashboard_is_interactive_responsive_and_escapes_embedded_markup(tmp_path):
    lead = Lead(
        creator_name="Alex </script><script>alert(1)</script>",
        stable_creator_id="synthetic:1",
        candidate_status="Needs review",
        primary_platform="YouTube",
    )
    destination = tmp_path / "dashboard.html"
    write_dashboard(
        [],
        [lead],
        [],
        {"qualified": 0, "pending_review": 1, "rejected": 0, "run_metrics": {"target_leads": 5000}},
        destination,
    )
    html = destination.read_text(encoding="utf-8")
    assert "IncuBrix Evidence Desk" in html
    assert 'id="platform"' in html and 'id="sort"' in html and 'id="theme"' in html
    assert "@media(max-width:650px)" in html
    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
