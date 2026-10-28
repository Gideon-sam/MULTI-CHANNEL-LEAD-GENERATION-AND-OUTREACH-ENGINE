from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Self
from urllib.parse import urlparse

import feedparser
import httpx
from langdetect import LangDetectException, detect

from ..config import Config
from ..http_client import HttpClient
from ..models import Lead

API_ROOT = "https://www.googleapis.com/youtube/v3"
CHANNEL_ROOT = "https://www.youtube.com/channel"
FEED_ROOT = "https://www.youtube.com/feeds/videos.xml"
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>\])}\"']+", re.IGNORECASE)
ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)

ORGANISATION_TERMS = {
    "agency",
    "association",
    "broadcast",
    "church",
    "clinic",
    "college",
    "company",
    "corporation",
    "daily",
    "foundation",
    "institute",
    "magazine",
    "media",
    "network",
    "news",
    "official tv",
    "productions",
    "radio",
    "records",
    "school",
    "society",
    "studio",
    "studios",
    "team",
    "university",
}
COMMERCIAL_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Sponsorship", ("sponsored by", "sponsor", "brand partner", "paid partnership")),
    ("Course/coaching", ("my course", "online course", "coaching", "masterclass", "workshop")),
    ("Membership/subscription", ("patreon.com", "membership", "join my community", "substack.com")),
    ("Affiliate offer", ("affiliate", "use code", "discount code", "amazon.com/shop")),
    ("Product/service", ("book a call", "work with me", "my book", "consulting", "services")),
    ("Donation/support", ("buymeacoffee.com", "support the channel", "donate")),
)
SOCIAL_HOSTS = (
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "threads.net",
    "tiktok.com",
    "substack.com",
    "patreon.com",
)


@dataclass
class YouTubeCandidate:
    channel_id: str
    title: str
    description: str
    custom_url: str = ""
    country_iso2: str = ""
    subscriber_count: str = ""
    matched_terms: list[str] = field(default_factory=list)
    api_item: dict = field(default_factory=dict)


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    description: str
    published_date: str
    duration_minutes: int = 0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


