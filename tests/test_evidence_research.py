import asyncio

from incubrix_engine.evidence_research import fetch_page, page_evidence, seed_urls
from incubrix_engine.http_client import CachedResponse


def test_search_identity_is_never_assumed_and_platform_pages_are_skipped():
    row = {"metadata": {}, "channel_handle_or_url": ""}
    hints = {"results": [{"url": "https://youtube.com/watch?v=a"}, {"url": "https://person.test"}]}
    assert seed_urls(row, hints) == [("https://person.test", "search_match_ownership_unverified")]


def test_excerpts_exclude_scripts_and_flag_placeholder_text():
    data = page_evidence(
        b"<title>About</title><script>guessed@test.com</script><p>Contact me for coaching.</p>"
        b'<a href="/contact">Contact</a><time datetime="2026-10-01">October</time>'
        b"<p>Lorem ipsum</p>",
        "https://person.test/about",
    )
    assert "guessed" not in data["excerpt"]
    assert "Contact me for coaching." in data["excerpt"]
    assert "PLACEHOLDER" in data["review_warning"]
    assert data["next_pages"] == ["https://person.test/contact"]
    assert data["content_dates"] == "2026-10-01"


def test_stale_fetch_is_not_evidence():
    class FakeHttp:
        async def get(self, url, **kwargs):
            return CachedResponse(url, 200, {}, b"Old contact text", 1234, True, True)

    result, links = asyncio.run(
        fetch_page(
            FakeHttp(),
            {"stable_creator_id": "synthetic:1"},
            "https://person.test",
            "test",
        )
    )
    assert result["status"] == "stale_fallback"
    assert result["excerpt"] == "" and links == []
