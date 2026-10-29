"""Uncertain names deserve evidence research, never automatic qualification."""

import asyncio
from datetime import UTC, datetime

import pytest
from test_dedupe_and_validation import config

from incubrix_engine.http_client import CachedResponse
from incubrix_engine.models import PodcastCandidate
from incubrix_engine.review import approve_candidate
from incubrix_engine.sources.apple_podcasts import enrich


@pytest.mark.parametrize("author", ["The Learning Studio", "Bloomberg Media"])
def test_uncertain_identity_is_enriched_but_cannot_qualify_without_review(author):
    feed = f'''<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel><title>The Learning Studio</title><itunes:author>{author}</itunes:author>
    <language>en</language><link>https://example.test/</link>
    <item><title>Planning a creative week</title><link>https://example.test/one</link>
    <pubDate>Sun, 25 Oct 2026 12:00:00 GMT</pubDate><itunes:duration>1200</itunes:duration>
    </item><item><title>Producing a lesson</title><link>https://example.test/two</link>
    <pubDate>Sun, 18 Oct 2026 12:00:00 GMT</pubDate><itunes:duration>1200</itunes:duration>
    </item></channel></rss>'''.encode()
    visited = []

    class FakeClient:
        async def get(self, url, **kwargs):
            visited.append(url)
            return CachedResponse(
                url=url, status_code=200, headers={},
                content=feed if url.endswith("/rss") else b"<html>Official website</html>",
                fetched_at=datetime(2026, 10, 26, tzinfo=UTC).timestamp(), from_cache=False,
            )

        async def allowed_by_robots(self, url):
            return True

    async def scenario():
        candidate = PodcastCandidate(
            "123", author, "The Learning Studio", "", "https://example.test/rss",
            "https://example.test/profile", "Education",
        )
        client = FakeClient()
        result = await enrich(candidate, config(), client)
        assert result.lead.candidate_status == "Needs review"
        assert result.lead.longform_count_60d == 2
        assert result.lead.metadata["creator_identity_review_required"] is True
        assert "https://example.test/" in visited
        reviewed = await approve_candidate(result.lead, None, config(), client, False)
        assert reviewed.candidate_status == "Needs review"

    asyncio.run(scenario())
