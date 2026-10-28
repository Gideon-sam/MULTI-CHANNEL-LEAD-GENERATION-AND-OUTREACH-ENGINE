from dataclasses import asdict

import openpyxl

from incubrix_engine.bulk_evidence import Snapshot, auto_review_draft
from incubrix_engine.models import Lead
from incubrix_engine.review_workflow import REVIEW_COLUMNS, export_review_workbook


def test_auto_evidence_prefills_exact_hints_but_never_approves(tmp_path):
    feed = Snapshot(
        url="https://example.test/feed.xml",
        raw="<rss><language>en-US</language><author>Alex Smith</author><title>Recent Episode</title></rss>",
        visible="en-US Alex Smith Recent Episode",
        title="",
        fetched_at="2026-10-29T00:00:00+00:00",
        sha256="abc",
    )
    site = Snapshot(
        url="https://example.test/",
        raw=(
            "<html><title>Alex Smith</title><body>Alex Smith is based in Canada. "
            'Book coaching. <a href="mailto:alex@example.test">Email</a> '
            '<a href="https://linkedin.com/in/alex-smith">LinkedIn</a></body></html>'
        ),
        visible="Alex Smith is based in Canada. Book coaching. Email LinkedIn",
        title="Alex Smith",
        fetched_at="2026-10-29T00:00:00+00:00",
        sha256="def",
    )
    lead = Lead(
        stable_creator_id="apple-podcast:123",
        creator_name="Alex Smith",
        country_iso2="CA",
        source_feed_url=feed.url,
        channel_handle_or_url="alex@example.test",
        best_channel="Email",
        personalization_hook="Recent Episode",
        incubrix_need="Repurposing opportunity based on recent publishing",
        metadata={"official_site_url": site.url, "activity_items": [{"title": "Recent Episode"}]},
    )
    draft, missing = auto_review_draft(lead, [feed, site])
    assert draft["identity_quote"]
    assert draft["country_quote"]
    assert draft["language_quote"] == "en-US"
    assert draft["contact_quote"]
    assert draft["backup_handle_or_url"] == "https://linkedin.com/in/alex-smith"
    assert "contact_activity" in missing

    lead.metadata["auto_review_draft"] = draft
    queue = tmp_path / "queue.json"
    queue.write_text(__import__("json").dumps([asdict(lead)]), encoding="utf-8")
    workbook = tmp_path / "review.xlsx"
    export_review_workbook(queue, workbook)
    book = openpyxl.load_workbook(workbook, read_only=True)
    values = [cell.value for cell in book["Reviews"][2]]
    book.close()
    assert values[REVIEW_COLUMNS.index("decision")] == "Pending"
    assert values[REVIEW_COLUMNS.index("country_quote")]
