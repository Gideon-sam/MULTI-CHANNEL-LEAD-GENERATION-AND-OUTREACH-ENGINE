from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .config import Config
from .models import Lead

EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
REQUIRED_FIELDS = [
    "creator_name",
    "creator_segment",
    "country_iso2",
    "primary_language",
    "primary_platform",
    "profile_url",
    "stable_creator_id",
    "last_content_date",
    "backup_channel",
    "recent_content_url",
    "monetization_signal",
    "monetization_evidence_url",
    "incubrix_need",
    "need_evidence_url",
    "best_channel",
    "channel_handle_or_url",
    "channel_evidence_url",
    "personalization_hook",
    "first_message",
    "checked_date",
    "priority",
]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    value: object
    requirement: str


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate(leads: list[Lead], config: Config, report_path: Path | None = None) -> list[Check]:
    ids = [lead.stable_creator_id for lead in leads]
    countries = Counter(lead.country_iso2 for lead in leads)
    max_share = max(countries.values(), default=0) / max(1, len(leads))
    approved = sum(countries[country] for country in config.approved_countries)
    missing = [
        lead.stable_creator_id
        for lead in leads
        if any(getattr(lead, field) in {None, ""} for field in REQUIRED_FIELDS)
    ]
    bad_urls = [
        lead.stable_creator_id
        for lead in leads
        if not all(
            _is_url(value)
            for value in (
                lead.profile_url,
                lead.recent_content_url,
                lead.monetization_evidence_url,
                lead.need_evidence_url,
                lead.channel_evidence_url,
            )
        )
    ]
    bad_contacts = [
        lead.stable_creator_id
        for lead in leads
        if lead.best_channel == "Email" and not EMAIL_RE.match(lead.channel_handle_or_url)
    ]
    normalized_names = [re.sub(r"[^a-z0-9]", "", lead.creator_name.lower()) for lead in leads]
    normalized_contacts = [lead.channel_handle_or_url.lower().strip() for lead in leads]
    duplicate_identities = (
        len(normalized_names)
        - len(set(normalized_names))
        + len(normalized_contacts)
        - len(set(normalized_contacts))
    )
    bad_activity = [
        lead.stable_creator_id
        for lead in leads
        if lead.content_count_30d < config.min_items_30d
        and lead.longform_count_60d < config.min_longform_60d
    ]
    bad_country_evidence = [
        lead.stable_creator_id
        for lead in leads
        if not _is_url(str(lead.metadata.get("country_evidence_url", "")))
        or not str(lead.metadata.get("country_evidence_method", "")).startswith(
            ("reviewed_creator_specific_source", "youtube_api_declared_country")
        )
    ]
    stale_checks = []
    check_date = date.fromisoformat(config.checked_date)
    for lead in leads:
        try:
            age = (check_date - date.fromisoformat(lead.checked_date)).days
        except ValueError:
            age = 999
        if age < 0 or age > 30:
            stale_checks.append(lead.stable_creator_id)
    bad_status = [lead.stable_creator_id for lead in leads if lead.candidate_status != "Qualified"]
    unverified = [
        lead.stable_creator_id
        for lead in leads
        if not (lead.metadata.get("review") or lead.metadata.get("automated_evidence"))
        or not lead.metadata.get("evidence_snapshots")
    ]
    priority = [lead for lead in leads if lead.priority == "A"]
    checks = [
        Check(
            "minimum_leads",
            len(leads) >= config.target_leads,
            len(leads),
            f">={config.target_leads}",
        ),
        Check(
            "unique_stable_ids", len(ids) == len(set(ids)), len(ids) - len(set(ids)), "0 duplicates"
        ),
        Check(
            "unique_creator_and_contact",
            duplicate_identities == 0,
            duplicate_identities,
            "0 duplicates",
        ),
        Check("complete_required_fields", not missing, len(missing), "0 missing"),
        Check("working_url_shape", not bad_urls, len(bad_urls), "0 malformed URLs"),
        Check("public_email_shape", not bad_contacts, len(bad_contacts), "0 malformed emails"),
        Check("activity_threshold", not bad_activity, len(bad_activity), "0 failures"),
        Check(
            "country_evidence",
            not bad_country_evidence,
            len(bad_country_evidence),
            "0 missing/weak",
        ),
        Check("evidence_freshness", not stale_checks, len(stale_checks), "checked within 30 days"),
        Check("qualified_status", not bad_status, len(bad_status), "all Qualified"),
        Check(
            "creator_specific_review",
            not unverified,
            len(unverified),
            "all creator-specific evidence reviewed or deterministically verified",
        ),
        Check(
            "approved_country_share",
            approved / max(1, len(leads)) >= 0.8,
            approved / max(1, len(leads)),
            ">=0.80",
        ),
        Check("country_count", len(countries) >= 3, len(countries), ">=3"),
        Check(
            "country_cap",
            max_share <= config.max_country_share,
            max_share,
            f"<={config.max_country_share}",
        ),
        Check(
            "priority_a_count",
            len(priority) >= config.priority_a_count,
            len(priority),
            f">={config.priority_a_count}",
        ),
        Check(
            "priority_a_sequences",
            all(lead.first_message and lead.follow_up_1 and lead.follow_up_2 for lead in priority),
            sum(
                bool(lead.first_message and lead.follow_up_1 and lead.follow_up_2)
                for lead in priority
            ),
            "all Priority A",
        ),
    ]
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "passed": all(check.passed for check in checks),
                    "checks": [asdict(check) for check in checks],
                    "countries": countries,
                    "bad_urls": bad_urls[:100],
                    "bad_contacts": bad_contacts[:100],
                    "bad_activity": bad_activity[:100],
                    "bad_country_evidence": bad_country_evidence[:100],
                    "stale_checks": stale_checks[:100],
                    "bad_status": bad_status[:100],
                    "missing": missing[:100],
                },
                indent=2,
                default=dict,
            ),
            encoding="utf-8",
        )
    return checks
