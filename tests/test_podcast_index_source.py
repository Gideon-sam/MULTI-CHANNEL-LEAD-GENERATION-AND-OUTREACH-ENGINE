from __future__ import annotations

import hashlib

from incubrix_engine.sources.podcast_index import PodcastIndexApi, _candidate_from_feed


def test_auth_uses_documented_sha1_without_putting_secret_in_url(tmp_path) -> None:
    api = PodcastIndexApi("public-key", "private-secret", tmp_path, clock=lambda: 1234.0)
    try:
        headers = api._auth_headers()
        assert headers["X-Auth-Date"] == "1234"
        assert headers["X-Auth-Key"] == "public-key"
        assert headers["Authorization"] == hashlib.sha1(
            b"public-keyprivate-secret1234"
        ).hexdigest()
        assert "private-secret" not in api.client.base_url.query.decode()
    finally:
        import asyncio

        asyncio.run(api.client.aclose())


def test_feed_candidate_requires_real_itunes_id_and_feed_url() -> None:
    candidate = _candidate_from_feed(
        {
            "itunesId": 123,
            "url": "https://creator.example/feed.xml",
            "ownerName": "Alex Creator",
            "title": "Alex Creates",
            "language": "en",
            "categories": {"1": "Business"},
            "newestItemPubdate": 1_700_000_000,
        }
    )
    assert candidate is not None
    assert candidate.apple_id == "123"
    assert candidate.discovery_provider == "Podcast Index API"
    assert candidate.country_iso2 == ""
    assert _candidate_from_feed({"itunesId": "", "url": "https://example.test/feed"}) is None
