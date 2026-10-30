"""Creator-specific evidence approval. Discovery heuristics never constitute approval."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .config import Config
from .http_client import HttpClient
from .models import Lead

PROOF_KINDS = (
    "identity",
    "country",
    "language",
    "commercial",
    "need",
    "contact",
    "contact_activity",
    "backup",
)
REVIEW_FIELDS = (
    "stable_creator_id",
    "creator_identity_key",
    "reviewer",
    "reviewed_at",
    "rationale",
    "creator_name",
    "country_iso2",
    "best_channel",
    "channel_handle_or_url",
    "backup_channel",
    "backup_handle_or_url",
    "contact_active_date",
    "need_description",
)


def load_reviews(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(data.get("reviews"), list)
    ):
        raise ValueError("reviews.json requires schema_version: 1 and a reviews array")
    result = {}
    for review in data["reviews"]:
        if not isinstance(review, dict):
            raise TypeError("Each review must be an object")
        missing = [
            key
            for key in REVIEW_FIELDS
            if not isinstance(review.get(key), str) or not review[key].strip()
        ]
        if missing:
            raise ValueError(f"Review lacks required fields: {', '.join(missing)}")
        stable_id = review["stable_creator_id"]
        for field in ("reviewed_at", "contact_active_date"):
            try:
                date.fromisoformat(review[field])
            except ValueError:
                raise ValueError(f"{stable_id}: {field} must be YYYY-MM-DD") from None
        if review["contact_active_date"] > review["reviewed_at"]:
            raise ValueError(f"{stable_id}: contact activity cannot follow the review date")
        if not _public_url(review["creator_identity_key"]):
            raise ValueError(f"{stable_id}: creator identity must be a valid public URL")
        if stable_id in result:
            raise ValueError(f"Duplicate review: {stable_id}")
        proofs = review.get("proofs", {})
        if not isinstance(proofs, dict) or set(proofs) != set(PROOF_KINDS):
            raise ValueError(f"{stable_id}: provide exactly the eight required proof kinds")
        for kind in PROOF_KINDS:
            proof = proofs.get(kind, {})
            if (
                not isinstance(proof, dict)
                or not isinstance(proof.get("url"), str)
                or not isinstance(proof.get("quote"), str)
                or not proof["url"].strip()
                or not proof["quote"].strip()
            ):
                raise ValueError(f"{stable_id}: missing {kind} URL or exact excerpt")
            if len(proof["quote"]) > 400:
                raise ValueError(f"{stable_id}: keep {kind} excerpt under 400 characters")
            if not _public_url(proof["url"]):
                raise ValueError(f"{stable_id}: invalid {kind} evidence URL")
        result[stable_id] = review
    return result


def _normal(value: str) -> str:
    return " ".join(value.split()).casefold()


def _public_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not any(character.isspace() for character in value)
            and (parsed.port is None or 0 < parsed.port <= 65535)
        )
    except (ValueError, TypeError):
        return False


def _route_key(value: str) -> str:
    """Equivalent URL spellings do not constitute a second contact route."""
    value = value.strip()
    if not _public_url(value):
        return value.casefold()
    parsed = urlparse(value)
    host = parsed.hostname.casefold().removeprefix("www.")
    port = parsed.port
    authority = host if port in {None, 80, 443} else f"{host}:{port}"
    return f"{authority}{parsed.path.rstrip('/')}?{parsed.query}"


async def approve_candidate(
    lead: Lead,
    review: dict | None,
    config: Config,
    http: HttpClient,
    refresh: bool,
) -> Lead:
    if review is None:
        return lead
    review = dict(review)
    for channel in ("best_channel", "backup_channel"):
        if str(review.get(channel, "")).strip().casefold() == "email":
            review[channel] = "Email"

    def fail(reason: str) -> Lead:
        lead.rejection_reason = f"review_failed:{reason}"
        return lead

    today = date.fromisoformat(config.checked_date)
    try:
        reviewed = date.fromisoformat(review["reviewed_at"][:10])
        contact_active = date.fromisoformat(review["contact_active_date"])
        feed_time = datetime.fromisoformat(lead.metadata["feed_fetched_at"]).date()
    except (ValueError, KeyError, TypeError):
        return fail("invalid_dates")
    if not 0 <= (today - reviewed).days <= 30:
        return fail("review_expired_or_future")
    if not 0 <= (today - contact_active).days <= 60:
        return fail("contact_activity_not_recent")
    if lead.metadata.get("feed_stale") or not 0 <= (today - feed_time).days <= 30:
        return fail("feed_not_fresh")
    if review["country_iso2"] not in config.approved_countries:
        return fail("country_not_approved")
    if not _public_url(review["creator_identity_key"]):
        return fail("creator_identity_key_must_be_canonical_public_url")
    if review["best_channel"] == "Email":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", review["channel_handle_or_url"]):
            return fail("invalid_email")
    elif not _public_url(review["channel_handle_or_url"]):
        return fail("invalid_channel_url")
    # A copied address needs explicit business-contact context, not merely an RSS owner tag.
    if review["best_channel"] == "Email" and _normal(
        review["channel_handle_or_url"]
    ) not in _normal(review["proofs"]["contact"]["quote"]):
        return fail("contact_excerpt_must_contain_exact_email")

    backup = review["backup_handle_or_url"]
    if review["backup_channel"] == "Email":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", backup):
            return fail("invalid_backup_email")
    elif not _public_url(backup):
        return fail("invalid_backup_url")
    if _route_key(backup) == _route_key(review["channel_handle_or_url"]):
        return fail("backup_must_be_a_second_route")
    if _normal(backup) not in _normal(review["proofs"]["backup"]["quote"]):
        return fail("backup_excerpt_must_contain_exact_contact")
    if review["best_channel"] != "Email" and _normal(
        review["channel_handle_or_url"]
    ) not in _normal(review["proofs"]["contact"]["quote"]):
        return fail("contact_excerpt_must_contain_exact_url")

    snapshots = {}
    urls = {proof["url"] for proof in review["proofs"].values()}
    urls.update((lead.profile_url, lead.recent_content_url))
    for url in sorted(urls):
        if not _public_url(url):
            return fail("invalid_evidence_url")
        try:
            response = await http.get(
                url, refresh=refresh, respect_robots=url != lead.source_feed_url
            )
        except (httpx.HTTPError, OSError, ValueError) as error:
            return fail(f"evidence_unavailable:{type(error).__name__}:{url}")
        fetched = datetime.fromtimestamp(response.fetched_at, UTC)
        if response.stale or not 0 <= (today - fetched.date()).days <= 30:
            return fail(f"stale_evidence:{url}")
        raw = response.content.decode("utf-8", errors="replace")
        visible = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        for kind, proof in review["proofs"].items():
            if proof["url"] != url:
                continue
            if _normal(proof["quote"]) not in _normal(visible) and _normal(
                proof["quote"]
            ) not in _normal(raw):
                return fail(f"excerpt_not_found:{kind}")
        snapshots[url] = {
            "resolved_url": response.url,
            "status_code": response.status_code,
            "retrieved_at": fetched.isoformat(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        }

    for name in ("creator_name", "country_iso2", "best_channel", "channel_handle_or_url"):
        setattr(lead, name, review[name])
    lead.backup_channel = f"{review['backup_channel']}: {review['backup_handle_or_url']}"
    lead.incubrix_need = review["need_description"]
    lead.need_evidence_url = review["proofs"]["need"]["url"]
    lead.channel_evidence_url = review["proofs"]["contact"]["url"]
    lead.monetization_evidence_url = review["proofs"]["commercial"]["url"]
    lead.monetization_signal = review["proofs"]["commercial"]["quote"]
    latest = lead.metadata.get("activity_items", [{}])[0]
    title = latest.get("title", lead.personalization_hook)
    first_name = lead.creator_name.split()[0]
    sender = f"{config.sender_name}, {config.sender_context}"
    lead.first_message = (
        f"Hi {first_name} — I'm {sender}. Your recent episode '{title}' ({lead.last_content_date}) "
        f"caught my attention. {lead.incubrix_need} Would a short IncuBrix workflow preview for "
        "turning that episode into clips and captions be useful? Reply 'no' to opt out."
    )
    lead.follow_up_1 = (
        f"Hi {first_name} — {sender}, following up on '{title}'. One possible experiment is a "
        "captioned clip around its central question, linked to the full episode. Would you like "
        "to review that workflow? Reply 'no' and I will stop."
    )
    lead.follow_up_2 = (
        f"Final note from {sender}, {first_name}. If repurposing '{title}' is useful to you, "
        "I can share the IncuBrix workflow. Otherwise I'll close this out. Reply 'no' to opt out."
    )
    lead.metadata.update(
        {
            "review": review,
            "evidence_snapshots": snapshots,
            "creator_identity_key": review["creator_identity_key"],
            "country_evidence_url": review["proofs"]["country"]["url"],
            "country_evidence_method": "reviewed_creator_specific_source",
        }
    )
    lead.checked_date = today.isoformat()
    lead.candidate_status = "Qualified"
    lead.rejection_reason = ""
    lead.completeness_check = "COMPLETE"
    lead.evidence_notes += (
        f" Reviewed by {review['reviewer']} on {review['reviewed_at']}; exact excerpts checked."
    )
    return lead
