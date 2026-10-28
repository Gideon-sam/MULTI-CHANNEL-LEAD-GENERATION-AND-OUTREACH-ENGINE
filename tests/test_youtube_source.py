from __future__ import annotations

import asyncio
from types import SimpleNamespace

from incubrix_engine.sources.youtube import (
    _contact,
    _creator_led,
    _creator_name,
    _iso_duration_minutes,
    discover_channels,
)


def test_iso_duration_parser() -> None:
    assert _iso_duration_minutes("PT12M35S") == 12
    assert _iso_duration_minutes("PT1H2M") == 62
    assert _iso_duration_minutes("not-a-duration") == 0


def test_creator_filter_requires_personal_or_expert_signal() -> None:
    assert _creator_led("Alex Smith", "I help founders improve their sales process.")
    assert not _creator_led("Example News Network", "Daily reporting from our newsroom.")
    assert (
        _creator_name("Creator Upload", "A podcast hosted by Lauren Schnipper and Joshua Cohen.")
        == "Lauren Schnipper and Joshua Cohen"
    )


def test_contact_uses_public_description_without_guessing() -> None:
    result = _contact(
        "Business: alex@example.com More: https://instagram.com/alex",
        "https://www.youtube.com/channel/abc",
    )
    assert result[:4] == (
        "Email",
        "alex@example.com",
        "Instagram",
        "https://instagram.com/alex",
    )


def test_discovery_mixes_recent_videos_and_channels_without_changing_gates() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.calls = []

        async def get(self, resource, params, *, cost=1):
            self.calls.append((resource, params, cost))
            return {"items": []}

    api = FakeApi()
    config = SimpleNamespace(
        search_terms=["business", "marketing"],
        youtube_max_search_calls=2,
        youtube_result_limit=50,
        checked_date="2026-10-28",
    )
    assert asyncio.run(discover_channels(config, api)) == []
    video = api.calls[0][1]
    channel = api.calls[1][1]
    assert video["type"] == "video"
    assert video["publishedAfter"] == "2026-08-29T00:00:00Z"
    assert channel["type"] == "channel"
    assert "publishedAfter" not in channel
