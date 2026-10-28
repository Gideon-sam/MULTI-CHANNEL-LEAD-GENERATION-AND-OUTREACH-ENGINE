from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .exporters import _write_csv
from .models import Lead

CHANNEL_SEQUENCES = """# IncuBrix multi-channel outreach sequences

These are manual, one-to-one sequences. Only use them after a human verifies the evidence on the day of send. Respect each platform's limits and stop immediately after an opt-out. Do not bulk-automate social DMs.

## Email — creator-led podcasts

Day 1: Mention the verified recent episode and its publication date. Connect the specific long-form cadence to one IncuBrix workflow: clips, captions and platform-specific posts. Ask for a 15-minute workflow review. Identify the sender and include a plain-text opt-out.

Day 4: Offer one concrete repurposing idea tied to the same episode. Do not claim to have listened beyond what was manually reviewed.

Day 9: Close the loop, restate the verified cadence and say there will be no further contact.

## LinkedIn — expert-led creators

Day 1 (connection note, <=300 characters): “Hi {{first_name}} — your recent {{content_title}} caught my eye. I’m Gideon, evaluating creator workflows for IncuBrix. I’d value connecting; no pitch in the request.”

Day 3 after acceptance: “Thanks for connecting. I saw {{content_title}} published on {{date}}. IncuBrix turns one long-form piece into clips, captions and channel-ready posts. Would a short workflow preview be useful? If not, say so and I won’t follow up.”

Day 8: Share one specific transformation idea and close the loop. Never automate connection requests or DMs where platform rules prohibit it.

## Instagram — video-first creators

Day 1: Reply only where a business DM is invited. “Hi {{first_name}} — Gideon here, evaluating creator workflows for IncuBrix. Your {{date}} post on {{topic}} is a strong long-form source for clips and caption variants. Open to a 15-minute workflow look? Say ‘no’ and I won’t follow up.”

Day 5: Send one concise clip/caption idea based on the verified post.

Day 10: Final close-out. No repeated reactions, comment spam or automated DMs.

## YouTube — public business contact route

Use the channel's published business contact route; do not post a sales pitch as a public comment. Follow the email cadence and link to the exact video used for personalization.

## Global safeguards

- Suppress addresses immediately after any opt-out, complaint or hard bounce.
- One creator = one active sequence across all channels.
- Re-check the latest content and contact evidence before sending.
- No purchased lists, guessed emails, scraped private data or claims that the sender works for IncuBrix.
- Seed tests go only to accounts controlled by the candidate; real creators are never contacted during the assessment.
"""


def write_outreach(leads: list[Lead], root: Path) -> None:
    outreach_dir = root / "outreach"
    priority_dir = outreach_dir / "priority_a"
    priority_dir.mkdir(parents=True, exist_ok=True)
    (outreach_dir / "channel_sequences.md").write_text(CHANNEL_SEQUENCES, encoding="utf-8")

    priority = [lead for lead in leads if lead.priority == "A"]
    current_ids = {lead.lead_id for lead in priority}
    for previous in priority_dir.glob("*.md"):
        if previous.stem not in current_ids:
            archive = (
                outreach_dir / "previous_priority_a" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            )
            archive.mkdir(parents=True, exist_ok=True)
            previous.replace(archive / previous.name)
    fields = [
        "lead_id",
        "creator_name",
        "best_channel",
        "channel_handle_or_url",
        "personalization_hook",
        "first_message",
        "follow_up_1",
        "follow_up_2",
        "recent_content_url",
        "channel_evidence_url",
    ]
    _write_csv(
        outreach_dir / "priority_a_sequences.csv",
        [{field: getattr(lead, field) for field in fields} for lead in priority],
        fields,
    )

    for lead in priority:
        safe_id = lead.lead_id.replace("/", "-")
        content = f"""# {lead.lead_id} — {lead.creator_name}

- Verified hook: {lead.personalization_hook}
- Recent content: {lead.recent_content_url}
- Contact evidence: {lead.channel_evidence_url}
- Channel: {lead.best_channel} — {lead.channel_handle_or_url}

## Message 1 — Day 1

{lead.first_message}

## Follow-up 1 — Day 4

{lead.follow_up_1}

## Follow-up 2 — Day 9

{lead.follow_up_2}
"""
        (priority_dir / f"{safe_id}.md").write_text(content, encoding="utf-8")
