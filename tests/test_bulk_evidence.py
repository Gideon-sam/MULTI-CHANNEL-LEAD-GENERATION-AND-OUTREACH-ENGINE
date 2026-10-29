from dataclasses import asdict

import openpyxl

from incubrix_engine.bulk_evidence import (
    Snapshot,
    _activity_contact_proof,
    _country_names_creator,
    _routes,
    auto_review_draft,
)
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
        last_content_date="2026-10-28",
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
    assert draft["contact_active_date"] == ""

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


def test_rss_owner_and_publication_do_not_certify_active_business_contact():
    feed = Snapshot(
        "https://example.test/rss",
        "<rss>owner@example.test 2026-10-28</rss>",
        "Business contact owner@example.test 2026-10-28",
        "",
        "",
        "",
    )
    assert _activity_contact_proof([feed], "owner@example.test", "2026-10-29") == ("", "", "")


def test_contact_activity_uses_its_own_observed_date_and_rejects_old_dates():
    page = Snapshot(
        "https://example.test/contact",
        "",
        "Business contact alex@example.test updated 2026-10-20",
        "",
        "",
        "",
    )
    assert _activity_contact_proof([page], "alex@example.test", "2026-10-29")[2] == "2026-10-20"
    assert _activity_contact_proof([page], "alex@example.test", "2027-01-29") == ("", "", "")


def test_social_share_and_book_listing_are_not_contact_routes():
    page = Snapshot(
        "https://example.test/",
        '<a href="https://x.com/intent/tweet?text=a">Share</a><a href="https://example.test/books">Books</a>',
        "",
        "",
        "",
        "",
    )
    assert _routes([page]) == []


def test_staff_location_is_not_used_as_creator_location():
    assert not _country_names_creator("Alex Smith", "Our editor Jane lives in London.")
    assert _country_names_creator("Alex Smith", "Alex Smith is based in Canada.")
