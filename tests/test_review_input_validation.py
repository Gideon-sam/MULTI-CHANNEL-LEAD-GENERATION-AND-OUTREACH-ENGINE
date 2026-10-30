import json

import pytest

from incubrix_engine.review import _public_url, _route_key, load_reviews


def review_fixture():
    return {
        "stable_creator_id": "synthetic:1", "creator_identity_key": "https://example.test/",
        "reviewer": "Synthetic reviewer", "reviewed_at": "2026-10-30", "rationale": "Test only",
        "creator_name": "Synthetic Creator", "country_iso2": "GB", "best_channel": "Email",
        "channel_handle_or_url": "owned@example.test", "backup_channel": "Website",
        "backup_handle_or_url": "https://example.test/contact", "contact_active_date": "2026-10-29",
        "need_description": "Synthetic editing workflow",
        "proofs": {kind: {"url": "https://example.test/proof", "quote": "Synthetic evidence"} for kind in
                   ("identity", "country", "language", "commercial", "need", "contact", "contact_activity", "backup")},
    }


@pytest.mark.parametrize("field,value", [
    ("reviewed_at", "30-10-2026"), ("contact_active_date", "2026-02-30"),
    ("contact_active_date", "2026-10-31"), ("creator_identity_key", "https://[broken"),
])
def test_bad_review_inputs_are_rejected_before_network_access(tmp_path, field, value):
    review = review_fixture()
    review[field] = value
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps({"schema_version": 1, "reviews": [review]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_reviews(path)


@pytest.mark.parametrize("value", ["https://[broken", "https://example.test:bad", "https://example.test:99999", "https://user:secret@example.test", "https://example.test/a b"])
def test_malformed_public_urls_return_false(value):
    assert not _public_url(value)


def test_equivalent_urls_do_not_create_fake_backup_routes():
    assert _route_key("https://www.example.test/contact/") == _route_key("http://example.test/contact#form")
    assert _route_key("Business@Example.test") == _route_key("business@example.test")
    assert _route_key("https://example.test/contact") != _route_key("https://example.test/booking")
