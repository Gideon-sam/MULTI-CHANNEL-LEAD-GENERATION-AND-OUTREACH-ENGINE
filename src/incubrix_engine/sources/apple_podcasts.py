from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
from bs4 import BeautifulSoup
from langdetect import DetectorFactory, LangDetectException, detect

from ..config import Config
from ..http_client import HttpClient
from ..models import Episode, Lead, PodcastCandidate

DetectorFactory.seed = 0
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
MAX_FEED_PARSE_BYTES = 1024 * 1024
MAX_SITE_PARSE_BYTES = 512 * 1024
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
OWNER_EMAIL_RE = re.compile(
    r"<itunes:owner\b[^>]*>.*?<itunes:email\b[^>]*>(.*?)</itunes:email>.*?</itunes:owner>",
    re.IGNORECASE | re.DOTALL,
)
GENERIC_EMAIL_PREFIXES = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "privacy",
    "abuse",
}
ORGANISATION_WORDS = {
    "network",
    "media",
    "news",
    "magazine",
    "radio",
    "studios",
    "studio",
    "agency",
    "company",
    "official",
    "foundation",
    "university",
    "association",
    "society",
    "team",
    "productions",
    "podcasts",
    "inc",
    "llc",
    "ltd",
    "group",
    "daily",
    "times",
    "press",
    "broadcasting",
    "corporation",
    "consulting",
    "consultancy",
    "firm",
    "institute",
    "academy",
    "center",
    "centre",
    "organization",
    "organisation",
    "collective",
    "clinic",
}
TOPICAL_BRAND_WORDS = {
    "startup",
    "wellness",
    "health",
    "business",
    "marketing",
    "education",
    "fitness",
    "finance",
    "wisdom",
    "strategy",
    "success",
    "leadership",
    "digital",
    "ventures",
}
COMMERCIAL_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("Membership/subscription", ("patreon.com", "substack.com", "membership", "subscribe at")),
    ("Course/coaching", ("course", "coaching", "masterclass", "workshop", "enrol", "enroll")),
    ("Sponsorship", ("sponsor", "sponsored by", "our partners", "promo code")),
    ("Affiliate offer", ("affiliate", "use code", "discount code", "amazon.com/", "bookshop.org")),
    ("Product/service", ("book a call", "consulting", "services", "shop", "buy my", "order my")),
    ("Donation/support", ("support the show", "buy me a coffee", "donate")),
]
COUNTRY_MAP = {
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "CA": "CA",
    "CAN": "CA",
    "CANADA": "CA",
    "GB": "GB",
    "GBR": "GB",
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "IE": "IE",
    "IRL": "IE",
    "IRELAND": "IE",
    "AU": "AU",
    "AUS": "AU",
    "AUSTRALIA": "AU",
    "NZ": "NZ",
    "NZL": "NZ",
    "NEW ZEALAND": "NZ",
    "SG": "SG",
    "SGP": "SG",
    "SINGAPORE": "SG",
}
TLD_COUNTRIES = {
    ".ca": "CA",
    ".uk": "GB",
    ".ie": "IE",
    ".au": "AU",
    ".nz": "NZ",
    ".sg": "SG",
}
LOCATION_PATTERNS = {
    "US": (
        "united states",
        "u.s.a.",
        "usa",
        "new york",
        "los angeles",
        "austin",
        "chicago",
        "boston",
        "miami",
        "seattle",
        "san francisco",
        "denver",
        "atlanta",
        "nashville",
        "dallas",
        "phoenix",
        "washington dc",
    ),
    "CA": ("canada", "toronto", "vancouver", "montreal", "calgary", "ottawa"),
    "GB": (
        "united kingdom",
        "england",
        "scotland",
        "wales",
        "london",
        "manchester",
        "birmingham",
        "edinburgh",
        "glasgow",
        "bristol",
        "liverpool",
    ),
    "IE": ("ireland", "dublin", "cork", "galway"),
    "AU": ("australia", "sydney", "melbourne", "brisbane", "perth", "adelaide"),
    "NZ": ("new zealand", "auckland", "wellington", "christchurch"),
    "SG": ("singapore",),
}


@dataclass(frozen=True)
class EnrichmentResult:
    lead: Lead
    rejection: str = ""


