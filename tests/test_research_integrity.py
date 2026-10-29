import gzip
import hashlib
import json

from incubrix_engine.research_integrity import check_source, restore_exported_snippets


def test_excel_escape_is_restored_only_when_original_checkpoint_matches(tmp_path):
    records = tmp_path / "records"
    records.mkdir()
    (records / "1.json").write_text(json.dumps({
        "stable_creator_id": "synthetic:1",
        "metadata": {"auto_review_draft": {
            "contact_quote": "=business@example.test",
            "backup_quote": "=https://example.test/contact",
        }},
    }), encoding="utf-8")
    claims = [
        {"stable_creator_id": "synthetic:1", "check": "contact",
         "verbatim_snippet": "'=business@example.test"},
        {"stable_creator_id": "synthetic:1", "check": "backup",
         "verbatim_snippet": "'=https://tampered.test/contact"},
    ]
    restore_exported_snippets(tmp_path, claims)
    assert claims[0]["verbatim_snippet"] == "=business@example.test"
    assert claims[1]["verbatim_snippet"] == "'=https://tampered.test/contact"


def test_integrity_detects_altered_sources_missing_quotes_and_stale_dates(tmp_path):
    url = "https://example.test/about"
    body = b"<p>Alex Smith offers business coaching.</p>"
    digest = hashlib.sha256((url + "?{}").encode()).hexdigest()
    (tmp_path / f"{digest}.body.gz").write_bytes(gzip.compress(body))
    (tmp_path / f"{digest}.json").write_text(
        json.dumps(
            {
                "status_code": 200,
                "fetched_at": 1793232000,
            }
        ),
        encoding="utf-8",
    )
    base = {
        "stable_creator_id": "synthetic:1",
        "check": "commercial",
        "url": url,
        "verbatim_snippet": "Alex Smith offers business coaching.",
        "sha256": hashlib.sha256(body).hexdigest(),
        "fetch_date": "2026-10-28T00:00:00+00:00",
    }
    claims = [
        base,
        {**base, "sha256": "different"},
        {**base, "verbatim_snippet": "Invented claim"},
        {**base, "fetch_date": "2025-01-01"},
    ]
    statuses = [
        row["integrity_status"] for row in check_source((url, claims, str(tmp_path), "2026-10-29"))
    ]
    assert statuses == [
        "exact_excerpt_and_snapshot_match",
        "source_snapshot_changed",
        "excerpt_not_found",
        "source_date_invalid_or_stale",
    ]


def test_integrity_follows_recorded_request_url_for_redirected_cache(tmp_path):
    requested, resolved = "http://example.test", "https://example.test/"
    body = b"Creator business contact"
    digest = hashlib.sha256((requested + "?{}").encode()).hexdigest()
    (tmp_path / f"{digest}.body.gz").write_bytes(gzip.compress(body))
    (tmp_path / f"{digest}.json").write_text(
        json.dumps({"status_code": 200, "fetched_at": 1793232000}), encoding="utf-8"
    )
    claim = {
        "stable_creator_id": "synthetic:2",
        "check": "contact",
        "requested_url": requested,
        "verbatim_snippet": "Creator business contact",
        "sha256": hashlib.sha256(body).hexdigest(),
        "fetch_date": "2026-10-28T00:00:00+00:00",
    }
    assert (
        check_source((resolved, [claim], str(tmp_path), "2026-10-29"))[0]["integrity_status"]
        == "exact_excerpt_and_snapshot_match"
    )
