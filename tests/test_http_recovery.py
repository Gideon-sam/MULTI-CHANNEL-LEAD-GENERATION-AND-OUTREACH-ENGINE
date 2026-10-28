from __future__ import annotations

import asyncio

import httpx

from incubrix_engine.http_client import HttpClient


def test_stale_cache_recovers_from_temporary_failure(tmp_path) -> None:
    async def scenario() -> None:
        async with HttpClient(
            tmp_path,
            concurrency=1,
            per_host_concurrency=1,
            timeout_seconds=1,
            retries=1,
            max_age_hours=0,
            resolve_dns=False,
        ) as client:
            request = httpx.Request("GET", "https://example.test/feed")

            async def success(*_args, **_kwargs):
                return httpx.Response(200, content=b"verified", request=request)

            client.client.get = success  # type: ignore[method-assign]
            first = await client.get("https://example.test/feed", refresh=True)
            assert first.content == b"verified"
            assert not first.from_cache

            async def failure(*_args, **_kwargs):
                raise httpx.ConnectError("temporary", request=request)

            client.client.get = failure  # type: ignore[method-assign]
            recovered = await client.get("https://example.test/feed", refresh=True)
            assert recovered.content == b"verified"
            assert recovered.from_cache
            assert recovered.stale
            assert recovered.fetched_at == first.fetched_at

    asyncio.run(scenario())
