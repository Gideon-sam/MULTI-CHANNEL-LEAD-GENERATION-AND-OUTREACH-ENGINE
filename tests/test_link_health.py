import asyncio
import time

import httpx

from incubrix_engine.http_client import CachedResponse
from incubrix_engine.link_health import check_link


def test_404_and_stale_success_are_not_working_link_proof():
    class DeadSource:
        async def get(self, url, **kwargs):
            response = httpx.Response(404, request=httpx.Request("GET", url))
            response.raise_for_status()

    class StaleSource:
        async def get(self, url, **kwargs):
            return CachedResponse(url, 200, {}, b"old page", time.time(), True, True)

    dead = asyncio.run(check_link("https://example.test/dead", DeadSource()))
    stale = asyncio.run(check_link("https://example.test/old", StaleSource()))
    assert dead["status"] == "not_found" and dead["http_status"] == 404
    assert stale["status"] == "unverified_stale_fallback" and stale["http_status"] is None


def test_malformed_link_does_not_make_a_network_request():
    result = asyncio.run(check_link("example.test/no-scheme", None))
    assert result["status"] == "malformed"
