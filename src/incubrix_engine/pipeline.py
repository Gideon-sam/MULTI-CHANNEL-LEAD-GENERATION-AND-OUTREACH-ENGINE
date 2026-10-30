from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config
from .exporters import export_all
from .files import write_text
from .http_client import HttpClient
from .inputs import load_candidates
from .launch_kit import write_launch_kit
from .models import Lead, PodcastCandidate
from .outreach import write_outreach
from .review import approve_candidate, load_reviews
from .review_workflow import export_review_workbook
from .sources.apple_podcasts import deduplicate, discover, enrich
from .storage import LeadStore
from .validation import validate
from .workbook import build_workbook


@dataclass(frozen=True)
class PipelineResult:
    leads: list[Lead]
    rejected: list[Lead]
    metrics: dict[str, float | int]
    all_checks_passed: bool


def _interleave(candidates: list[PodcastCandidate], config: Config) -> list[PodcastCandidate]:
    del config
    # Country is intentionally unknown until an independent feed/site signal is verified.
    return sorted(
        candidates, key=lambda candidate: (candidate.release_date, candidate.apple_id), reverse=True
    )


def _identity_key(lead: Lead) -> tuple[str, str]:
    name = re.sub(r"[^a-z0-9]", "", lead.creator_name.lower())
    contact = lead.channel_handle_or_url.lower().strip()
    return name, contact


def _dedupe_leads(leads: list[Lead]) -> tuple[list[Lead], int]:
    best_by_id: dict[str, Lead] = {}
    name_keys: set[str] = set()
    contact_keys: set[str] = set()
    identity_keys: set[str] = set()
    for lead in sorted(leads, key=lambda item: (-item.lead_score, item.stable_creator_id)):
        name_key, contact_key = _identity_key(lead)
        identity_key = str(lead.metadata.get("creator_identity_key", ""))
        if (
            lead.stable_creator_id in best_by_id
            or (name_key and name_key in name_keys)
            or (contact_key and contact_key in contact_keys)
            or (identity_key and identity_key in identity_keys)
        ):
            continue
        best_by_id[lead.stable_creator_id] = lead
        name_keys.add(name_key)
        contact_keys.add(contact_key)
        if identity_key:
            identity_keys.add(identity_key)
    unique = list(best_by_id.values())
    return unique, len(leads) - len(unique)


def _can_select(pool: list[Lead], config: Config) -> bool:
    if len(pool) < config.target_leads:
        return False
    countries = Counter(lead.country_iso2 for lead in pool)
    maximum = int(config.target_leads * config.max_country_share)
    usable = sum(min(count, maximum) for count in countries.values())
    return usable >= config.target_leads and sum(count > 0 for count in countries.values()) >= 3


def _select_final(pool: list[Lead], config: Config) -> list[Lead]:
    pool, _ = _dedupe_leads(pool)
    grouped: dict[str, list[Lead]] = defaultdict(list)
    for lead in pool:
        grouped[lead.country_iso2].append(lead)
    for values in grouped.values():
        values.sort(key=lambda item: (-item.lead_score, item.stable_creator_id))

    selected: list[Lead] = []
    selected_ids: set[str] = set()
    counts: Counter[str] = Counter()
    target_weight = sum(config.country_targets.values()) or 1
    desired = {
        country: round(config.target_leads * weight / target_weight)
        for country, weight in config.country_targets.items()
    }
    cap = int(config.target_leads * config.max_country_share)
    for country, amount in sorted(desired.items(), key=lambda item: item[1], reverse=True):
        take = min(amount, cap, len(grouped[country]), config.target_leads - len(selected))
        for lead in grouped[country][:take]:
            selected.append(lead)
            selected_ids.add(lead.stable_creator_id)
            counts[country] += 1

    remaining = sorted(
        (lead for lead in pool if lead.stable_creator_id not in selected_ids),
        key=lambda item: (-item.lead_score, item.stable_creator_id),
    )
    for lead in remaining:
        if len(selected) >= config.target_leads:
            break
        if counts[lead.country_iso2] >= cap:
            continue
        selected.append(lead)
        selected_ids.add(lead.stable_creator_id)
        counts[lead.country_iso2] += 1

    selected.sort(key=lambda item: (-item.lead_score, item.stable_creator_id))
    for index, lead in enumerate(selected, start=1):
        if lead.stable_creator_id.startswith("apple-podcast:"):
            lead.lead_id = "INC-" + lead.stable_creator_id.removeprefix("apple-podcast:")
        elif lead.stable_creator_id.startswith("youtube-channel:"):
            lead.lead_id = "INC-YT-" + lead.stable_creator_id.removeprefix("youtube-channel:")
        else:
            lead.lead_id = (
                "INC-" + hashlib.sha256(lead.stable_creator_id.encode("utf-8")).hexdigest()[:16]
            )
        lead.priority = "A" if index <= config.priority_a_count else ("B" if index <= 250 else "C")
    return sorted(selected, key=lambda item: item.lead_id)


