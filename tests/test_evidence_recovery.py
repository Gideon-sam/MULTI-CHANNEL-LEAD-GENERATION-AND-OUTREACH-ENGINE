import gzip
import hashlib
import json
from datetime import UTC, datetime

from incubrix_engine.evidence_recovery import recover_one


def make_cache(tmp_path):
    url = "https://feed.example.test/rss"
    body = b'''<rss><channel><item><title>Recent creator episode</title>
    <pubDate>Wed, 28 Oct 2026 18:00:00 +0000</pubDate><description><![CDATA[
    <p>Business inquiries: hello@creator.test</p>]]></description></item></channel></rss>'''
    digest = hashlib.sha256((url + "?{}").encode()).hexdigest()
    (tmp_path / f"{digest}.body.gz").write_bytes(gzip.compress(body))
    (tmp_path / f"{digest}.json").write_text(json.dumps({
        "url": url, "status_code": 200, "fetched_at": datetime(2026, 10, 29, tzinfo=UTC).timestamp(),
    }), encoding="utf-8")
    row = {"stable_creator_id": "synthetic:1", "creator_name": "Synthetic Creator", "candidate_status": "Needs review", "source_feed_url": url,
           "metadata": {"official_site_url": "https://creator.test", "auto_review_draft": {},
                        "auto_evidence_snapshots": {url: {"sha256": hashlib.sha256(body).hexdigest(), "retrieved_at": "2026-10-29T00:00:00+00:00"}}}}
    return row, body


def test_recovery_preserves_dates_hashes_and_pending_status(tmp_path):
    row, body = make_cache(tmp_path)
    result, status = recover_one((row, str(tmp_path), "2026-10-30"))
    assert status == "dated_publisher_invitation_recovered"
    assert result["candidate_status"] == "Needs review"
    draft = result["metadata"]["auto_review_draft"]
    assert draft["contact_quote"] in body.decode()
    assert draft["contact_active_date"] == "2026-10-28"
    assert result["metadata"]["contact_evidence_recovery"]["source_fetched_at"].startswith("2026-10-29")


def test_changed_source_bytes_are_not_promoted_to_evidence(tmp_path):
    row, _ = make_cache(tmp_path)
    row["metadata"]["auto_evidence_snapshots"][row["source_feed_url"]]["sha256"] = "changed"
    result, status = recover_one((row, str(tmp_path), "2026-10-30"))
    assert status == "snapshot_missing_or_changed"
    assert not result["metadata"]["auto_review_draft"]


def test_stale_snapshot_does_not_produce_contact_evidence(tmp_path):
    row, _ = make_cache(tmp_path)
    _, status = recover_one((row, str(tmp_path), "2027-01-01"))
    assert status == "source_stale_or_future"
