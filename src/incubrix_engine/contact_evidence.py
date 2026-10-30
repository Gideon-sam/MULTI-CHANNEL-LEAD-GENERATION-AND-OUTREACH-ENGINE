"""Extract dated publisher business-contact invitations, never approval decisions."""

from __future__ import annotations

import html
import re
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
INVITATION = re.compile(
    r"business (?:enquir|inquir)|(?:enquir|inquir)(?:ies|y)|sponsor|"
    r"get in touch|contact (?:me|us)|email (?:me|us)|book(?:ing| a call)", re.IGNORECASE
)
PROVIDER_HOSTS = {
    "acast.com", "anchor.fm", "podbean.com", "buzzsprout.com", "libsyn.com",
    "simplecast.com", "spotify.com", "pod.co", "omnycontent.com", "megaphone.fm",
}


def publisher_contact_hints(
    feed_raw: str, official_url: str, official_emails: set[str], as_of: str
) -> list[dict]:
    """Only recent item-level invitations tied to the supplied publisher website.

    Header owner mailboxes, undated items, future posts and unrelated guest domains
    cannot produce a hint. Identity and meaning still require separate verification.
    """
    host = (urlparse(official_url).hostname or "").lower().removeprefix("www.")
    if not host or any(host == p or host.endswith("." + p) for p in PROVIDER_HOSTS):
        return []
    try:
        today = date.fromisoformat(as_of)
    except (ValueError, TypeError):
        return []
    known = {email.casefold() for email in official_emails}
    results = []
    seen = set()
    for item in re.findall(r"<item\b[^>]*>.*?</item\s*>", feed_raw, re.IGNORECASE | re.DOTALL):
        published = re.search(r"<pubDate\b[^>]*>(.*?)</pubDate\s*>", item, re.IGNORECASE | re.DOTALL)
        if not published:
            continue
        try:
            day = parsedate_to_datetime(published.group(1).strip()).date()
        except (ValueError, TypeError, OverflowError):
            continue
        if not 0 <= (today - day).days <= 60:
            continue
        descriptions = re.findall(
            r"<(?:description|content:encoded)\b[^>]*>(.*?)</(?:description|content:encoded)\s*>",
            item, re.IGNORECASE | re.DOTALL,
        )
        for description in descriptions:
            if not EMAIL.search(html.unescape(description)):
                continue
            content = html.unescape(description.replace("<![CDATA[", "").replace("]]>", ""))
            visible = " ".join(BeautifulSoup(content, "html.parser").get_text(" ", strip=True).split())
            for match in EMAIL.finditer(visible):
                contact = match.group().rstrip(".").casefold()
                domain = contact.split("@", 1)[1]
                if contact not in known and not (domain == host or domain.endswith("." + host)):
                    continue
                if any(domain == p or domain.endswith("." + p) for p in PROVIDER_HOSTS):
                    continue
                if contact.split("@", 1)[0] in {"privacy", "abuse", "noreply", "no-reply"}:
                    continue
                window = visible[max(0, match.start() - 140): match.end() + 100]
                if not INVITATION.search(window) or re.search(
                    r"(?:guest|privacy|unsubscribe|copyright|data protection)", window, re.IGNORECASE
                ):
                    continue
                if contact in seen:
                    continue
                # Keep raw snippets exact: do not synthesize prose from decoded HTML.
                raw_match = re.search(re.escape(match.group()), description, re.IGNORECASE)
                if not raw_match:
                    continue
                quote = description[
                    max(0, raw_match.start() - 140):raw_match.end() + 100
                ][:400]
                title = re.search(r"<title\b[^>]*>(.*?)</title\s*>", item, re.IGNORECASE | re.DOTALL)
                results.append({
                    "contact": contact,
                    "contact_quote": quote,
                    "contact_activity_quote": published.group(0),
                    "contact_active_date": day.isoformat(),
                    "episode_title": html.unescape(title.group(1)) if title else "",
                    "status": "HINT_REQUIRES_CREATOR_SPECIFIC_REVIEW",
                })
                seen.add(contact)
    return results
