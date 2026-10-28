from __future__ import annotations

from incubrix_engine.sources.apple_podcasts import (
    _country_from_text,
    _duration_minutes,
    _extract_owner_email,
    _looks_like_person,
    _site_page_evidence,
)


def test_duration_parser_handles_seconds_and_clock_formats() -> None:
    assert _duration_minutes("3600") == 60
    assert _duration_minutes("42:30") == 42
    assert _duration_minutes("1:02:00") == 62
    assert _duration_minutes("unknown") is None


def test_contact_is_copied_only_from_feed_header() -> None:
    xml = """
    <rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
      <itunes:owner><itunes:name>Alex</itunes:name><itunes:email>alex@example.com</itunes:email></itunes:owner>
      <item><description>Guest: guest@example.net</description></item>
    </channel></rss>
    """
    assert _extract_owner_email(xml) == "alex@example.com"


def test_episode_guest_email_is_never_selected() -> None:
    xml = "<rss><channel><item><description>guest@example.net</description></item></channel></rss>"
    assert _extract_owner_email(xml) == ""


def test_creator_led_filter_excludes_publications() -> None:
    assert _looks_like_person("Alex Hormozi", "The Alex Hormozi Podcast")
    assert not _looks_like_person("Bloomberg Media", "Masters in Business")
    assert not _looks_like_person("Startup Junkie", "The Startup Junkies Podcast")
    assert not _looks_like_person("Australian Broadcasting Corporation", "This Working Life")


def test_country_requires_an_identity_location_construction() -> None:
    assert _country_from_text("A creator based in Toronto, Canada") == ("CA", "toronto")
    assert _country_from_text("An episode about travel in Canada") == ("", "")


def test_site_evidence_uses_structured_country_and_exact_mailto() -> None:
    page = b"""<html><head><script type="application/ld+json">
    {"@type":"Person","address":{"addressCountry":"GB"}}
    </script></head><body><a href="mailto:alex@example.co.uk">Email Alex</a>
    <p>Book a coaching call.</p></body></html>"""
    evidence = _site_page_evidence("https://example.co.uk/about", page)
    assert evidence.country == "GB"
    assert evidence.contact_value == "alex@example.co.uk"
    assert evidence.commercial_label == "Course/coaching"


def test_contact_page_comments_cannot_supply_country_or_email() -> None:
    page = b"""<html><body><h1>Contact</h1><div class="comments">
    <p>I am based in Australia. Email visitor@example.com.</p></div></body></html>"""
    evidence = _site_page_evidence("https://creator.example/contact/", page)
    assert evidence.country == ""
    assert evidence.contact_value == ""