class YouTubeApi:
    """Small API-key client that never puts the credential in URLs, logs, or cache files."""

    def __init__(
        self,
        api_key: str,
        cache_dir: str | os.PathLike[str] | None = None,
        max_age_hours: int = 24,
        refresh: bool = False,
    ) -> None:
        if not api_key.strip():
            raise ValueError("YOUTUBE_API_KEY is required for --source youtube")
        self.client = httpx.AsyncClient(
            base_url=API_ROOT,
            timeout=httpx.Timeout(30),
            headers={"X-Goog-Api-Key": api_key, "Accept": "application/json"},
        )
        self.requests = 0
        self.cache_hits = 0
        self.estimated_quota_units = 0
        self.network_attempts: Counter[str] = Counter()
        self.response_provenance: dict[tuple[str, str, str], dict] = {}
        self.cache_dir = os.fspath(cache_dir) if cache_dir is not None else ""
        self.max_age_seconds = max_age_hours * 3600
        self.refresh = refresh
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    @staticmethod
    def _read_cached_json(path: str) -> dict:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_cached_json(path: str, payload: dict) -> None:
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)

    async def get(self, resource: str, params: dict[str, object], *, cost: int = 1) -> dict:
        cache_path = ""
        if self.cache_dir:
            material = resource + "?" + json.dumps(params, sort_keys=True, separators=(",", ":"))
            cache_path = os.path.join(
                self.cache_dir, hashlib.sha256(material.encode("utf-8")).hexdigest() + ".json"
            )
            if not self.refresh and os.path.exists(cache_path):
                age = time.time() - os.path.getmtime(cache_path)
                if 0 <= age <= self.max_age_seconds:
                    try:
                        payload = await asyncio.to_thread(self._read_cached_json, cache_path)
                        self.cache_hits += 1
                        self.record_provenance(
                            resource, params, payload, os.path.getmtime(cache_path), True
                        )
                        return payload
                    except (OSError, ValueError, TypeError):
                        pass
        try:
            self.network_attempts[resource] += 1
            response = await self.client.get(f"/{resource}", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            reason = ""
            try:
                reason = (
                    error.response.json().get("error", {}).get("errors", [{}])[0].get("reason", "")
                )
            except (ValueError, AttributeError, IndexError):
                pass
            raise RuntimeError(
                f"YouTube API request failed ({status}, {reason or 'unknown'})"
            ) from None
        self.requests += 1
        self.estimated_quota_units += cost
        self.record_provenance(resource, params, payload, time.time(), False)
        if cache_path:
            await asyncio.to_thread(self._write_cached_json, cache_path, payload)
        return payload

    def record_provenance(
        self, resource: str, params: dict, payload: dict, fetched_at: float, cached: bool
    ) -> None:
        for item in payload.get("items", []):
            identity = item.get("id")
            if not isinstance(identity, str):
                continue
            self.response_provenance[resource, identity, str(params.get("part", ""))] = {
                "retrieved_at": datetime.fromtimestamp(fetched_at, UTC).isoformat(),
                "sha256": hashlib.sha256(
                    json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
                "source": f"YouTube Data API {resource}.list",
                "parts": params.get("part", ""),
                "from_cache": cached,
                "public_item_id": identity,
            }

    def snapshot(self, resource: str, identity: str, part: str) -> dict:
        return dict(self.response_provenance.get((resource, identity, part), {}))


def _chunks(values: list[str], size: int = 50) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _iso_duration_minutes(value: str) -> int:
    match = ISO_DURATION_RE.fullmatch(value or "")
    if not match:
        return 0
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    seconds = (
        parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]
    )
    return seconds // 60


def _creator_led(title: str, description: str) -> bool:
    lowered = f"{title} {description[:600]}".casefold()
    if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in ORGANISATION_TERMS):
        return False
    first_person = bool(
        re.search(r"\b(i am|i'm|my channel|my videos|i help|i teach|i share)\b", lowered)
    )
    person_like_title = 1 < len(re.findall(r"[A-Za-z][A-Za-z'\-]+", title)) <= 5
    expertise = bool(
        re.search(r"\b(coach|consultant|educator|author|speaker|creator|trainer|expert)\b", lowered)
    )
    return first_person or (person_like_title and expertise)


def _creator_name(title: str, description: str) -> str:
    match = re.search(
        r"\bhosted\s+by\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3}"
        r"(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})?)",
        description,
    )
    return " ".join(match.group(1).split()) if match else title


def _english(title: str, description: str, videos: list[YouTubeVideo]) -> bool:
    text = " ".join([title, description[:1200], *[video.title for video in videos[:8]]]).strip()
    try:
        return len(text) >= 40 and detect(text) == "en"
    except LangDetectException:
        return False


def _commercial_evidence(
    description: str, profile_url: str, videos: list[YouTubeVideo]
) -> tuple[str, str, str]:
    sources = [(description, profile_url), *((v.description, v.url) for v in videos)]
    for text, url in sources:
        lowered = text.casefold()
        for label, terms in COMMERCIAL_SIGNALS:
            for term in terms:
                if term in lowered:
                    start = max(0, lowered.index(term) - 90)
                    excerpt = " ".join(text[start : start + 260].split())
                    return label, url, excerpt
    return "", "", ""


def _contact(description: str, profile_url: str) -> tuple[str, str, str, str, str]:
    emails = [value.lower().rstrip(".") for value in EMAIL_RE.findall(description)]
    emails = [value for value in emails if value.split("@", 1)[0] not in {"noreply", "privacy"}]
    urls = []
    for value in URL_RE.findall(description):
        value = value.rstrip(".,;:!?")
        host = (urlparse(value).hostname or "").lower().removeprefix("www.")
        if host and "youtube.com" not in host and value not in urls:
            urls.append(value)
    social = next(
        (value for value in urls if any(host in value.lower() for host in SOCIAL_HOSTS)), ""
    )
    website = next((value for value in urls if value != social), "")
    if emails:
        backup = social or website or profile_url
        backup_host = (urlparse(backup).hostname or "").lower()
        backup_label = next(
            (
                name
                for name in ("Instagram", "LinkedIn", "TikTok", "X")
                if name.lower() in backup_host
            ),
            "YouTube" if "youtube.com" in backup_host else "Website",
        )
        return "Email", emails[0], backup_label, backup, emails[0]
    if social:
        host = (urlparse(social).hostname or "").lower()
        label = next(
            (name for name in ("Instagram", "LinkedIn", "TikTok", "X") if name.lower() in host),
            "Social",
        )
        return label, social, "YouTube", profile_url, social
    if website:
        return "Website", website, "YouTube", profile_url, website
    return "", "", "", "", ""


