from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from .config import Config
from .delivery_support import safe_drafts
from .exporters import export_all
from .files import write_text
from .http_client import HttpClient
from .launch_kit import write_launch_kit
from .models import Lead
from .outreach import write_outreach
from .pipeline import PipelineResult, _dedupe_leads, _select_final
from .sources.youtube import (
    YouTubeApi,
    api_key_from_environment,
    discover_channels,
    qualify_channel,
)
from .sources.youtube_activity import fetch_upload_activity
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
            videos, ingestion = await fetch_upload_activity(candidates, api, config, logger)
            write_text(output_dir / "source_health.json", json.dumps(ingestion, indent=2))
            rows = []
            for candidate in candidates:
                activity = videos.get(candidate.channel_id, [])
                if ingestion[candidate.channel_id]["status"] != "available":
                    lead = Lead(
                        creator_name=candidate.title,
                        primary_platform="YouTube",
                        creator_segment="YouTuber/Video-first Creator",
                        stable_creator_id=f"youtube-channel:{candidate.channel_id}",
                        profile_url=f"https://www.youtube.com/channel/{candidate.channel_id}",
                        country_iso2=candidate.country_iso2,
                        candidate_status="Needs review",
                        rejection_reason="source_unavailable_activity_unknown",
                        checked_date=config.checked_date,
                    )
                else:
                    lead = qualify_channel(candidate, activity, config)
                lead.metadata["ingestion"] = ingestion[candidate.channel_id]
                lead.metadata["evidence_snapshots"] = {
                    lead.profile_url + "/about": api.snapshot(
                        "channels", candidate.channel_id, "snippet,brandingSettings,statistics"
                    ),
                    **{
                        video.url: api.snapshot(
                            "videos", video.video_id, "snippet,contentDetails,status"
                        )
                        for video in activity
                    },
                }
                lead.metadata["source_description"] = candidate.description
                lead.metadata["verification_limits"] = [
                    "Identity/commercial signals use existing heuristics",
                    "Public contact activity and business invitation require manual confirmation",
                    "Country is channel-declared; confirm creator location",
                    "HTTP access and exact evidence meaning require audit",
                ]
                lead.source_license = (
                    "Public YouTube Data API metadata; no media redistribution permission implied"
                )
                for field, value in safe_drafts(asdict(lead)).items():
                    setattr(lead, field, value)
                rows.append(lead)
            from .manual_decisions import apply_rejection, load_decisions
            decisions = load_decisions(root / "config/review_decisions.json")
            for lead in rows:
                apply_rejection(lead, decisions)
            store.upsert_many(rows)
            qualified = [lead for lead in rows if lead.candidate_status == "Qualified"]
            rejected = [lead for lead in rows if lead.candidate_status == "Rejected"]
            pending = [lead for lead in rows if lead.candidate_status == "Needs review"]
            unique, duplicates_removed = _dedupe_leads(qualified)
            leads = _select_final(unique, config)
            metrics: dict[str, float | int] = {
                "target_leads": config.target_leads,
                "input_size": len(rows),
                "qualified_pool": len(unique),
                "produced": len(leads),
                "rejected": len(rejected),
                "duplicates_removed": duplicates_removed,
                "pending_review": len(pending),
                "runtime_minutes": round((time.perf_counter() - started) / 60, 2),
                "youtube_api_requests": api.requests,
                "youtube_api_cache_hits": api.cache_hits,
                "youtube_network_attempts": sum(api.network_attempts.values()),
            }
            checks = validate(leads, config, output_dir / "validation_report.json")
            export_all(leads, rejected, output_dir, pending=pending, metrics=metrics)
            write_text(
                output_dir / "api_call_report.json",
                json.dumps(
                    {
                        "network_attempts_by_endpoint": dict(api.network_attempts),
                        "successful_requests": api.requests,
                        "cache_hits": api.cache_hits,
                        "actual_billed_cost": None,
                        "provider_quota_usage": None,
                        "note": "Actual client request counts. Provider billing/quota measurements require console evidence; no estimated cost is reported.",
                    },
                    indent=2,
                ),
            )
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
