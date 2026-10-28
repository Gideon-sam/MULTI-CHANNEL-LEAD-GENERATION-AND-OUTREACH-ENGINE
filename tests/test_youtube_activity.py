import asyncio
import logging
from datetime import date

from test_dedupe_and_validation import config

from incubrix_engine.sources.youtube import YouTubeCandidate
from incubrix_engine.sources.youtube_activity import fetch_upload_activity, public_video


def item(identity="v1", channel="channel1", published="2026-10-25T10:00:00Z", privacy="public"):
    return {
        "id": identity,
        "snippet": {
            "channelId": channel,
            "title": "Synthetic lesson",
            "description": "Synthetic metadata",
            "publishedAt": published,
        },
        "status": {"privacyStatus": privacy},
        "contentDetails": {"duration": "PT12M30S"},
    }


def test_api_activity_checks_ownership_date_privacy_and_duration():
    assert public_video(item(), "channel1", date(2026, 10, 26)).duration_minutes == 12
    assert public_video(item(channel="someone_else"), "channel1", date(2026, 10, 26)) is None
    assert public_video(item(privacy="private"), "channel1", date(2026, 10, 26)) is None
    assert (
        public_video(item(published="2027-01-01T00:00:00Z"), "channel1", date(2026, 10, 26)) is None
    )
    assert (
        public_video(item(published="2025-01-01T00:00:00Z"), "channel1", date(2026, 10, 26)) is None
    )


def test_upload_api_dedupes_and_failure_is_unknown_not_inactive():
    class FakeApi:
        async def get(self, resource, params):
            if resource == "channels":
                return {
                    "items": [
                        {
                            "id": c,
                            "contentDetails": {"relatedPlaylists": {"uploads": "uploads-" + c}},
                        }
                        for c in ("channel1", "channel2")
                    ]
                }
            if resource == "playlistItems":
                if params["playlistId"].endswith("channel2"):
                    raise RuntimeError("Synthetic quota failure")
                return {
                    "items": [
                        {
                            "contentDetails": {
                                "videoId": "v1",
                                "videoPublishedAt": "2026-10-25T00:00:00Z",
                            }
                        }
                    ]
                    * 2
                }
            return {"items": [item()]}

    videos, reports = asyncio.run(
        fetch_upload_activity(
            [YouTubeCandidate(c, "Synthetic", "") for c in ("channel1", "channel2")],
            FakeApi(),
            config(),
            logging.getLogger("test"),
        )
    )
    assert len(videos["channel1"]) == 1
    assert reports["channel1"]["status"] == "available"
    assert reports["channel2"]["status"] == "unavailable"
