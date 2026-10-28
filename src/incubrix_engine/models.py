from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

LEAD_COLUMNS = [
    "lead_id",
    "creator_name",
    "creator_segment",
    "country_iso2",
    "primary_language",
    "primary_platform",
    "profile_url",
    "stable_creator_id",
    "followers_or_subscribers",
    "last_content_date",
    "recent_content_url",
    "content_count_30d",
    "longform_count_60d",
    "monetization_signal",
    "monetization_evidence_url",
    "incubrix_need",
    "need_evidence_url",
    "best_channel",
    "channel_handle_or_url",
    "channel_evidence_url",
    "backup_channel",
    "personalization_hook",
    "first_message",
    "checked_date",
    "priority",
    "lead_score",
    "candidate_status",
    "rejection_reason",
    "duplicate_check",
    "completeness_check",
]


@dataclass
class PodcastCandidate:
    apple_id: str
    artist_name: str
    collection_name: str
    country_iso2: str
    feed_url: str
    apple_url: str
    genre: str
    release_date: str = ""


@dataclass
class Episode:
    title: str
    url: str
    published_date: str
    duration_minutes: int | None
    summary: str = ""


@dataclass
class Lead:
    lead_id: str = ""
    creator_name: str = ""
    creator_segment: str = "Podcaster/Video Podcaster"
    country_iso2: str = ""
    primary_language: str = "English"
    primary_platform: str = "Podcast"
    profile_url: str = ""
    stable_creator_id: str = ""
    followers_or_subscribers: str = ""
    last_content_date: str = ""
    recent_content_url: str = ""
    content_count_30d: int = 0
    longform_count_60d: int = 0
    monetization_signal: str = ""
    monetization_evidence_url: str = ""
    incubrix_need: str = ""
    need_evidence_url: str = ""
    best_channel: str = ""
    channel_handle_or_url: str = ""
    channel_evidence_url: str = ""
    backup_channel: str = ""
    personalization_hook: str = ""
    first_message: str = ""
    checked_date: str = ""
    priority: str = "C"
    lead_score: float = 0.0
    candidate_status: str = "Rejected"
    rejection_reason: str = ""
    duplicate_check: str = "UNIQUE"
    completeness_check: str = "MISSING FIELDS"
    source_feed_url: str = ""
    source_api_url: str = ""
    source_license: str = ""
    evidence_notes: str = ""
    follow_up_1: str = ""
    follow_up_2: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def workbook_row(self) -> dict[str, Any]:
        row = asdict(self)
        return {column: row[column] for column in LEAD_COLUMNS}

    def source_system(self) -> str:
        """Return an explicit provenance label without changing any lead decision."""
        if self.stable_creator_id.startswith("youtube-channel:"):
            return "YouTube Data API"
        if self.stable_creator_id.startswith("apple-podcast:"):
            return "Apple Podcasts + publisher RSS"
        return str(self.metadata.get("source_system", "Unknown"))

    def evidence_row(self) -> dict[str, Any]:
        raw = asdict(self)
        row: dict[str, Any] = {}
        for key, value in raw.items():
            row[key] = value
            if key == "stable_creator_id":
                row["source_system"] = self.source_system()
        row["metadata"] = json.dumps(raw["metadata"], ensure_ascii=False, sort_keys=True)
        return row
