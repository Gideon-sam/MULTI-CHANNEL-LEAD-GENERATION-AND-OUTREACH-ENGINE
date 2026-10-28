from __future__ import annotations

from dataclasses import replace

from incubrix_engine.config import Config
from incubrix_engine.models import Lead
from incubrix_engine.pipeline import _dedupe_leads
from incubrix_engine.validation import validate


def config() -> Config:
    return Config(
        checked_date="2026-10-26",
        sender_name="Test Sender",
        sender_context="candidate",
        target_leads=3,
        priority_a_count=1,
        max_country_share=0.6,
        approved_countries=["US", "CA", "GB"],
        country_targets={"US": 1, "CA": 1, "GB": 1},
        search_terms=["business"],
        itunes_result_limit=10,
        max_candidates=10,
        network_concurrency=2,
        per_host_concurrency=1,
        request_timeout_seconds=2,
        request_retries=1,
        min_episode_minutes=10,
        min_longform_60d=2,
        min_items_30d=8,
        cache_max_age_hours=24,
        workbook_template="template.xlsx",
        output_dir="output",
        state_dir="state",
        cache_dir="cache",
        log_dir="logs",
    )


def lead(stable_id: str, name: str, contact: str, country: str, priority: str = "B") -> Lead:
    return Lead(
        lead_id=stable_id,
        creator_name=name,
        country_iso2=country,
        profile_url="https://podcasts.apple.com/show",
        stable_creator_id=stable_id,
        last_content_date="2026-10-25",
        recent_content_url="https://example.com/episode",
        monetization_signal="Sponsorship",
        monetization_evidence_url="https://example.com/episode",
        incubrix_need="Verified repurposing opportunity",
        need_evidence_url="https://example.com/episode",
        best_channel="Email",
        channel_handle_or_url=contact,
        channel_evidence_url="https://example.com/feed.xml",
        personalization_hook="Published a verified episode",
        first_message="Hi — specific message with opt-out",
        checked_date="2026-10-26",
        priority=priority,
        lead_score=90,
        candidate_status="Qualified",
        completeness_check="COMPLETE",
        follow_up_1="Follow-up one",
        follow_up_2="Follow-up two",
    )


def test_dedupe_uses_stable_id_name_and_exact_contact() -> None:
    original = lead("a", "Alex Smith", "alex@example.com", "US")
    same_person_new_show = replace(original, stable_creator_id="b", lead_score=80)
    same_contact = lead("c", "A. Smith", "alex@example.com", "CA")
    unique, removed = _dedupe_leads([same_person_new_show, same_contact, original])
    assert [item.stable_creator_id for item in unique] == ["a"]
    assert removed == 2


def test_validation_catches_country_cap() -> None:
    leads = [
        lead("a", "Alex Smith", "a@example.com", "US", "A"),
        lead("b", "Bea Jones", "b@example.com", "US"),
        lead("c", "Cam Lee", "c@example.com", "CA"),
    ]
    checks = {check.name: check for check in validate(leads, config())}
    assert checks["minimum_leads"].passed
    assert not checks["country_cap"].passed
