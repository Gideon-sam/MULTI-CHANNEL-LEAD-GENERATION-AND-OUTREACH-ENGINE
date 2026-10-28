"""Reproducible measured engine demonstrations on real discovery inputs."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import httpx

from .config import Config
from .exporters import _write_csv
from .files import write_text
from .http_client import HttpClient
from .inputs import load_candidates
from .logging_utils import configure_logging
from .pipeline import run_pipeline


async def run_demo(root: Path, count: int = 4) -> dict:
    if count < 2:
        raise ValueError("Demo requires at least two inputs to show continued processing")
    candidates = sorted(
        load_candidates(root / "inputs/cached_discovery_expanded.csv"),
        key=lambda candidate: (candidate.release_date, candidate.apple_id),
        reverse=True,
    )
    directory = root / "verification/current"
    directory.mkdir(parents=True, exist_ok=True)
    selected = candidates[: count + 2]
    results = {}
    for label, size, refresh in (
        ("normal", count, False),
        ("repeat", count, False),
        ("new_input_refresh", count + 2, True),
        ("failure_recovery", count, True),
    ):
        input_path = directory / f"{label}_inputs.csv"
        _write_csv(
            input_path,
            [asdict(candidate) for candidate in selected[:size]],
            list(asdict(selected[0])),
        )
        config = replace(
            Config.load(root / "config/production.json"),
            sender_name="[YOUR NAME]",
            output_dir=f"verification/current/{label}",
            state_dir="verification/current/state",
            max_candidates=size,
            network_concurrency=4,
            per_host_concurrency=2,
            request_timeout_seconds=8,
            request_retries=1,
        )
        logger = configure_logging(directory / f"{label}.jsonl")
        if label == "failure_recovery":
            original_get = HttpClient.get
            target = selected[0].feed_url
            injected = False

            async def simulated_failure(
                self, url, _target=target, _logger=logger, _get=original_get, **kwargs
            ):
                nonlocal injected
                if url == _target and not injected:
                    injected = True
                    _logger.warning(
                        "injected_source_http_404",
                        extra={
                            "data": {
                                "stable_creator_id": f"apple-podcast:{selected[0].apple_id}",
                                "simulation": True,
                            }
                        },
                    )
                    response = httpx.Response(404, request=httpx.Request("GET", url))
                    response.raise_for_status()
                return await _get(self, url, **kwargs)

            with patch.object(HttpClient, "get", simulated_failure):
                result = await run_pipeline(
                    root, config, logger, refresh=refresh, input_path=input_path
                )
        else:
            result = await run_pipeline(
                root, config, logger, refresh=refresh, input_path=input_path
            )
        with sqlite3.connect(root / config.state_dir / "leads.sqlite3") as connection:
            total, distinct = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT stable_creator_id) FROM leads"
            ).fetchone()
            stored_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT stable_creator_id FROM leads ORDER BY stable_creator_id"
                )
            ]
        manifest = json.loads(
            (root / config.output_dir / "manifest.json").read_text(encoding="utf-8")
        )
        results[label] = {
            "metrics": result.metrics,
            "http": manifest["http"],
            "stored_rows": total,
            "stored_unique_ids": distinct,
            "duplicate_state_rows": total - distinct,
            "stored_ids": stored_ids,
            "official_leads": len(result.leads),
            "acceptance_passed": result.all_checks_passed,
            "actual_api_cost": None,
            "log": f"verification/current/{label}.jsonl",
        }
        if label == "failure_recovery":
            results[label].update(
                simulated_failure=True,
                injected=injected,
                processed_remaining=size - 1,
                continued_after_failure=result.metrics["input_size"] == size
                and any(
                    lead.stable_creator_id == f"apple-podcast:{selected[0].apple_id}"
                    and "feed_fetch_failed" in lead.rejection_reason
                    for lead in result.rejected
                ),
            )
    results["repeat_keeps_stable_state_ids"] = (
        results["normal"]["stored_ids"] == results["repeat"]["stored_ids"]
    )
    results["refresh_contains_new_ids"] = set(results["normal"]["stored_ids"]) < set(
        results["new_input_refresh"]["stored_ids"]
    )
    results["note"] = (
        "Real discovery records and public network runs. Only the one declared HTTP 404 is simulated. This is a small execution test; it is not a 5,000-lead refresh or a completed seed test. Costs are unmeasured."
    )
    write_text(directory / "run_evidence.json", json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo(Path.cwd())), indent=2))
