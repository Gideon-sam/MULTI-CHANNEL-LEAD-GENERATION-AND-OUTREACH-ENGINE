"""Bounded web evidence discovery. Search results are hints, never qualification proof."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Self

import httpx

from ..models import Lead

API_URL = "https://api.tavily.com/search"


class TavilyApi:
    """Bearer-token client whose cache and errors never contain the credential."""

    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        max_age_hours: int = 168,
        refresh: bool = False,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TAVILY_API_KEY is required")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_age_seconds = max_age_hours * 3600
        self.refresh = refresh
        self.requests = 0
        self.cache_hits = 0
        self.credits_used = 0
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            headers={
                "Authorization": "Bearer " + api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.client.aclose()

    async def search(self, query: str, max_results: int = 5) -> dict:
        body = {
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
            "safe_search": True,
            "exclude_domains": ["podcasts.apple.com"],
        }
        material = json.dumps(body, sort_keys=True, separators=(",", ":"))
        cache_path = self.cache_dir / (hashlib.sha256(material.encode()).hexdigest() + ".json")
        if not self.refresh and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if 0 <= age <= self.max_age_seconds:
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                    self.cache_hits += 1
                    return payload
                except (OSError, ValueError, TypeError):
                    pass
        try:
            response = await self.client.post(API_URL, json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(f"Tavily API request failed ({error.response.status_code})") from None
        if not isinstance(payload, dict):
            raise TypeError("Tavily API returned an invalid payload")
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(cache_path)
        self.requests += 1
        usage = payload.get("usage") or {}
        self.credits_used += int(usage.get("credits") or 0)
        return payload


def _query(lead: Lead) -> str:
    show = str(lead.metadata.get("collection_name") or "")
    quoted = " ".join(value for value in (lead.creator_name, show) if value).strip()
    return f'"{quoted}" official website business contact creator'.strip()


async def evidence_hints(leads: list[Lead], api: TavilyApi, limit: int) -> list[dict]:
    """Return search hints for manual/fetched-page review without changing lead status."""
    selected = sorted(leads, key=lambda lead: (-lead.lead_score, lead.stable_creator_id))[:limit]
    semaphore = asyncio.Semaphore(4)

    async def one(lead: Lead) -> dict:
        query = _query(lead)
        async with semaphore:
            try:
                payload = await api.search(query)
                error = ""
            except (RuntimeError, TypeError, httpx.HTTPError) as failure:
                payload = {}
                error = type(failure).__name__
        results = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                {
                    "url": url,
                    "title": str(item.get("title") or ""),
                    "search_snippet": str(item.get("content") or ""),
                    "score": item.get("score"),
                    "status": "SEARCH HINT ONLY - fetch and verify before use",
                }
            )
        return {
            "stable_creator_id": lead.stable_creator_id,
            "creator_name": lead.creator_name,
            "query": query,
            "searched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "results": results,
            "error_type": error,
            "qualification_changed": False,
        }

    return await asyncio.gather(*(one(lead) for lead in selected))


def api_key_from_environment() -> str:
    return os.environ.get("TAVILY_API_KEY", "").strip()
