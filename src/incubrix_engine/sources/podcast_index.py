"""Bounded Podcast Index discovery; publisher RSS still supplies qualification evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

import httpx
import truststore

from ..config import Config
from ..models import PodcastCandidate

API_ROOT = "https://api.podcastindex.org/api/1.0"


class PodcastIndexApi:
    """Header-authenticated client that excludes credentials from URLs and cache keys."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        cache_dir: Path,
        max_age_hours: int = 24,
        refresh: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Podcast Index key and secret are required")
        self.api_key = api_key
        self.api_secret = api_secret
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_hours * 3600
        self.refresh = refresh
        self.clock = clock
        self.requests = 0
        self.cache_hits = 0
        self.client = httpx.AsyncClient(
            base_url=API_ROOT,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            timeout=httpx.Timeout(30),
            headers={"User-Agent": "IncuBrixAssessmentResearch/1.0", "Accept": "application/json"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    def _auth_headers(self) -> dict[str, str]:
        timestamp = str(int(self.clock()))
        token = hashlib.sha1(
            (self.api_key + self.api_secret + timestamp).encode("utf-8")
        ).hexdigest()
        return {
            "X-Auth-Date": timestamp,
            "X-Auth-Key": self.api_key,
            "Authorization": token,
        }

    async def get(self, resource: str, params: dict[str, object]) -> dict:
        material = resource + "?" + json.dumps(params, sort_keys=True, separators=(",", ":"))
        cache_path = self.cache_dir / (hashlib.sha256(material.encode()).hexdigest() + ".json")
        if not self.refresh and cache_path.exists():
            age = self.clock() - cache_path.stat().st_mtime
            if 0 <= age <= self.max_age_seconds:
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                    self.cache_hits += 1
                    return payload
                except (OSError, ValueError, TypeError):
                    pass
        try:
            response = await self.client.get(
                "/" + resource.lstrip("/"), params=params, headers=self._auth_headers()
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                f"Podcast Index API request failed ({error.response.status_code})"
            ) from None
        if not isinstance(payload, dict):
            raise TypeError("Podcast Index API returned an invalid payload")
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(cache_path)
        self.requests += 1
        return payload


def _candidate_from_feed(feed: dict) -> PodcastCandidate | None:
    itunes_id = str(feed.get("itunesId") or "").strip()
    feed_url = str(feed.get("url") or feed.get("originalUrl") or "").strip()
    parsed = urlparse(feed_url)
    if not itunes_id.isdigit() or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    published = feed.get("newestItemPubdate") or 0
    try:
        release_date = datetime.fromtimestamp(int(published), UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        release_date = ""
    categories = feed.get("categories") or {}
    if isinstance(categories, dict):
        genre = " | ".join(str(value) for value in categories.values())
    else:
        genre = ""
    return PodcastCandidate(
        apple_id=itunes_id,
        artist_name=str(feed.get("ownerName") or feed.get("author") or "").strip(),
        collection_name=str(feed.get("title") or "").strip(),
        country_iso2="",
        feed_url=feed_url,
        apple_url=f"https://podcasts.apple.com/podcast/id{itunes_id}",
        genre=genre,
        release_date=release_date,
        discovery_provider="Podcast Index API",
    )


async def discover(config: Config, api: PodcastIndexApi) -> list[PodcastCandidate]:
    """Search a bounded term set; do not crawl or download the provider's whole index."""
    semaphore = asyncio.Semaphore(4)
    terms = config.search_terms[: config.podcast_index_max_search_calls]

    async def search(term: str) -> dict:
        async with semaphore:
            return await api.get(
                "search/byterm",
                {"q": term, "max": config.podcast_index_result_limit, "clean": ""},
            )

    payloads = await asyncio.gather(*(search(term) for term in terms))
    found: dict[str, PodcastCandidate] = {}
    as_of = date.fromisoformat(config.checked_date)
    for payload in payloads:
        for feed in payload.get("feeds", []):
            if not isinstance(feed, dict) or feed.get("dead"):
                continue
            language = str(feed.get("language") or "").casefold()
            if language and not language.startswith("en"):
                continue
            candidate = _candidate_from_feed(feed)
            if candidate is None:
                continue
            if candidate.release_date:
                published = datetime.fromisoformat(candidate.release_date).date()
                if not 0 <= (as_of - published).days <= 60:
                    continue
            found.setdefault(candidate.apple_id, candidate)
    return list(found.values())[: config.max_candidates]


def credentials_from_environment() -> tuple[str, str]:
    return (
        os.environ.get("PODCAST_INDEX_API_KEY", "").strip(),
        os.environ.get("PODCAST_INDEX_API_SECRET", "").strip(),
    )
