"""Additional outreach review and launch evidence, without changing qualification gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .audit_support import metadata, read_rows
from .exporters import _write_csv
from .files import write_text

SEGMENTS = ("Podcaster/Video Podcaster", "YouTuber/Video-first Creator", "Expert-led Creator")
CHANNELS = ("Email", "LinkedIn", "Instagram")


def content_title(row: dict) -> str:
    items = metadata(row).get("activity_items", [])
    return str(items[0].get("title", "")) if items else ""


def safe_drafts(row: dict) -> dict:
    title = content_title(row)
    if not title:
        return {"first_message": "", "follow_up_1": "", "follow_up_2": ""}
    name = str(row.get("creator_name", "")).split(" ", 1)[0]
    sender = "[YOUR NAME], an independent candidate researching creator workflows for IncuBrix"
    return {
        "first_message": (
            f"Hi {name} — I'm {sender}. Your recent content, “{title}” "
            f"({row.get('last_content_date', '')}), prompted an idea: use one focused excerpt "
            "as a captioned clip linked to the full piece. Would a short IncuBrix workflow "
            "preview for that piece be useful? Reply 'no' to opt out and I will stop."
        ),
        "follow_up_1": (
            f"Hi {name} — {sender}, following up on “{title}”. A practical test would be "
            "one short clip, a caption variant and a post directing viewers back to the full "
            "piece. Would you like to review that workflow? Reply 'no' to opt out."
        ),
        "follow_up_2": (
            f"Final note from {sender}, {name}. If reusing “{title}” fits your workflow, "
            "I can share the preview. Otherwise I will close this out with no further "
            "follow-ups. Reply 'no' to opt out."
        ),
    }


def outreach_issues(row: dict) -> list[str]:
    title = content_title(row)
    messages = [
        str(row.get(field, "")) for field in ("first_message", "follow_up_1", "follow_up_2")
    ]
    issues = []
    if not title or title not in messages[0]:
        issues.append("generic_or_missing_specific_recent_title")
    if any(not message.strip() for message in messages):
        issues.append("missing_touch")
    if any("[YOUR NAME]" not in message for message in messages):
        issues.append("sender_placeholder_missing")
    if any(
        "opt out" not in message.lower() and "opt-out" not in message.lower()
        for message in messages
    ):
        issues.append("opt_out_missing")
    if any(
        re.search(r"\bi (?:watched|listened|loved|enjoyed)\b", message, re.IGNORECASE)
        for message in messages
    ):
        issues.append("unsubstantiated_personal_consumption_claim")
    if any("independent" not in message.lower() for message in messages):
        issues.append("sender_relationship_not_explicit")
    return issues


def write_outreach_support(directory: Path) -> dict:
    leads = read_rows(directory / "leads.csv")
    ledger = {row["lead_id"]: row for row in read_rows(directory / "evidence_ledger.csv")}
    ranked = sorted(
        leads, key=lambda row: (-float(row.get("lead_score") or 0), row["stable_creator_id"])
    )
    expected = {row["lead_id"] for row in ranked[:25]}
    priority = [row for row in leads if row.get("priority") == "A"]
    issues, drafts = [], []
    for row in priority:
        full = {**ledger.get(row["lead_id"], {}), **row}
        problems = outreach_issues(full)
        if problems:
            issues.append({"lead_id": row["lead_id"], "issues": problems})
        drafts.append(
            {
                "lead_id": row["lead_id"],
                "creator_name": row["creator_name"],
                "best_channel": row["best_channel"],
                "channel_handle_or_url": row["channel_handle_or_url"],
                "recent_content_url": row["recent_content_url"],
                "specific_content_title": content_title(full),
                **safe_drafts(full),
                "send_status": "DRAFT: user review required; no messages sent",
            }
        )
    fields = [
        "lead_id",
        "creator_name",
        "best_channel",
        "channel_handle_or_url",
        "recent_content_url",
        "specific_content_title",
        "first_message",
        "follow_up_1",
        "follow_up_2",
        "send_status",
    ]
    _write_csv(directory / "outreach/review_ready_priority_a_sequences.csv", drafts, fields)
    sequences = []
    for segment in SEGMENTS:
        for channel in CHANNELS:
            unit = (
                "episode"
                if segment.startswith("Podcaster")
                else "video"
                if segment.startswith("YouTuber")
                else "lesson"
            )
            context = (
                "Use an explicitly published business email; day 1, 4, 9."
                if channel == "Email"
                else "Only after a connection is accepted and business contact is invited; day 1, 4, 9."
                if channel == "LinkedIn"
                else "Only where business DMs are explicitly invited; day 1, 5, 10."
            )
            sequences.append(
                {
                    "segment": segment,
                    "channel": channel,
                    "cadence_and_contact_rule": context,
                    "first_message": f"Hi [FIRST NAME] — I'm [YOUR NAME], an independent candidate researching IncuBrix workflows. Your {unit} “[EXACT RECENT TITLE]” ([DATE]) suggests a clip/caption experiment. Open to a short preview? Reply 'no' to opt out.",
                    "follow_up_1": f"[YOUR NAME], independent candidate, following up on “[EXACT RECENT TITLE]”. One test: a captioned excerpt linked back to the full {unit}. Useful to see? Reply 'no' to opt out.",
                    "follow_up_2": "Final note from [YOUR NAME], independent candidate: I can share the workflow for “[EXACT RECENT TITLE]”, or close this out. Reply 'no' to opt out; no more follow-ups.",
                }
            )
    _write_csv(directory / "outreach/segment_channel_sequences.csv", sequences, list(sequences[0]))
    report = {
        "official_leads": len(leads),
        "priority_a_count": len(priority),
        "required_priority_a_count": 25,
        "has_25_priority_a": len(priority) >= 25,
        "best_25_marking_matches": len(leads) >= 25
        and {r["lead_id"] for r in priority} == expected,
        "priority_a_message_issues": issues,
        "segment_channel_template_count": len(sequences),
        "templates_are_not_completed_seed_tests": True,
        "messages_sent": 0,
    }
    write_text(directory / "outreach/quality_report.json", json.dumps(report, indent=2))
    return report


def write_launch_supplement(directory: Path) -> None:
    leads = read_rows(directory / "leads.csv")
    contacts = Counter(row.get("best_channel") or "Unknown" for row in leads)
    mix = "\n".join(
        f"| {channel} | {count} | {count / len(leads):.1%} |"
        for channel, count in sorted(contacts.items())
    )
    content = f"""# Launch supplement — evidence and assumptions

