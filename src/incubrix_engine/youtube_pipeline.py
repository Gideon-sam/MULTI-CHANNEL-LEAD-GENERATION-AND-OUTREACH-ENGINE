from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from .config import Config
from .exporters import export_all
from .files import write_text
from .http_client import HttpClient
from .launch_kit import write_launch_kit
from .outreach import write_outreach
from .pipeline import PipelineResult, _dedupe_leads, _select_final
from .sources.youtube import (
    YouTubeApi,
    api_key_from_environment,
    discover_channels,
    fetch_channel_videos,
    qualify_channel,
)
from .storage import LeadStore
from .validation import validate
from .workbook import build_workbook


async def run_youtube_pipeline(
    root: Path, config: Config, logger: logging.Logger, *, refresh: bool = False
) -> PipelineResult:
    started = time.perf_counter()
    config.ensure_directories(root)
    output_dir = root / config.output_dir
    store = LeadStore(root / config.state_dir / "leads.sqlite3")
    try:
        async with (
            YouTubeApi(
                api_key_from_environment(),
                root / config.cache_dir / "youtube_api",
                config.cache_max_age_hours,
                refresh,
            ) as api,
            HttpClient(
                root / config.cache_dir,
                config.network_concurrency,
                config.per_host_concurrency,
                config.request_timeout_seconds,
                config.request_retries,
                config.cache_max_age_hours,
            ) as http,
        ):
            logger.info("youtube_discovery_started")
            candidates = await discover_channels(config, api)
            with (output_dir / "discovered_inputs.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                fields = [
                    "channel_id",
                    "title",
                    "description",
                    "custom_url",
                    "country_iso2",
                    "subscriber_count",
                    "matched_terms",
                ]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for candidate in candidates:
                    row = asdict(candidate)
                    row["matched_terms"] = " | ".join(candidate.matched_terms)
                    writer.writerow({field: row[field] for field in fields})
            logger.info(
                "youtube_discovery_completed", extra={"data": {"candidates": len(candidates)}}
            )
            videos = await fetch_channel_videos(candidates, http, api, config, refresh)
            rows = [
                qualify_channel(candidate, videos.get(candidate.channel_id, []), config)
                for candidate in candidates
            ]
            store.upsert_many(rows)
            qualified = [lead for lead in rows if lead.candidate_status == "Qualified"]
            rejected = [lead for lead in rows if lead.candidate_status != "Qualified"]
            unique, duplicates_removed = _dedupe_leads(qualified)
            leads = _select_final(unique, config)
            metrics: dict[str, float | int] = {
                "target_leads": config.target_leads,
                "input_size": len(rows),
                "qualified_pool": len(unique),
                "produced": len(leads),
                "rejected": len(rejected),
                "duplicates_removed": duplicates_removed,
                "pending_review": 0,
                "runtime_minutes": round((time.perf_counter() - started) / 60, 2),
                "youtube_api_requests": api.requests,
                "youtube_api_cache_hits": api.cache_hits,
                "youtube_estimated_quota_units": api.estimated_quota_units,
            }
            checks = validate(leads, config, output_dir / "validation_report.json")
            export_all(leads, rejected, output_dir, metrics=metrics)
            write_outreach(leads, output_dir)
            write_launch_kit(leads, output_dir / "launch-kit.md")
            template = root / config.workbook_template
            if template.exists():
                build_workbook(
                    template,
                    output_dir / "IncuBrix_Submission_Workbook_Draft.xlsx",
                    leads,
                    config,
                    metrics,
                )
            passed = all(check.passed for check in checks)
            manifest = {
                "submission_ready": False,
                "lead_checks_passed": passed,
                "source": "YouTube Data API and public channel feeds",
                "metrics": metrics,
                "http": http.stats,
                "config": asdict(config),
                "files": {
                    str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in output_dir.rglob("*")
                    if path.is_file() and path.name not in {"manifest.json", "progress.json"}
                },
                "pending_external": [
                    "authenticated_product_test",
                    "three_channel_seed_test",
                    "unedited_videos",
                    "candidate_declaration",
                ],
            }
            write_text(output_dir / "manifest.json", json.dumps(manifest, indent=2))
            write_text(
                output_dir / "progress.json",
                json.dumps(
                    {"status": "completed", **metrics, "lead_checks_passed": passed}, indent=2
                ),
            )
            logger.info("run_completed", extra={"data": {**metrics, "validation_passed": passed}})
            return PipelineResult(leads, rejected, metrics, passed)
    finally:
        store.close()