@dataclass(frozen=True)
class SiteEvidence:
    country: str = ""
    country_url: str = ""
    country_method: str = ""
    contact_channel: str = ""
    contact_value: str = ""
    contact_url: str = ""
    commercial_label: str = ""
    commercial_url: str = ""


def _parse_feed_payload(
    feed_bytes: bytes,
) -> tuple[dict[str, object], list[dict[str, object]], bool]:
    """Parse CPU-heavy RSS in a worker and return only picklable fields used downstream."""
    parsed = feedparser.parse(feed_bytes)
    feed_fields = ("author", "language", "summary", "link", "title", "subtitle", "description")
    entry_fields = (
        "published_parsed",
        "updated_parsed",
        "link",
        "title",
        "itunes_duration",
        "summary",
    )
    feed = {field: parsed.feed.get(field) for field in feed_fields}
    entries = [{field: entry.get(field) for field in entry_fields} for entry in parsed.entries]
    return feed, entries, bool(getattr(parsed, "bozo", False))


def _plain_text(value: str) -> str:
    value = html.unescape(value or "")
    if "<" not in value:
        return " ".join(value.split())
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, tuple):
        try:
            return date(value.tm_year, value.tm_mon, value.tm_mday)
        except (AttributeError, ValueError):
            return None
    text = str(value)
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return parsedate_to_datetime(text).date()
        except (TypeError, ValueError, OverflowError):
            return None


def _duration_minutes(value: object) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.isdigit():
        seconds = int(text)
    else:
        parts = text.split(":")
        if not all(part.isdigit() for part in parts) or len(parts) not in {2, 3}:
            return None
        nums = [int(part) for part in parts]
        seconds = nums[-1] + nums[-2] * 60 + (nums[-3] * 3600 if len(nums) == 3 else 0)
    return max(0, seconds // 60)


def _looks_like_person(name: str, show_name: str) -> bool:
    lowered = f"{name} {show_name}".lower()
    if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in ORGANISATION_WORDS):
        # Named-host syntax is still creator-led even when the show has a network credit.
        return bool(re.search(r"\b(with|hosted by)\s+[A-Z][\w'\-]+", show_name))
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", name)
    lowered_name_words = {word.lower() for word in words}
    if lowered_name_words & TOPICAL_BRAND_WORDS:
        return bool(re.search(r"\b(with|hosted by)\s+[A-Z][\w'\-]+", show_name))
    return 1 < len(words) <= 6 or bool(re.search(r"\b(with|hosted by)\b", show_name, re.IGNORECASE))


def _creator_name(candidate: PodcastCandidate, feed: feedparser.FeedParserDict) -> str:
    author = _plain_text(str(feed.feed.get("author") or candidate.artist_name))
    named_host = re.search(
        r"\b(?:with|hosted by)\s+([A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){1,3})",
        candidate.collection_name,
    )
    if named_host and not _looks_like_person(author, ""):
        return named_host.group(1)
    return author or candidate.artist_name


def _extract_owner_email(raw_xml: str) -> str:
    owner = OWNER_EMAIL_RE.search(raw_xml)
    if owner:
        scope = html.unescape(owner.group(1))
    else:
        # Limit fallback to feed-level metadata so a guest's episode email is never selected.
        channel_header = re.split(r"<(?:item|entry)\b", raw_xml, maxsplit=1, flags=re.IGNORECASE)[0]
        scope = html.unescape(channel_header)
    matches = EMAIL_RE.findall(scope)
    for address in matches:
        address = address.strip().lower().strip(".>")
        if address.endswith(("@anchor.fm", "@privaterelay.appleid.com")):
            continue
        if address.split("@", 1)[0] not in GENERIC_EMAIL_PREFIXES:
            return address
    return ""


def _language_is_english(feed: feedparser.FeedParserDict, episodes: list[Episode]) -> bool:
    declared = str(feed.feed.get("language") or "").lower()
    if declared.startswith("en"):
        return True
    sample = " ".join(episode.title for episode in episodes[:8])
    try:
        return bool(sample) and detect(sample) == "en"
    except LangDetectException:
        return False


def _commercial_signal(episodes: list[Episode]) -> tuple[str, str]:
    for episode in episodes[:12]:
        haystack = f"{episode.title} {episode.summary}".lower()
        for label, terms in COMMERCIAL_SIGNALS:
            if any(term in haystack for term in terms):
                return label, episode.url
    return "", ""


