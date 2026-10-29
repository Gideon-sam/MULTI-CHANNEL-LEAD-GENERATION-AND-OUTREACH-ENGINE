import gzip
import hashlib
import json

from incubrix_engine.research_integrity import check_source


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