async def discover_channels(config: Config, api: YouTubeApi) -> list[YouTubeCandidate]:
    regions = ["US", "US", "US", "GB", "CA", "AU", "IE", "NZ", "SG"]
    queries: list[tuple[str, str]] = []
    modifiers = ("coach", "consultant", "educator", "creator", "podcast host")
    for index, term in enumerate(config.search_terms):
        if re.search(
            r"\b(coach|consultant|creator|podcast|educator|author|speaker)\b", term, re.IGNORECASE
        ):
            query = term
        else:
            query = f"{term} {modifiers[index % len(modifiers)]}"
        queries.append((query, regions[index % len(regions)]))
        if len(queries) >= config.youtube_max_search_calls:
            break

    semaphore = asyncio.Semaphore(8)

    async def search(query: str, region: str) -> tuple[str, dict]:
        async with semaphore:
            payload = await api.get(
                "search",
                {
                    "part": "snippet",
                    "type": "channel",
                    "q": query,
                    "maxResults": config.youtube_result_limit,
                    "relevanceLanguage": "en",
                    "regionCode": region,
                    "safeSearch": "moderate",
                },
                cost=100,
            )
            return query, payload

    results = await asyncio.gather(*(search(query, region) for query, region in queries))
    found: dict[str, YouTubeCandidate] = {}
    for query, payload in results:
        for item in payload.get("items", []):
            channel_id = str(
                item.get("snippet", {}).get("channelId")
                or item.get("id", {}).get("channelId")
                or ""
            )
            if not channel_id:
                continue
            snippet = item.get("snippet", {})
            candidate = found.setdefault(
                channel_id,
                YouTubeCandidate(
                    channel_id=channel_id,
                    title=str(snippet.get("title") or ""),
                    description=str(snippet.get("description") or ""),
                ),
            )
            if query not in candidate.matched_terms:
                candidate.matched_terms.append(query)

    channel_ids = sorted(found)
    for batch in _chunks(channel_ids):
        payload = await api.get(
            "channels",
            {
                "part": "snippet,brandingSettings,statistics",
                "id": ",".join(batch),
                "maxResults": 50,
            },
        )
        for item in payload.get("items", []):
            channel_id = str(item.get("id") or "")
            if channel_id not in found:
                continue
            snippet = item.get("snippet", {})
            branding = item.get("brandingSettings", {}).get("channel", {})
            statistics = item.get("statistics", {})
            candidate = found[channel_id]
            candidate.title = str(snippet.get("title") or candidate.title)
            candidate.description = str(snippet.get("description") or candidate.description)
            candidate.custom_url = str(snippet.get("customUrl") or "")
            candidate.country_iso2 = str(branding.get("country") or "").upper()
            candidate.subscriber_count = str(statistics.get("subscriberCount") or "")
            candidate.api_item = item
    return list(found.values())