def _country_from_text(text: str) -> tuple[str, str]:
    text = _plain_text(text).lower()
    for country, locations in LOCATION_PATTERNS.items():
        for location in locations:
            escaped = re.escape(location)
            patterns = (
                rf"\bbased\s+in\s+(?:the\s+)?{escaped}\b",
                rf"\b(?:host|creator|podcaster|coach|consultant|educator)\s+from\s+(?:the\s+)?{escaped}\b",
                rf"\b(?:lives?|living|works?|working|recorded|produced)\s+in\s+(?:the\s+)?{escaped}\b",
            )
            if any(re.search(pattern, text) for pattern in patterns):
                return country, location
    return "", ""


def _country_from_structured_data(soup: BeautifulSoup) -> tuple[str, str]:
    accepted = {
        "US": "US",
        "USA": "US",
        "UNITED STATES": "US",
        "UNITED STATES OF AMERICA": "US",
        "CA": "CA",
        "CAN": "CA",
        "CANADA": "CA",
        "GB": "GB",
        "GBR": "GB",
        "UK": "GB",
        "UNITED KINGDOM": "GB",
        "IE": "IE",
        "IRL": "IE",
        "IRELAND": "IE",
        "AU": "AU",
        "AUS": "AU",
        "AUSTRALIA": "AU",
        "NZ": "NZ",
        "NZL": "NZ",
        "NEW ZEALAND": "NZ",
        "SG": "SG",
        "SGP": "SG",
        "SINGAPORE": "SG",
    }

    def walk(value: object) -> tuple[str, str]:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() == "addresscountry":
                    if isinstance(child, dict):
                        child = child.get("name") or child.get("@id") or ""
                    text = str(child).rsplit("/", 1)[-1].strip().upper()
                    if text in accepted:
                        return accepted[text], text
                found = walk(child)
                if found[0]:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found[0]:
                    return found
        return "", ""

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.IGNORECASE)}):
        try:
            payload = json.loads(script.get_text(strip=True))
        except (json.JSONDecodeError, TypeError):
            continue
        found = walk(payload)
        if found[0]:
            return found
    return "", ""


def _remove_user_generated_content(soup: BeautifulSoup) -> None:
    for tag in soup.select(
        "script, style, noscript, [id*='comment' i], [class*='comment' i], "
        "[id*='review' i], [class*='review' i]"
    ):
        tag.decompose()


def _site_page_evidence(page_url: str, body: bytes) -> SiteEvidence:
    # Creator sites occasionally include multi-megabyte inline assets. Evidence is taken only
    # from the document header and visible page copy, so cap parsing to keep runs bounded.
    text = body[:MAX_SITE_PARSE_BYTES].decode("utf-8", errors="replace")
    if re.search(r"<(?:rss|feed|channel)\b", text[:2000], re.IGNORECASE):
        return SiteEvidence()
    soup = BeautifulSoup(text, "html.parser")
    hostname = (urlparse(page_url).hostname or "").lower()
    country = ""
    method = ""
    for suffix, value in TLD_COUNTRIES.items():
        if hostname.endswith(suffix):
            country, method = value, f"official_site_ccTLD:{suffix}"
            break
    if not country:
        country, structured_value = _country_from_structured_data(soup)
        if country:
            method = f"structured_addressCountry:{structured_value}"
    _remove_user_generated_content(soup)
    page_path = urlparse(page_url).path.lower().rstrip("/")
    allow_visible_country = not page_path or "about" in page_path
    if not country and allow_visible_country:
        country, location = _country_from_text(soup.get_text(" ", strip=True))
        if country:
            method = f"explicit_site_location:{location}"

    contact_channel = ""
    contact_value = ""
    for anchor in soup.select("a[href^='mailto:']"):
        address = anchor.get("href", "").split(":", 1)[-1].split("?", 1)[0].strip().lower()
        if EMAIL_RE.fullmatch(address) and address.split("@", 1)[0] not in GENERIC_EMAIL_PREFIXES:
            contact_channel, contact_value = "Email", address
            break
    if not contact_value:
        for address in EMAIL_RE.findall(soup.get_text(" ", strip=True)):
            address = address.lower().strip(".>")
            if address.split("@", 1)[0] not in GENERIC_EMAIL_PREFIXES:
                contact_channel, contact_value = "Email", address
                break
    if not contact_value and soup.find("form") and "contact" in page_url.lower():
        contact_channel, contact_value = "Contact form", page_url

    commercial_label = ""
    visible = _plain_text(soup.get_text(" ", strip=True)).lower()
    for label, terms in COMMERCIAL_SIGNALS:
        if any(term in visible for term in terms):
            commercial_label = label
            break
    return SiteEvidence(
        country=country,
        country_url=page_url if country else "",
        country_method=method,
        contact_channel=contact_channel,
        contact_value=contact_value,
        contact_url=page_url if contact_value else "",
        commercial_label=commercial_label,
        commercial_url=page_url if commercial_label else "",
    )


