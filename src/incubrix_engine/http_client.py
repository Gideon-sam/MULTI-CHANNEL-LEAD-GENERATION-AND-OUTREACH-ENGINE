from __future__ import annotations

import asyncio
import gzip
import hashlib
import ipaddress
import json
import random
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .files import atomic_destination

try:
    import truststore

    truststore.inject_into_ssl()
except (ImportError, RuntimeError):  # Linux containers generally use a current CA bundle.
    pass


@dataclass(frozen=True)
class CachedResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    fetched_at: float
    from_cache: bool
    stale: bool = False

    def json(self) -> object:
        return json.loads(self.content)


class HttpClient:
    """Async HTTP client with bounded concurrency, retries and an inspectable disk cache."""

    def __init__(
        self,
        cache_dir: Path,
        concurrency: int = 16,
        per_host_concurrency: int = 3,
        timeout_seconds: int = 25,
        retries: int = 3,
        max_age_hours: int = 168,
        *,
        resolve_dns: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.global_semaphore = asyncio.Semaphore(concurrency)
        self.per_host_concurrency = per_host_concurrency
        self.host_semaphores: dict[str, asyncio.Semaphore] = {}
        self.host_rate_locks: dict[str, asyncio.Lock] = {}
        self.host_next_request: dict[str, float] = {}
        self.public_hosts: set[str] = set()
        self.resolve_dns = resolve_dns
        self.robots: dict[str, RobotFileParser | None] = {}
        self.stats = {"network_requests": 0, "cache_hits": 0, "stale_fallbacks": 0, "failures": 0}
        self.timeout = httpx.Timeout(timeout_seconds)
        self.retries = retries
        self.max_age_seconds = max_age_hours * 3600
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            headers={
                "User-Agent": "IncuBrixAssessmentResearch/1.0",
                "Accept": "application/json, application/xml, text/xml, text/html;q=0.9, */*;q=0.5",
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots:
            policy = RobotFileParser()
            try:
                result = await self.get(origin + "/robots.txt")
                if result.stale:
                    self.robots[origin] = None
                    return False
                policy.parse(result.content.decode("utf-8", errors="replace").splitlines())
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in {404, 410}:
                    self.robots[origin] = None
                    return False
                policy.parse([])
            except (httpx.HTTPError, OSError, ValueError):
                self.robots[origin] = None
                return False
            self.robots[origin] = policy
        policy = self.robots[origin]
        return policy is not None and policy.can_fetch("IncuBrixAssessmentResearch/1.0", url)

    def _paths(self, url: str, params: dict[str, object] | None) -> tuple[Path, Path]:
        material = url + "?" + json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.body.gz", self.cache_dir / f"{digest}.json"

    def _read_cache(
        self, url: str, params: dict[str, object] | None, allow_stale: bool = False
    ) -> CachedResponse | None:
        body_path, meta_path = self._paths(url, params)
        legacy_body_path = body_path.with_suffix("")
        if not (body_path.exists() or legacy_body_path.exists()) or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age = time.time() - float(meta["fetched_at"])
            body = (
                gzip.decompress(body_path.read_bytes())
                if body_path.exists()
                else legacy_body_path.read_bytes()
            )
            if not 200 <= int(meta["status_code"]) < 300:
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if age > self.max_age_seconds and not allow_stale:
            return None
        return CachedResponse(
            url=meta["url"],
            status_code=int(meta["status_code"]),
            headers=meta.get("headers", {}),
            content=body,
            fetched_at=float(meta["fetched_at"]),
            from_cache=True,
            stale=age > self.max_age_seconds,
        )

    def _write_cache(
        self, url: str, params: dict[str, object] | None, response: httpx.Response
    ) -> CachedResponse:
        body_path, meta_path = self._paths(url, params)
        fetched_at = time.time()
        with atomic_destination(body_path) as temporary:
            temporary.write_bytes(gzip.compress(response.content, compresslevel=6))
        metadata = json.dumps(
            {
                "url": str(response.url),
                "status_code": response.status_code,
                "headers": {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() in {"content-type", "etag", "last-modified"}
                },
                "fetched_at": fetched_at,
            },
            indent=2,
        )
        with atomic_destination(meta_path) as temporary:
            temporary.write_text(metadata, encoding="utf-8")
        return CachedResponse(
            url=str(response.url),
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            fetched_at=fetched_at,
            from_cache=False,
        )

    async def get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        refresh: bool = False,
        _visited: frozenset[str] = frozenset(),
        respect_robots: bool = False,
    ) -> CachedResponse:
        parsed_target = urlparse(url)
        if (
            parsed_target.scheme not in {"http", "https"}
            or not parsed_target.hostname
            or parsed_target.username
        ):
            raise ValueError("Only public HTTP(S) sources without credentials are accepted")
        host_name = parsed_target.hostname.lower()
        if host_name in {"localhost", "metadata.google.internal"} or host_name.endswith(
            (".local", ".localhost", ".internal")
        ):
            raise ValueError("Local and metadata sources are not permitted")
        try:
            literal = ipaddress.ip_address(host_name)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ValueError("Private/reserved IP addresses are not public evidence")
        if parsed_target.port not in {None, 80, 443}:
            raise ValueError("Only standard HTTP(S) ports are accepted")
        if url in _visited or len(_visited) >= 9:
            raise httpx.TooManyRedirects("Redirect loop or too many redirects")
        if respect_robots and not await self.allowed_by_robots(url):
            raise httpx.RequestError("Source robots policy blocked or unavailable")
        if not refresh:
            cached = self._read_cache(url, params)
            if cached is not None:
                if respect_robots and not await self.allowed_by_robots(cached.url):
                    raise httpx.RequestError("Resolved source robots policy blocked or unavailable")
                self.stats["cache_hits"] += 1
                return cached

        if self.resolve_dns and host_name not in self.public_hosts:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo, host_name, None, 0, socket.SOCK_STREAM
            )
            if not addresses or any(
                not ipaddress.ip_address(row[4][0]).is_global for row in addresses
            ):
                raise ValueError("Source resolves to a private/reserved address")
            self.public_hosts.add(host_name)

        host = urlparse(url).netloc.lower()
        host_semaphore = self.host_semaphores.setdefault(
            host, asyncio.Semaphore(self.per_host_concurrency)
        )
        last_error: Exception | None = None
        redirect_to = ""
        # Take the host slot first. Otherwise many requests for one slow feed host can occupy
        # every global slot while waiting, starving unrelated creator sites.
        async with host_semaphore, self.global_semaphore:
            for attempt in range(self.retries):
                try:
                    # Apple's documented Search API ceiling is approximately 20 calls/minute.
                    # Cache hits do not consume this budget; every actual request/retry does.
                    interval = 3.1 if host == "itunes.apple.com" else 0.25
                    lock = self.host_rate_locks.setdefault(host, asyncio.Lock())
                    async with lock:
                        delay = self.host_next_request.get(host, 0) - time.monotonic()
                        if delay > 0:
                            await asyncio.sleep(delay)
                        self.host_next_request[host] = time.monotonic() + interval
                    self.stats["network_requests"] += 1
                    try:
                        async with asyncio.timeout(float(self.timeout.read or 25) * 2):
                            response = await self.client.get(url, params=params)
                    except TimeoutError as error:
                        raise httpx.ReadTimeout("Total request deadline exceeded") from error
                    if response.status_code in {301, 302, 303, 307, 308}:
                        redirect_to = urljoin(
                            str(response.url), response.headers.get("location", "")
                        )
                        break
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise httpx.HTTPStatusError(
                            f"retryable status {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    response.raise_for_status()
                    if len(response.content) > 32 * 1024 * 1024:
                        raise httpx.DecodingError("Source exceeds 32 MB response limit")
                    return self._write_cache(url, params, response)
                except (httpx.HTTPError, OSError) as error:
                    last_error = error
                    if isinstance(
                        error, httpx.HTTPStatusError
                    ) and error.response.status_code not in {429, 500, 502, 503, 504}:
                        break
                    if attempt + 1 < self.retries:
                        retry_after = 0.0
                        if isinstance(error, httpx.HTTPStatusError):
                            try:
                                retry_after = float(error.response.headers.get("retry-after", "0"))
                            except ValueError:
                                pass
                        await asyncio.sleep(min(60, max(retry_after, 2**attempt + random.random())))

        # Release host and global slots before following a redirect, including same-host redirects.
        if redirect_to:
            return await self.get(
                redirect_to,
                refresh=refresh,
                _visited=_visited | {url},
                respect_robots=respect_robots,
            )
        stale = self._read_cache(url, params, allow_stale=True)
        if stale is not None:
            self.stats["stale_fallbacks"] += 1
            # Even a recently cached body is degraded if the requested live refresh failed.
            from dataclasses import replace

            return replace(stale, stale=True)
        self.stats["failures"] += 1
        assert last_error is not None
        raise last_error
