from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    checked_date: str
    sender_name: str
    sender_context: str
    target_leads: int
    priority_a_count: int
    max_country_share: float
    approved_countries: list[str]
    country_targets: dict[str, int]
    search_terms: list[str]
    itunes_result_limit: int
    max_candidates: int
    network_concurrency: int
    per_host_concurrency: int
    request_timeout_seconds: int
    request_retries: int
    min_episode_minutes: int
    min_longform_60d: int
    min_items_30d: int
    cache_max_age_hours: int
    workbook_template: str
    output_dir: str
    state_dir: str
    cache_dir: str
    log_dir: str
    review_file: str = "config/reviews.json"
    youtube_max_search_calls: int = 70
    youtube_result_limit: int = 50
    podcast_index_max_search_calls: int = 40
    podcast_index_result_limit: int = 100
    tavily_evidence_query_limit: int = 100

    @classmethod
    def load(cls, path: str | Path) -> Config:
        path = Path(path)
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        allowed = {field.name for field in fields(cls)}
        unknown = set(raw) - allowed
        required = {field.name for field in fields(cls) if field.default is MISSING}
        missing = required - set(raw)
        if unknown or missing:
            raise ValueError(
                f"Invalid config; unknown={sorted(unknown)}, missing={sorted(missing)}"
            )
        if raw.get("checked_date") == "today":
            raw["checked_date"] = (
                datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
            )
        config = cls(**raw)
        date.fromisoformat(config.checked_date)
        for name in (
            "target_leads",
            "priority_a_count",
            "max_candidates",
            "network_concurrency",
            "per_host_concurrency",
            "request_timeout_seconds",
            "request_retries",
            "min_episode_minutes",
            "min_longform_60d",
            "min_items_30d",
            "cache_max_age_hours",
            "youtube_max_search_calls",
            "youtube_result_limit",
            "podcast_index_max_search_calls",
            "podcast_index_result_limit",
            "tavily_evidence_query_limit",
        ):
            value = getattr(config, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not 1 <= config.itunes_result_limit <= 200:
            raise ValueError("itunes_result_limit must be between 1 and 200")
        if not 1 <= config.youtube_result_limit <= 50:
            raise ValueError("youtube_result_limit must be between 1 and 50")
        if not 1 <= config.podcast_index_result_limit <= 200:
            raise ValueError("podcast_index_result_limit must be between 1 and 200")
        if not 0 < config.max_country_share <= 0.6:
            raise ValueError("max_country_share must be >0 and <=0.6")
        if len(set(config.approved_countries)) < 3:
            raise ValueError("At least three approved countries are required")
        if config.priority_a_count > config.target_leads:
            raise ValueError("priority_a_count cannot exceed target_leads")
        return config

    def ensure_directories(self, root: Path) -> None:
        for name in (self.output_dir, self.state_dir, self.cache_dir, self.log_dir):
            target = (root / name).resolve()
            if not target.is_relative_to(root.resolve()) or target == root.resolve():
                raise ValueError(
                    f"Output/cache/state path must be a subdirectory of the project: {name}"
                )
            target.mkdir(parents=True, exist_ok=True)
