"""Official uploads API ingestion. Transport failures never establish inactivity."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx

from ..config import Config
from .youtube import YouTubeApi, YouTubeCandidate, YouTubeVideo, _chunks, _iso_duration_minutes


def public_video(item: dict, owner_id: str, as_of: date) -> YouTubeVideo | None:
    snippet = item.get("snippet", {})
    if (
        item.get("status", {}).get("privacyStatus") != "public"
        or snippet.get("channelId") != owner_id
    ):
        return None
    try:
        published = date.fromisoformat(str(snippet.get("publishedAt", ""))[:10])
    except ValueError:
        return None
    if not 0 <= (as_of - published).days <= 60 or not item.get("id") or not snippet.get("title"):
        return None
    return YouTubeVideo(
        str(item["id"]),
        str(snippet["title"]),
        str(snippet.get("description", "")),
        published.isoformat(),
        _iso_duration_minutes(str(item.get("contentDetails", {}).get("duration", ""))),
    )


async def fetch_upload_activity(
    candidates: list[YouTubeCandidate], api: YouTubeApi, config: Config, logger: logging.Logger
) -> tuple[dict[str, list[YouTubeVideo]], dict[str, dict]]:
    slots = asyncio.Semaphore(8)
    as_of = date.fromisoformat(config.checked_date)
    reports = {
        candidate.channel_id: {
            "channel_id": candidate.channel_id,
            "status": "pending",
            "pages": 0,
            "window_complete": False,
        }
        for candidate in candidates
    }
    playlists: dict[str, str] = {}

    async def get(resource: str, params: dict) -> dict:
        async with slots:
            return await api.get(resource, params)

    for batch in _chunks([candidate.channel_id for candidate in candidates]):
        try:
            payload = await get(
                "channels", {"part": "contentDetails", "id": ",".join(batch), "maxResults": 50}
            )
        except (RuntimeError, httpx.HTTPError, OSError) as error:
            for channel_id in batch:
                reports[channel_id].update(status="unavailable", error_type=type(error).__name__)
            logger.warning(
                "youtube_channel_details_unavailable",
                extra={"data": {"count": len(batch), "error_type": type(error).__name__}},
            )
            continue
        for item in payload.get("items", []):
            playlists[item["id"]] = str(
                item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
            )
    completed = 0

    async def uploads(candidate: YouTubeCandidate) -> tuple[str, list[str]]:
        nonlocal completed
        channel_id = candidate.channel_id
        report = reports[channel_id]
        playlist = playlists.get(channel_id, "")
        if not playlist:
            report.update(status="unavailable", detail="No public uploads playlist returned")
            completed += 1
            return channel_id, []
        token = ""
        ids: list[str] = []
        try:
            for _ in range(4):
                params = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
                if token:
                    params["pageToken"] = token
                payload = await get("playlistItems", params)
                report["pages"] += 1
                older = False
                for item in payload.get("items", []):
                    details = item.get("contentDetails", {})
                    video_id = details.get("videoId")
                    try:
                        published = date.fromisoformat(
                            str(details.get("videoPublishedAt", ""))[:10]
                        )
                        age = (as_of - published).days
                    except ValueError:
                        age = None
                    if age is not None and age > 60:
                        older = True
                        continue
                    if video_id and (age is None or age >= 0) and video_id not in ids:
                        ids.append(video_id)
                token = str(payload.get("nextPageToken", ""))
                if not token or older:
                    report["window_complete"] = True
                    break
            report.update(status="available", counts_are_lower_bounds=not report["window_complete"])
        except (RuntimeError, httpx.HTTPError, OSError) as error:
            report.update(status="unavailable", error_type=type(error).__name__)
            logger.warning(
                "youtube_uploads_unavailable",
                extra={"data": {"channel_id": channel_id, "error_type": type(error).__name__}},
            )
            ids = []
        completed += 1
        if completed % 100 == 0 or completed == len(candidates):
            logger.info(
                "youtube_uploads_progress",
                extra={"data": {"processed": completed, "total": len(candidates)}},
            )
        return channel_id, ids

    owners = dict(await asyncio.gather(*(uploads(candidate) for candidate in candidates)))
    all_ids = sorted({video_id for ids in owners.values() for video_id in ids})
    video_items: dict[str, dict] = {}
    failed_ids: set[str] = set()

    async def details(batch: list[str]) -> None:
        try:
            payload = await get(
                "videos",
                {"part": "snippet,contentDetails,status", "id": ",".join(batch), "maxResults": 50},
            )
            video_items.update({item["id"]: item for item in payload.get("items", [])})
        except (RuntimeError, httpx.HTTPError, OSError) as error:
            failed_ids.update(batch)
            logger.warning(
                "youtube_video_details_unavailable",
                extra={"data": {"count": len(batch), "error_type": type(error).__name__}},
            )

    await asyncio.gather(*(details(batch) for batch in _chunks(all_ids)))
    videos: dict[str, list[YouTubeVideo]] = {}
    for channel_id, ids in owners.items():
        if any(video_id in failed_ids for video_id in ids):
            reports[channel_id].update(status="unavailable", detail="Video verification incomplete")
        items = [public_video(video_items.get(video_id, {}), channel_id, as_of) for video_id in ids]
        videos[channel_id] = sorted(
            (item for item in items if item is not None),
            key=lambda item: (item.published_date, item.video_id),
            reverse=True,
        )
        reports[channel_id]["verified_recent_public_videos"] = len(videos[channel_id])
    return videos, reports
