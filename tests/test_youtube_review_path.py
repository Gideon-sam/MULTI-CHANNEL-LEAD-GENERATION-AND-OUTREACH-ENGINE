from incubrix_engine.youtube_pipeline import _latest_snapshot_date


def test_youtube_review_path_records_fresh_api_snapshot_metadata():
    snapshots = {
        "profile": {"retrieved_at": "2026-10-29T10:00:00+00:00"},
        "video": {"retrieved_at": "2026-10-30T10:00:00+00:00"},
        "missing": {},
    }
    assert _latest_snapshot_date(snapshots) == "2026-10-30T10:00:00+00:00"
    assert _latest_snapshot_date({}) == ""
