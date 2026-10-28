"""Synthetic .test fixtures exercise gates; they are never exported as real leads."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import feedparser
import httpx
import pytest
from test_dedupe_and_validation import config, lead

from incubrix_engine.http_client import CachedResponse, HttpClient
from incubrix_engine.review import approve_candidate, load_reviews
from incubrix_engine.seed import SeedStore
from incubrix_engine.sources.apple_podcasts import _duration_minutes, _episodes


def test_missing_review_cannot_qualify_a_discovery_candidate(tmp_path):
    candidate = lead("test", "Synthetic Person", "owned@example.test", "US")
    candidate.candidate_status = "Needs review"

    async def scenario():
        async with HttpClient(tmp_path, resolve_dns=False) as client:
            result = await approve_candidate(candidate, None, config(), client, False)
            assert result.candidate_status == "Needs review"

    asyncio.run(scenario())


def test_complete_review_promotes_candidate_only_after_source_recheck():
    candidate = lead("apple-podcast:123", "Synthetic Person", "owned@example.test", "US")
    candidate.candidate_status = "Needs review"
    candidate.profile_url = "https://example.test/proof"
    candidate.recent_content_url = "https://example.test/proof"
    candidate.metadata = {
        "feed_fetched_at": "2026-10-26T00:00:00+00:00",
        "feed_stale": False,
        "activity_items": [{"title": "Synthetic episode"}],
    }
    excerpts = {
        "identity": "Synthetic Person official creator profile",
        "country": "Synthetic Person is based in the United States",
        "language": "This English-language creator podcast",
        "commercial": "Enroll in Synthetic Person's creator course",
        "need": "Editing and repurposing every weekly episode takes time",
        "contact": "Business enquiries: owned@example.test",
        "contact_activity": "Business channel updated 2026-10-25",
        "backup": "Backup contact: https://example.test/contact",
    }
    review = {
        "stable_creator_id": candidate.stable_creator_id,
        "creator_identity_key": "https://example.test/creator",
        "reviewer": "Synthetic reviewer",
        "reviewed_at": "2026-10-26",
        "rationale": "Synthetic evidence exercises the complete approval path.",
        "creator_name": "Synthetic Person",
        "country_iso2": "US",
        "best_channel": "Email",
        "channel_handle_or_url": "owned@example.test",
        "backup_channel": "Website",
        "backup_handle_or_url": "https://example.test/contact",
        "contact_active_date": "2026-10-25",
        "need_description": "Weekly editing and repurposing workflow",
        "proofs": {
            kind: {"url": "https://example.test/proof", "quote": quote}
            for kind, quote in excerpts.items()
        },
    }

    class FakeClient:
        async def get(self, url, **_kwargs):
            assert url == "https://example.test/proof"
            return CachedResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html"},
                content=("<html><body>" + " ".join(excerpts.values()) + "</body></html>").encode(),
                fetched_at=datetime(2026, 10, 26, tzinfo=UTC).timestamp(),
                from_cache=False,
            )

    result = asyncio.run(approve_candidate(candidate, review, config(), FakeClient(), False))
    assert result.candidate_status == "Qualified"
    assert result.metadata["creator_identity_key"] == "https://example.test/creator"
    assert result.metadata["evidence_snapshots"]["https://example.test/proof"]["status_code"] == 200


def test_review_file_requires_all_business_evidence(tmp_path):
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps({"schema_version": 1, "reviews": [{"stable_creator_id": "test"}]}))
    with pytest.raises(ValueError, match="required fields"):
        load_reviews(path)


def test_repeated_feed_entries_do_not_inflate_activity():
    entry = {
        "title": "Synthetic episode",
        "link": "https://example.test/one",
        "published_parsed": time.gmtime(1793000000),
        "itunes_duration": "600",
    }
    feed = feedparser.FeedParserDict({"entries": [entry, entry]})
    assert len(_episodes(feed)) == 1
    assert _duration_minutes("599") == 9


def test_redirects_release_single_connection_slot_and_detect_loop(tmp_path):
    async def scenario():
        async with HttpClient(
            tmp_path, concurrency=1, per_host_concurrency=1, retries=1, resolve_dns=False
        ) as client:

            async def respond(url, **_kwargs):
                if url.endswith("/first"):
                    return httpx.Response(
                        302, headers={"location": "/last"}, request=httpx.Request("GET", url)
                    )
                return httpx.Response(
                    200, content=b"actual mock response", request=httpx.Request("GET", url)
                )

            client.client.get = respond
            result = await asyncio.wait_for(client.get("https://example.test/first"), 3)
            assert result.url == "https://example.test/last"

            async def loop(url, **_kwargs):
                return httpx.Response(
                    302, headers={"location": url}, request=httpx.Request("GET", url)
                )

            client.client.get = loop
            with pytest.raises(httpx.TooManyRedirects):
                await asyncio.wait_for(client.get("https://example.test/loop"), 3)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "file:///tmp/file",
        "https://user:password@example.test/",
        "http://[::1]/",
    ],
)
def test_sources_cannot_target_local_addresses(tmp_path, url):
    async def scenario():
        async with HttpClient(tmp_path, resolve_dns=False) as client:
            with pytest.raises(ValueError):
                await client.get(url)

    asyncio.run(scenario())


def test_seed_schedule_tracking_reply_and_suppression(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps(
            {
                channel: {
                    "sender": f"sender-{channel}.test",
                    "recipient": f"recipient-{channel}.test",
                    "ownership_confirmed": True,
                }
                for channel in ("email", "linkedin", "instagram")
            }
        )
    )
    evidence = tmp_path / "synthetic-test-evidence.txt"
    evidence.write_text("Synthetic unit-test evidence only; not a completed real seed test.")
    store = SeedStore(tmp_path / "seed.sqlite3")
    try:
        now = datetime.now(UTC)
        rows = store.plan(accounts, "http://127.0.0.1:8081", now, "unit-test")
        assert len(rows) == 9
        assert len(store.due(now + timedelta(seconds=1))) == 3
        assert not store.report()["evidence_complete"]
        for row in rows:
            if not row["message_id"].endswith("-1"):
                continue
            with pytest.raises(ValueError, match="scheduling"):
                store.record(row["message_id"], "sent", str(evidence))
            store.record(row["message_id"], "native_scheduled", str(evidence))
            store.record(row["message_id"], "sent", str(evidence))
            target = store.click(row["tracking_url"].rsplit("/", 1)[-1])
            assert "utm_source=seed_test" in target
            store.record(row["message_id"], "reply", str(evidence))
        assert store.report()["evidence_complete"]
        assert not store.due(now + timedelta(days=10))
        assert store.click("unknown-token") is None
    finally:
        store.close()
