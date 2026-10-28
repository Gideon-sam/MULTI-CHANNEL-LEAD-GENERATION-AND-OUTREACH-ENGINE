from __future__ import annotations

import asyncio

from incubrix_engine.models import Lead
from incubrix_engine.sources.tavily import _query, evidence_hints


class FakeApi:
    async def search(self, query: str, max_results: int = 5) -> dict:
        del query, max_results
        return {
            "results": [
                {
                    "url": "https://creator.example/about",
                    "title": "About Alex",
                    "content": "Public search excerpt",
                    "score": 0.8,
                }
            ]
        }


def test_query_uses_creator_and_show_without_claiming_evidence() -> None:
    lead = Lead(creator_name="Alex Creator", metadata={"collection_name": "Alex Creates"})
    assert "Alex Creator" in _query(lead) and "Alex Creates" in _query(lead)
    rows = asyncio.run(evidence_hints([lead], FakeApi(), 1))
    assert rows[0]["qualification_changed"] is False
    assert rows[0]["results"][0]["status"].startswith("SEARCH HINT ONLY")