async def fetch_channel_videos(
    candidates: list[YouTubeCandidate],
    http: HttpClient,
    api: YouTubeApi,
    config: Config,
    refresh: bool,
) -> dict[str, list[YouTubeVideo]]:
    semaphore = asyncio.Semaphore(config.network_concurrency)

    async def feed(candidate: YouTubeCandidate) -> tuple[str, list[YouTubeVideo]]:
        url = f"{FEED_ROOT}?channel_id={candidate.channel_id}"
        async with semaphore:
            try:
                response = await http.get(url, refresh=refresh)
            except (httpx.HTTPError, OSError, ValueError):
                return candidate.channel_id, []
        parsed = feedparser.parse(response.content)
        videos: list[YouTubeVideo] = []
        for entry in parsed.entries:
            video_id = str(entry.get("yt_videoid") or "")
            published = entry.get("published_parsed")
            if not video_id or not published:
                continue
            published_date = date(published.tm_year, published.tm_mon, published.tm_mday)
            age = (date.fromisoformat(config.checked_date) - published_date).days
            if not 0 <= age <= 60:
                continue
            videos.append(
                YouTubeVideo(
                    video_id=video_id,
                    title=str(entry.get("title") or ""),
                    description=str(entry.get("media_description") or entry.get("summary") or ""),
                    published_date=published_date.isoformat(),
                )
            )
        return candidate.channel_id, videos

    feed_rows = await asyncio.gather(*(feed(candidate) for candidate in candidates))
    by_channel = dict(feed_rows)
    video_ids = list(dict.fromkeys(v.video_id for videos in by_channel.values() for v in videos))
    durations: dict[str, int] = {}
    for batch in _chunks(video_ids):
        payload = await api.get(
            "videos", {"part": "contentDetails,status", "id": ",".join(batch), "maxResults": 50}
        )
        for item in payload.get("items", []):
            if item.get("status", {}).get("privacyStatus") != "public":
                continue
            durations[str(item.get("id") or "")] = _iso_duration_minutes(
                str(item.get("contentDetails", {}).get("duration") or "")
            )
    return {
        channel_id: [
            YouTubeVideo(
                video_id=video.video_id,
                title=video.title,
                description=video.description,
                published_date=video.published_date,
                duration_minutes=durations.get(video.video_id, 0),
            )
            for video in videos
            if video.video_id in durations
        ]
        for channel_id, videos in by_channel.items()
    }