def _merge_site_evidence(current: SiteEvidence, incoming: SiteEvidence) -> SiteEvidence:
    return SiteEvidence(
        country=current.country or incoming.country,
        country_url=current.country_url or incoming.country_url,
        country_method=current.country_method or incoming.country_method,
        contact_channel=current.contact_channel or incoming.contact_channel,
        contact_value=current.contact_value or incoming.contact_value,
        contact_url=current.contact_url or incoming.contact_url,
        commercial_label=current.commercial_label or incoming.commercial_label,
        commercial_url=current.commercial_url or incoming.commercial_url,
    )


async def _official_site_evidence(
    official_url: str, http: HttpClient, refresh: bool
) -> SiteEvidence:
    if not official_url.startswith(("http://", "https://")):
        return SiteEvidence()
    parsed = urlparse(official_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        robots_response = await http.get(robots_url, refresh=refresh)
        robots = RobotFileParser()
        robots.set_url(robots_url)
        robots.parse(robots_response.content.decode("utf-8", errors="replace").splitlines())
        if not robots.can_fetch("IncuBrixAssessmentResearch/1.0", official_url):
            return SiteEvidence()
    except httpx.HTTPStatusError as error:
        if error.response.status_code not in {404, 410}:
            return SiteEvidence()
        robots = RobotFileParser()
        robots.parse([])
    except (httpx.HTTPError, OSError):
        return SiteEvidence()

    try:
        response = await http.get(official_url, refresh=refresh, respect_robots=True)
    except (httpx.HTTPError, OSError):
        return SiteEvidence()
    if response.stale:
        return SiteEvidence()
    if re.search(rb"<(?:rss|feed|channel)\b", response.content[:2000], re.IGNORECASE):
        return SiteEvidence()
    evidence = _site_page_evidence(response.url, response.content)
    soup = BeautifulSoup(
        response.content[:MAX_SITE_PARSE_BYTES].decode("utf-8", errors="replace"), "html.parser"
    )
    candidate_pages: list[str] = []
    for anchor in soup.find_all("a", href=True):
        label = f"{anchor.get_text(' ', strip=True)} {anchor.get('href', '')}".lower()
        if any(word in label for word in ("about", "contact")):
            url = urljoin(response.url, str(anchor["href"]))
            if urlparse(url).netloc == urlparse(response.url).netloc and url not in candidate_pages:
                candidate_pages.append(url)
    for page_url in candidate_pages[:2]:
        if not robots.can_fetch("IncuBrixAssessmentResearch/1.0", page_url):
            continue
        try:
            page = await http.get(page_url, refresh=refresh, respect_robots=True)
        except (httpx.HTTPError, OSError):
            continue
        if page.stale:
            continue
        evidence = _merge_site_evidence(evidence, _site_page_evidence(page.url, page.content))
        if evidence.country and evidence.contact_value and evidence.commercial_label:
            break
    return evidence


def _country_from_feed(
    feed: feedparser.FeedParserDict, candidate: PodcastCandidate
) -> tuple[str, str, str]:
    """Return country only from an independent public location signal, never storefront."""
    official_link = str(feed.feed.get("link") or "")
    hostname = (urlparse(official_link).hostname or "").lower()
    for suffix, country in TLD_COUNTRIES.items():
        if hostname.endswith(suffix):
            return country, official_link, f"official_site_ccTLD:{suffix}"

    text = _plain_text(
        " ".join(
            str(feed.feed.get(field) or "")
            for field in ("title", "author", "subtitle", "summary", "description")
        )
    ).lower()
    country, location = _country_from_text(text)
    if country:
        return country, candidate.feed_url, f"explicit_feed_location:{location}"
    return "", "", ""


def _episodes(feed: feedparser.FeedParserDict, as_of: date | None = None) -> list[Episode]:
    values: list[Episode] = []
    seen: set[tuple[str, str]] = set()
    for entry in feed.entries:
        published = _parse_date(entry.get("published_parsed") or entry.get("updated_parsed"))
        if as_of is not None and published is not None and not 0 <= (as_of - published).days <= 60:
            continue
        url = str(entry.get("link") or "")
        title = _plain_text(str(entry.get("title") or ""))
        if not published or not url or not title:
            continue
        identity = (title.casefold().strip(), published.isoformat())
        if identity in seen:
            continue
        seen.add(identity)
        values.append(
            Episode(
                title=title,
                url=url,
                published_date=published.isoformat(),
                duration_minutes=_duration_minutes(entry.get("itunes_duration")),
                summary=_plain_text(str(entry.get("summary") or ""))[:5000],
            )
        )
    return sorted(values, key=lambda item: item.published_date, reverse=True)


async def discover(
    config: Config, http: HttpClient, refresh: bool = False
) -> list[PodcastCandidate]:
    tasks = []
    for storefront in ("us", "gb", "ca", "au", "ie", "nz", "sg"):
        for term in config.search_terms:
            tasks.append(
                http.get(
                    ITUNES_SEARCH_URL,
                    params={
                        "term": term,
                        "country": storefront,
                        "media": "podcast",
                        "entity": "podcast",
                        "limit": config.itunes_result_limit,
                        "explicit": "No",
                    },
                    refresh=refresh,
                )
            )
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    candidates: dict[str, PodcastCandidate] = {}
    for response in responses:
        if isinstance(response, Exception):
            continue
        payload = response.json()
        if not isinstance(payload, dict):
            continue
        for item in payload.get("results", []):
            feed_url = str(item.get("feedUrl") or "")
            apple_id = str(item.get("collectionId") or item.get("trackId") or "")
            if not feed_url.startswith(("http://", "https://")) or not apple_id:
                continue
            key = apple_id
            if key not in candidates:
                candidates[key] = PodcastCandidate(
                    apple_id=apple_id,
                    artist_name=_plain_text(str(item.get("artistName") or "")),
                    collection_name=_plain_text(str(item.get("collectionName") or "")),
                    country_iso2="",
                    feed_url=feed_url,
                    apple_url=str(item.get("collectionViewUrl") or item.get("trackViewUrl") or ""),
                    genre=str(item.get("primaryGenreName") or ""),
                    release_date=str(item.get("releaseDate") or ""),
                )
    ordered = sorted(candidates.values(), key=lambda item: item.apple_id)
    return ordered[: config.max_candidates]


async def enrich(
    candidate: PodcastCandidate,
    config: Config,
    http: HttpClient,
    refresh: bool = False,
    parse_executor: Executor | None = None,
) -> EnrichmentResult:
    podcast_index = candidate.discovery_provider == "Podcast Index API"
    lead = Lead(
        creator_name=candidate.artist_name,
        country_iso2=candidate.country_iso2,
        profile_url=candidate.apple_url,
        stable_creator_id=f"apple-podcast:{candidate.apple_id}",
        checked_date=config.checked_date,
        source_feed_url=candidate.feed_url,
        source_api_url=(
            f"https://api.podcastindex.org/api/1.0/podcasts/byitunesid?id={candidate.apple_id}"
            if podcast_index
            else f"https://itunes.apple.com/lookup?id={candidate.apple_id}&entity=podcast"
        ),
        source_license=(
            "Public Podcast Index metadata and publisher RSS; no media redistribution licence implied"
            if podcast_index
            else "Public Apple metadata and publisher RSS; no media redistribution licence implied"
        ),
        metadata={
            "collection_name": candidate.collection_name,
            "genre": candidate.genre,
            "discovery_provider": candidate.discovery_provider,
        },
    )
    try:
        response = await http.get(candidate.feed_url, refresh=refresh)
    except (httpx.HTTPError, OSError) as error:
        lead.rejection_reason = f"feed_fetch_failed:{type(error).__name__}"
        return EnrichmentResult(lead, lead.rejection_reason)

    # Podcast feeds can contain years of embedded HTML and exceed 20 MB. Publishers conventionally
    # place current items first; parsing a bounded prefix preserves exact evidence for recent items
    # while preventing one oversized feed from blocking an entire batch. A truncated/oldest-first
    # feed simply fails qualification, which is conservative.
    feed_bytes = response.content[:MAX_FEED_PARSE_BYTES]
    if len(response.content) > MAX_FEED_PARSE_BYTES:
        # Drop the partial last item so byte truncation cannot create an apparent content item.
        item_end = feed_bytes.rfind(b"</item>")
        entry_end = feed_bytes.rfind(b"</entry>")
        if item_end >= 0:
            feed_bytes = feed_bytes[: item_end + len(b"</item>")] + b"</channel></rss>"
        elif entry_end >= 0:
            feed_bytes = feed_bytes[: entry_end + len(b"</entry>")] + b"</feed>"
        else:
            lead.rejection_reason = "oversized_feed_without_complete_item_in_parse_limit"
            return EnrichmentResult(lead, lead.rejection_reason)
    raw_xml = feed_bytes.decode("utf-8", errors="replace")
    if parse_executor is None:
        feed_data, entry_data, bozo = _parse_feed_payload(feed_bytes)
    else:
        loop = asyncio.get_running_loop()
        feed_data, entry_data, bozo = await loop.run_in_executor(
            parse_executor, _parse_feed_payload, feed_bytes
        )
    feed = feedparser.FeedParserDict({"feed": feed_data, "entries": entry_data, "bozo": bozo})
    if getattr(feed, "bozo", False) and not feed.entries:
        lead.rejection_reason = "invalid_or_empty_feed"
        return EnrichmentResult(lead, lead.rejection_reason)

    today = date.fromisoformat(config.checked_date)
    episodes = _episodes(feed, as_of=today)
    if not episodes:
        lead.rejection_reason = "no_dated_public_episodes_in_last_60_days"
        return EnrichmentResult(lead, lead.rejection_reason)

    within_30 = [
        e for e in episodes if 0 <= (today - date.fromisoformat(e.published_date)).days <= 30
    ]
    longform_60 = [
        e
        for e in episodes
        if 0 <= (today - date.fromisoformat(e.published_date)).days <= 60
        and e.duration_minutes is not None
        and e.duration_minutes >= config.min_episode_minutes
    ]
    if len(within_30) < config.min_items_30d and len(longform_60) < config.min_longform_60d:
        lead.rejection_reason = "activity_threshold_not_met"
        return EnrichmentResult(lead, lead.rejection_reason)

    if not _language_is_english(feed, episodes):
        lead.rejection_reason = "content_not_mainly_english"
        return EnrichmentResult(lead, lead.rejection_reason)

    creator = _creator_name(candidate, feed)
    if not _looks_like_person(creator, candidate.collection_name):
        lead.rejection_reason = "not_clearly_creator_led"
        return EnrichmentResult(lead, lead.rejection_reason)

    country, country_evidence_url, country_method = _country_from_feed(feed, candidate)
    owner_email = _extract_owner_email(raw_xml)
    contact_channel = "Email" if owner_email else ""
    contact_value = owner_email
    contact_evidence_url = candidate.feed_url if owner_email else ""
    commercial_label, commercial_url = _commercial_signal(episodes)
    if not commercial_label:
        feed_summary = _plain_text(str(feed.feed.get("summary") or ""))
        fallback_episode = Episode(
            "", str(feed.feed.get("link") or candidate.apple_url), "", None, feed_summary
        )
        commercial_label, commercial_url = _commercial_signal([fallback_episode])

    if not country or not contact_value or not commercial_label:
        site = await _official_site_evidence(str(feed.feed.get("link") or ""), http, refresh)
        country = country or site.country
        country_evidence_url = country_evidence_url or site.country_url
        country_method = country_method or site.country_method
        contact_channel = contact_channel or site.contact_channel
        contact_value = contact_value or site.contact_value
        contact_evidence_url = contact_evidence_url or site.contact_url
        commercial_label = commercial_label or site.commercial_label
        commercial_url = commercial_url or site.commercial_url

    lead.country_iso2 = country
    lead.metadata["country_evidence_url"] = country_evidence_url
    lead.metadata["country_evidence_method"] = country_method

    eligible_episodes = [
        episode for episode in episodes if episode.published_date <= config.checked_date
    ]
    latest = eligible_episodes[0]
    lead.metadata["feed_fetched_at"] = datetime.fromtimestamp(response.fetched_at, UTC).isoformat()
    lead.metadata["feed_stale"] = response.stale
    lead.metadata["feed_sha256"] = hashlib.sha256(response.content).hexdigest()
    lead.metadata["official_site_url"] = str(feed.feed.get("link") or "")
    lead.metadata["activity_items"] = [
        {
            "title": e.title,
            "url": e.url,
            "date": e.published_date,
            "duration_minutes": e.duration_minutes,
        }
        for e in episodes
        if e in within_30 or e in longform_60
    ]
    cadence = len(within_30)
    duration_text = f"{latest.duration_minutes}-minute " if latest.duration_minutes else ""
    first_name = creator.split()[0] if creator.split() else creator
    lead.creator_name = creator
    lead.last_content_date = latest.published_date
    lead.recent_content_url = latest.url
    lead.content_count_30d = len(within_30)
    lead.longform_count_60d = len(longform_60)
    lead.monetization_signal = commercial_label
    lead.monetization_evidence_url = commercial_url
    lead.incubrix_need = (
        f"Repurposing opportunity: {len(longform_60)} verified long-form episodes in 60 days; "
        "each can become platform-specific clips, captions and posts. This is an evidence-based "
        "workflow inference, not a claimed pain point."
    )
    lead.need_evidence_url = latest.url
    lead.best_channel = contact_channel
    lead.channel_handle_or_url = contact_value
    lead.channel_evidence_url = contact_evidence_url
    lead.backup_channel = ""
    lead.personalization_hook = (
        f"Published the {duration_text}episode “{latest.title}” on {latest.published_date}; "
        f"{cadence} items verified in the last 30 days."
    )
    lead.first_message = (
        f"Hi {first_name} — {config.sender_name} here, an {config.sender_context}. I saw that you published "
        f"“{latest.title}” on {latest.published_date}. IncuBrix can turn one long-form episode "
        "into platform-ready clips, captions and posts, then schedule them from one workspace. "
        "Would a 15-minute look at a repurposing workflow for this episode be useful? "
        "If it is not relevant, reply ‘no’ and I will not follow up."
    )
    lead.follow_up_1 = (
        f"Hi {first_name} — {config.sender_name}, {config.sender_context}, following up. "
        f"One idea for “{latest.title}”: test a short clip around the "
        "episode’s central question, with burned-in captions and a link back to the full episode. "
        "I can show how IncuBrix prepares those variants in one workflow. Worth a quick look? "
        "Reply ‘no’ and I will close this out."
    )
    lead.follow_up_2 = (
        f"Last note from {config.sender_name}, {config.sender_context}, {first_name}. "
        f"Your episode “{latest.title}” suggests a repeatable source of "
        "long-form material for clips and posts. If consolidating that work is a priority, I can "
        "share the IncuBrix workflow; otherwise I will not contact you again. Reply 'no' to opt out."
    )
    lead.lead_score = round(
        min(100.0, 55 + min(20, len(longform_60) * 4) + min(10, cadence) + 10 + 5), 1
    )
    lead.candidate_status = "Needs review"
    lead.rejection_reason = "creator_specific_evidence_review_required"
    lead.completeness_check = "REVIEW REQUIRED"
    lead.evidence_notes = (
        f"RSS retrieved {lead.metadata['feed_fetched_at']}; possible contact copied from "
        f"{contact_evidence_url}; activity calculated from dated feed entries; monetization was "
        f"suggested as {commercial_label}; country hint via {country_method} at "
        f"{country_evidence_url}."
    )
    return EnrichmentResult(lead)


def deduplicate(candidates: Iterable[PodcastCandidate]) -> list[PodcastCandidate]:
    by_id: dict[str, PodcastCandidate] = {}
    seen_feeds: set[str] = set()
    for candidate in candidates:
        parsed = urlparse(candidate.feed_url)
        normalized_feed = f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"
        if candidate.apple_id in by_id or normalized_feed in seen_feeds:
            continue
        by_id[candidate.apple_id] = candidate
        seen_feeds.add(normalized_feed)
    return list(by_id.values())