async def run_pipeline(
    root: Path,
    config: Config,
    logger: logging.Logger,
    *,
    refresh: bool = False,
    input_path: Path | None = None,
    reviewed_only: bool = False,
) -> PipelineResult:
    started = time.perf_counter()
    config.ensure_directories(root)
    output_dir = root / config.output_dir
    store = LeadStore(root / config.state_dir / "leads.sqlite3")
    rejected: list[Lead] = []
    qualified_pool: list[Lead] = []
    pending: list[Lead] = []
    reviews = load_reviews(root / config.review_file)
    from .manual_decisions import apply_rejection, load_decisions
    decisions = load_decisions(root / "config/review_decisions.json")
    if reviewed_only and not reviews:
        store.close()
        raise ValueError("No reviews imported. Complete the human review workbook first.")
    try:
        parse_workers = min(8, max(2, os.cpu_count() or 2))
        parse_executor = ProcessPoolExecutor(max_workers=parse_workers)
        async with HttpClient(
            root / config.cache_dir,
            config.network_concurrency,
            config.per_host_concurrency,
            config.request_timeout_seconds,
            config.request_retries,
            config.cache_max_age_hours,
        ) as http:
            logger.info("discovery_started", extra={"data": {"source": "Apple Search API"}})
            candidates = deduplicate(
                load_candidates(input_path)
                if input_path
                else await discover(config, http, refresh=refresh)
            )[: config.max_candidates]
            if reviewed_only:
                candidates = [c for c in candidates if f"apple-podcast:{c.apple_id}" in reviews]
                if not candidates:
                    raise ValueError("No input IDs match the imported reviews")
            with (output_dir / "discovered_inputs.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(PodcastCandidate.__dataclass_fields__)
                )
                writer.writeheader()
                writer.writerows(asdict(candidate) for candidate in candidates)
            ordered = _interleave(candidates, config)
            logger.info(
                "discovery_completed",
                extra={
                    "data": {
                        "candidates": len(candidates),
                        "countries": Counter(c.country_iso2 for c in candidates),
                    }
                },
            )
            # Keep work flowing as individual sources finish; publish progress every window.
            batch_size = max(40, config.network_concurrency)

            slots = asyncio.Semaphore(config.network_concurrency)

            async def bounded_enrich(candidate: PodcastCandidate):
                async with slots:
                    try:
                        from .sources.apple_podcasts import EnrichmentResult
                        rejected_lead = Lead(
                            stable_creator_id=f"apple-podcast:{candidate.apple_id}",
                            creator_name=candidate.artist_name, profile_url=candidate.apple_url,
                            source_feed_url=candidate.feed_url, checked_date=config.checked_date,
                        )
                        if apply_rejection(rejected_lead, decisions):
                            return candidate, EnrichmentResult(rejected_lead)
                        async with asyncio.timeout(90):
                            result = await enrich(
                                candidate,
                                config,
                                http,
                                refresh=refresh,
                                parse_executor=parse_executor,
                                identity_reviewed=(
                                    reviewed_only
                                    and f"apple-podcast:{candidate.apple_id}" in reviews
                                ),
                            )
                            if result.lead.candidate_status == "Needs review":
                                await approve_candidate(
                                    result.lead,
                                    reviews.get(result.lead.stable_creator_id),
                                    config,
                                    http,
                                    refresh,
                                )
                            return candidate, result
                    except Exception as error:  # noqa: BLE001 - isolate a failed public source
                        return candidate, error

            tasks = [asyncio.create_task(bounded_enrich(candidate)) for candidate in ordered]
            completed = 0
            for task in asyncio.as_completed(tasks):
                candidate, result = await task
                completed += 1
                persisted: list[Lead] = []
                if isinstance(result, Exception):
                    logger.warning(
                        "candidate_processing_failed",
                        extra={
                            "data": {
                                "stable_creator_id": f"apple-podcast:{candidate.apple_id}",
                                "error_type": type(result).__name__,
                            }
                        },
                    )
                    lead = Lead(
                        creator_name=candidate.artist_name,
                        country_iso2=candidate.country_iso2,
                        stable_creator_id=f"apple-podcast:{candidate.apple_id}",
                        profile_url=candidate.apple_url,
                        source_feed_url=candidate.feed_url,
                        checked_date=config.checked_date,
                        rejection_reason=f"unexpected_error:{type(result).__name__}",
                    )
                    rejected.append(lead)
                    persisted.append(lead)
                elif result.lead.candidate_status in {"Needs review", "Qualified"}:
                    lead = result.lead
                    if lead.candidate_status == "Qualified":
                        qualified_pool.append(lead)
                    else:
                        pending.append(lead)
                    persisted.append(lead)
                else:
                    rejected.append(result.lead)
                    persisted.append(result.lead)
                store.upsert_many(persisted)
                if completed % batch_size and completed != len(ordered):
                    continue
                progress = {
                    "status": "running",
                    "processed": completed,
                    "total": len(ordered),
                    "pending_review": len(pending),
                    "qualified": len(qualified_pool),
                    "rejected": len(rejected),
                    "runtime_minutes": round((time.perf_counter() - started) / 60, 2),
                }
                write_text(output_dir / "progress.json", json.dumps(progress, indent=2))
                unique_pool, _ = _dedupe_leads(qualified_pool)
                logger.info(
                    "enrichment_progress",
                    extra={
                        "data": {
                            "processed": completed,
                            "qualified_unique": len(unique_pool),
                            "pending_review": len(pending),
                            "rejected": len(rejected),
                            "countries": Counter(lead.country_iso2 for lead in unique_pool),
                        }
                    },
                )
                quality_buffer = max(10, min(50, config.target_leads // 10))
                if (
                    _can_select(unique_pool, config)
                    and len(unique_pool) >= config.target_leads + quality_buffer
                ):
                    for pending_task in tasks:
                        pending_task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break
    finally:
        if "parse_executor" in locals():
            parse_executor.shutdown(wait=True, cancel_futures=True)
        store.close()

    unique_pool, duplicates_removed = _dedupe_leads(qualified_pool)
    pending.sort(key=lambda lead: (-lead.lead_score, lead.stable_creator_id))
    rejected.sort(key=lambda lead: lead.stable_creator_id)
    leads = _select_final(unique_pool, config)
    runtime_minutes = round((time.perf_counter() - started) / 60, 2)
    metrics: dict[str, float | int] = {
        "target_leads": config.target_leads,
        "input_size": len(qualified_pool) + len(rejected) + len(pending),
        "qualified_pool": len(unique_pool),
        "produced": len(leads),
        "rejected": len(rejected),
        "duplicates_removed": duplicates_removed,
        "pending_review": len(pending),
        "runtime_minutes": runtime_minutes,
    }
    checks = validate(leads, config, output_dir / "validation_report.json")
    export_all(leads, rejected, output_dir, pending=pending, metrics=metrics)
    if not reviewed_only:
        research_queue = output_dir / "research_queue.json"
        write_text(
            research_queue,
            json.dumps([asdict(lead) for lead in pending], ensure_ascii=False, indent=2),
        )
        review_workbook = output_dir / "Human_Review.xlsx"
        if not review_workbook.exists():
            export_review_workbook(research_queue, review_workbook)
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
    else:
        logger.warning("workbook_template_missing", extra={"data": {"path": str(template)}})
    passed = all(check.passed for check in checks)
    manifest = {
        "submission_ready": False,
        "lead_checks_passed": passed,
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
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_text(
        output_dir / "progress.json",
        json.dumps(
            {
                "status": "completed",
                "processed": metrics["input_size"],
                "total": len(candidates),
                **metrics,
                "lead_checks_passed": passed,
            },
            indent=2,
        ),
    )
    logger.info("run_completed", extra={"data": {**metrics, "validation_passed": passed}})
    return PipelineResult(leads, rejected, metrics, passed)