def qualify_channel(
    candidate: YouTubeCandidate, videos: list[YouTubeVideo], config: Config
) -> Lead:
    profile_url = f"{CHANNEL_ROOT}/{candidate.channel_id}"
    about_url = profile_url + "/about"
    lead = Lead(
        creator_name=_creator_name(candidate.title, candidate.description),
        creator_segment=(
            "Podcaster/Video Podcaster"
            if "podcast" in f"{candidate.title} {candidate.description}".casefold()
            else "YouTuber/Video-first Creator"
        ),
        country_iso2=candidate.country_iso2,
        primary_platform="YouTube",
        profile_url=profile_url,
        stable_creator_id=f"youtube-channel:{candidate.channel_id}",
        followers_or_subscribers=candidate.subscriber_count,
        checked_date=config.checked_date,
        source_api_url=profile_url,
        source_license="YouTube Data API metadata and public channel feed; no media redistribution",
    )
    reasons: list[str] = []
    if not _creator_led(candidate.title, candidate.description):
        reasons.append("not_clearly_creator_led")
    if candidate.country_iso2 not in config.approved_countries:
        reasons.append("approved_country_not_publicly_declared")
    if not videos:
        reasons.append("no_recent_public_videos")
    elif not _english(candidate.title, candidate.description, videos):
        reasons.append("content_not_mainly_english")

    as_of = date.fromisoformat(config.checked_date)
    within_30 = [
        v for v in videos if 0 <= (as_of - date.fromisoformat(v.published_date)).days <= 30
    ]
    longform_60 = [v for v in videos if v.duration_minutes >= config.min_episode_minutes]
    if len(within_30) < config.min_items_30d and len(longform_60) < config.min_longform_60d:
        reasons.append("activity_threshold_not_met")

    commercial, commercial_url, commercial_excerpt = _commercial_evidence(
        candidate.description, about_url, videos
    )
    if not commercial:
        reasons.append("commercial_evidence_not_found")
    best, contact, backup_label, backup, contact_excerpt = _contact(
        candidate.description, profile_url
    )
    if not best:
        reasons.append("public_business_contact_not_found")
    if not backup:
        reasons.append("backup_contact_not_found")

    if videos:
        latest = videos[0]
        lead.last_content_date = latest.published_date
        lead.recent_content_url = latest.url
        lead.personalization_hook = (
            f'Published "{latest.title}" on {latest.published_date}; '
            f"{len(within_30)} public videos verified in 30 days."
        )
        lead.incubrix_need = (
            f"Observed repurposing workload: {len(longform_60)} public long-form videos in 60 days "
            "can be converted into platform-specific clips, captions and posts. This is an "
            "evidence-based workflow inference, not a claimed pain point."
        )
        lead.need_evidence_url = latest.url
    lead.content_count_30d = len(within_30)
    lead.longform_count_60d = len(longform_60)
    lead.monetization_signal = commercial
    lead.monetization_evidence_url = commercial_url
    lead.best_channel = best
    lead.channel_handle_or_url = contact
    lead.channel_evidence_url = about_url if contact else ""
    lead.backup_channel = f"{backup_label}: {backup}" if backup else ""

    first_name = candidate.title.split()[0] if candidate.title.split() else "there"
    recent_title = videos[0].title if videos else "your recent video"
    sender = f"{config.sender_name}, {config.sender_context}"
    lead.first_message = (
        f"Hi {first_name} — I’m {sender}. I watched your recent video “{recent_title}”. "
        "Its long-form material could become a focused set of captioned clips and posts in "
        "IncuBrix. Would a 15-minute workflow preview using that video be useful? If not, reply "
        "‘no’ and I won’t follow up."
    )
    lead.follow_up_1 = (
        f"Hi {first_name} — {sender}, following up on “{recent_title}”. One concrete test is a "
        "captioned short built around its central takeaway and linked back to the full video. "
        "Would you like to see that workflow? Reply ‘no’ and I’ll stop."
    )
    lead.follow_up_2 = (
        f"Final note from {sender}, {first_name}. If repurposing “{recent_title}” is useful, I "
        "can share the IncuBrix workflow; otherwise I’ll close this out. Reply ‘no’ to opt out."
    )
    evidence_payload = json.dumps(candidate.api_item, sort_keys=True, ensure_ascii=False).encode()
    lead.metadata = {
        "matched_search_terms": candidate.matched_terms,
        "custom_url": candidate.custom_url,
        "country_evidence_url": about_url,
        "country_evidence_method": "youtube_api_declared_country:brandingSettings.channel.country",
        "automated_evidence": {
            "identity": candidate.title,
            "country": candidate.country_iso2,
            "language_method": "deterministic_language_detection_on_public_metadata",
            "commercial_excerpt": commercial_excerpt,
            "contact_excerpt": contact_excerpt,
            "backup_contact": backup,
            "activity_rule": f"{len(within_30)}_in_30d_or_{len(longform_60)}_longform_in_60d",
        },
        "evidence_snapshots": {
            about_url: {
                "retrieved_at": datetime.now().astimezone().isoformat(),
                "sha256": hashlib.sha256(evidence_payload).hexdigest(),
                "source": "YouTube Data API channels.list",
            },
            **(
                {
                    videos[0].url: {
                        "retrieved_at": datetime.now().astimezone().isoformat(),
                        "source": "YouTube public Atom feed and videos.list",
                    }
                }
                if videos
                else {}
            ),
        },
        "activity_items": [
            {
                "title": video.title,
                "url": video.url,
                "date": video.published_date,
                "duration_minutes": video.duration_minutes,
            }
            for video in videos
        ],
    }
    lead.lead_score = round(
        min(
            100,
            50
            + min(15, len(within_30))
            + min(20, len(longform_60) * 4)
            + (5 if candidate.subscriber_count else 0)
            + (5 if commercial else 0)
            + (5 if best else 0),
        ),
        1,
    )
    if reasons:
        lead.candidate_status = "Rejected"
        lead.rejection_reason = ";".join(dict.fromkeys(reasons))
        lead.completeness_check = "MISSING EVIDENCE"
    else:
        lead.candidate_status = "Qualified"
        lead.completeness_check = "COMPLETE"
        lead.evidence_notes = (
            "Stable channel ID, declared country, recent public activity, duration, commercial "
            "signal and public contact routes were deterministically checked."
        )
    return lead


def api_key_from_environment() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "").strip()