Observed official export: {len(leads)} rows. These are current engine outputs, pending the independent human audit. Actual reply, meeting, delivery and spend measurements are unset. No real creators have been contacted.

| Published best contact type | Rows | Share |
|---|---:|---:|
{mix or "| No official leads | 0 | unset |"}

Recommendation from available contact types: allocate initial research/review effort in these proportions, after each route's business purpose and activity are verified. Website and YouTube links are not proof of an inbox or permission for a public sales comment. There is no observed channel-response winner. Choose a channel based on verified contact availability first; compare responses only after an authorized future pilot. Test-account replies cannot demonstrate creator response rates.

## Days 1–30, owners and daily workload

| Days | Owner | Actions and conditions |
|---|---|---|
| 1–2 | Candidate + product owner | Finish product observations, review the random sample, repair missing evidence, test three owned channels, review 25 sequences. |
| 3–7 | Growth owner | If a future real pilot is separately authorized: at most 5 new emails/day, 2 invited LinkedIn conversations/day, 2 invited Instagram conversations/day. Otherwise owned-account tests only. |
| 8–14 | Growth owner | Consider 10 new emails/day and 3 manual conversations/day per social channel only after delivery and suppression checks pass. |
| 15–21 | Growth + product | Review at least 50 delivered messages before comparing variants; change one message variable. Prepare demos only for interested recipients. |
| 22–30 | Growth + engineering | At most 15 new emails/day and 5 invited conversations/day per social channel, conditional on observed results and current platform restrictions. Refresh evidence, log outcomes, decide continue/revise/stop. |

These volumes are conservative operating assumptions, not platform guarantees. Include follow-ups in daily workload; one creator has one active sequence. Stop follow-ups on any reply, opt-out, bounce or complaint. Pause on any complaint, hard bounce rate at or above 2%, or a platform restriction. Verify current account-specific limits before any future authorized pilot.

## Targets and reasoning (unmeasured planning scenarios)

For a future 125–200 delivered-contact pilot, plan for 0–12% total replies, 0–5% positive replies and 0–3% meetings. Zero is included because no response baseline exists. Upper bounds are test hypotheses reflecting relevant recent-content personalization, not sourced benchmarks or forecasts. Meetings must be a subset of positive replies; revise the scenario after the first 50 deliveries. The initial assessment target is complete evidence and three successful owned-account seed tests, not creator sends.

## Tools, owners and budget

Engineering: this Python CLI, SQLite, local dashboard and CSV. Growth: an existing owned mailbox and native LinkedIn/Instagram interfaces; CRM can start with the CSV. Product: IncuBrix access for actual testing. Candidate: evidence capture and videos. No new service purchase is required by this plan. Budget authorization: 0 new purchases; actual provider spend, API billing and cost per qualified lead: UNSET until invoices/console records are supplied. Existing subscriptions and hardware are not assumed free. See runtime_cost_report.json for measured calls/runtime and explicit missing financial evidence.

## Launch prerequisites

At least 1,000 verified creators (2,000 is the requested target), country rules, 25 complete Priority A sequences, the independent audit, working business-contact evidence, three actual owned-account seed tests, product findings, two videos and private access for the reviewers. Exceptional status additionally requires 5,000 verified creators, 250 Priority A sequences, the stricter audit and channel accuracy, a measured 5,000-row refresh, and evidence of creator responses. This supplement does not certify those requirements.
"""
    write_text(directory / "launch-supplement.md", content)
