"""Assemble existing source exports and evidence tools; never loosens qualification gates."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .audit_support import create_sample, metadata, read_rows, rejection_report, score_sample
from .config import Config
from .delivery_support import safe_drafts, write_launch_supplement, write_outreach_support
from .exporters import _write_csv, export_all
from .files import write_text
from .launch_kit import write_launch_kit
from .logging_utils import configure_logging
from .models import Lead
from .operations import run_demo
from .outreach import write_outreach
from .pipeline import _dedupe_leads, _select_final, run_pipeline
from .validation import validate
from .workbook import build_workbook
from .workbook_support import read_optional_json, supplement_workbook
from .youtube_pipeline import run_youtube_pipeline


def lead_from_row(row: dict) -> Lead:
    values = {field.name: row[field.name] for field in fields(Lead) if field.name in row}
    values["metadata"] = metadata(row)
    for key in ("content_count_30d", "longform_count_60d"):
        values[key] = int(values.get(key) or 0)
    values["lead_score"] = float(values.get("lead_score") or 0)
    return Lead(**values)


def artifact_hashes(directory: Path) -> dict:
    return {
        str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "progress.json"}
    }


def support(root: Path, directory: Path, source_metrics: list[dict] | None = None) -> dict:
    rows = read_rows(directory / "leads.csv")
    report = rejection_report(
        rows, read_rows(directory / "rejections.csv"), read_rows(directory / "review_queue.csv")
    )
    write_text(directory / "rejection_report.json", json.dumps(report, indent=2))
    _write_csv(
        directory / "rejection_counts.csv",
        report["grouped"],
        ["reason", "source", "country", "count"],
    )
    outreach = write_outreach_support(directory)
    write_launch_supplement(directory)
    fingerprint = hashlib.sha256((directory / "leads.csv").read_bytes()).hexdigest()[:12]
    sample = directory / f"audit_sample_{fingerprint}.csv"
    if not sample.exists():
        create_sample(directory / "leads.csv", directory / "evidence_ledger.csv", sample)
    scores = score_sample(sample)
    write_text(directory / "audit_results.json", json.dumps(scores, indent=2))
    demo = read_optional_json(root / "verification/current/run_evidence.json")
    clone = read_optional_json(root / "verification/clean_clone_report.json")
    evidence = {
        "lead_count": len(rows),
        "audit_sample": sample.name,
        "clean_clone_passed": clone.get("passed") is True,
        "refresh_demo_passed": demo.get("refresh_contains_new_ids") is True
        and demo.get("new_input_refresh", {}).get("duplicate_state_rows") == 0,
        "failure_demo_passed": demo.get("failure_recovery", {}).get("continued_after_failure")
        is True,
        "demo": demo,
        "root_prefix": os.path.relpath(root, directory).replace("\\", "/"),
    }
    draft = directory / "IncuBrix_Submission_Workbook_Draft.xlsx"
    if draft.exists():
        supplement_workbook(draft, directory / "IncuBrix_Submission_Workbook_Review.xlsx", evidence)
    gaps = []
    for row in read_rows(directory / "evidence_ledger.csv"):
        meta = metadata(row)
        proofs = meta.get("review", {}).get("proofs", {})
        missing = [
            kind
            for kind in (
                "identity",
                "country",
                "language",
                "commercial",
                "need",
                "contact",
                "contact_activity",
                "backup",
            )
            if not proofs.get(kind, {}).get("quote")
        ]
        gaps.append(
            {
                "lead_id": row["lead_id"],
                "creator_name": row["creator_name"],
                "engine_status": row["candidate_status"],
                "public_profile": row["profile_url"],
                "recent_content": row["recent_content_url"],
                "contact": row["channel_handle_or_url"],
                "missing_review_proofs": ";".join(missing),
                "my_verdict": "",
                "my_evidence": "",
            }
        )
    _write_csv(
        directory / "evidence_gaps.csv",
        gaps,
        [
            "lead_id",
            "creator_name",
            "engine_status",
            "public_profile",
            "recent_content",
            "contact",
            "missing_review_proofs",
            "my_verdict",
            "my_evidence",
        ],
    )
    if source_metrics is not None:
        write_text(
            directory / "runtime_cost_report.json",
            json.dumps(
                {
                    "source_runs": source_metrics,
                    "actual_billed_cost": None,
                    "cost_per_qualified_lead": None,
                    "provider_quota_usage": None,
                    "note": "Runtime/request counts are copied from measured source run artifacts. Old estimated quota-unit fields are excluded. Billing and provider quota usage require external account evidence. No 5,000-verified-lead refresh claim.",
                },
                indent=2,
            ),
        )
    status = {
        "output_directory": str(directory.relative_to(root)).replace("\\", "/"),
        "generated_at": datetime.now(UTC).isoformat(),
        "engine_qualified_rows": len(rows),
        "pending_rows": report["pending_rows"],
        "rejected_rows": report["rejected_rows"],
        "priority_a_rows": outreach["priority_a_count"],
        "audit_sample": sample.name,
        "audit_sample_rows": scores["sample_size"],
        "human_audit_pass_rate": scores["qualification_pass_rate"],
        "rows_missing_creator_specific_review_proofs": sum(
            bool(row["missing_review_proofs"]) for row in gaps
        ),
        "country_mix": report["country_mix"],
        "submission_ready": False,
        "qualification_note": "Existing source-specific qualification rules were preserved. Engine-qualified is not a guarantee of PDF acceptance; inspect evidence_gaps.csv and complete the independent audit.",
        "candidate_todos": [
            "Five observations and three opportunities from actual IncuBrix product use",
            "Review the random sample and resolve every missing business-contact/activity/source proof",
            "Perform and document three owned-account seed tests",
            "Record two unedited videos",
            "Confirm identity, declaration and private reviewer access",
        ],
        "smoke_outputs": "Historical output_youtube_smoke is not the current production result.",
    }
    write_text(directory / "submission_status.json", json.dumps(status, indent=2))
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest = read_optional_json(manifest_path)
        manifest["files"] = artifact_hashes(directory)
        manifest["submission_ready"] = False
        write_text(manifest_path, json.dumps(manifest, indent=2))
    return status


def assemble(root: Path, source_dirs: list[Path]) -> dict:
    started = time.perf_counter()
    config = replace(Config.load(root / "config/production.json"), sender_name="[YOUR NAME]")
    directory = root / config.output_dir / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    records: dict[str, Lead] = {}
    discoveries: dict[str, dict] = {}
    measured = []
    for source in source_dirs:
        if not (source / "manifest.json").exists():
            raise ValueError(f"Source run is missing a manifest: {source}")
        manifest = read_optional_json(source / "manifest.json")
        metric = dict(manifest.get("metrics", {}))
        metric.pop("youtube_estimated_quota_units", None)
        measured.append(
            {
                "source_directory": str(source.relative_to(root)),
                "metrics": metric,
                "http": manifest.get("http", {}),
                "api": read_optional_json(source / "api_call_report.json"),
            }
        )
        for name in ("evidence_ledger.csv", "rejections.csv", "review_queue.csv"):
            for row in read_rows(source / name):
                lead = lead_from_row(row)
                if lead.stable_creator_id:
                    records[lead.stable_creator_id] = lead
        for row in read_rows(source / "discovered_inputs.csv"):
            channel_id = row.get("channel_id", "")
            apple_id = row.get("apple_id", "")
            stable = (
                f"youtube-channel:{channel_id}"
                if channel_id
                else f"apple-podcast:{apple_id}"
                if apple_id
                else row.get("stable_creator_id", "")
            )
            if stable:
                discoveries[stable] = {
                    **row,
                    "stable_creator_id": stable,
                    "source_platform": "YouTube" if channel_id else "Apple Podcasts",
                    "source_run": str(source.relative_to(root)),
                    "data_status": "Discovery only; not qualification evidence",
                }
    directory.mkdir(parents=True, exist_ok=True)
    pool, removed = _dedupe_leads(
        [lead for lead in records.values() if lead.candidate_status == "Qualified"]
    )
    leads = _select_final(pool, config)
    rejected = [lead for lead in records.values() if lead.candidate_status == "Rejected"]
    pending = [lead for lead in records.values() if lead.candidate_status == "Needs review"]
    for lead in leads:
        drafts = safe_drafts(asdict(lead))
        if drafts["first_message"]:
            for field, value in drafts.items():
                setattr(lead, field, value)
    metrics = {
        "target_leads": config.target_leads,
        "input_size": len(records),
        "qualified_pool": len(pool),
        "produced": len(leads),
        "rejected": len(rejected),
        "pending_review": len(pending),
        "duplicates_removed": removed,
        "assembly_runtime_minutes": round((time.perf_counter() - started) / 60, 3),
    }
    checks = validate(leads, config, directory / "validation_report.json")
    export_all(leads, rejected, directory, pending=pending, metrics=metrics)
    all_discovered = sorted(discoveries.values(), key=lambda row: row["stable_creator_id"])
    discovery_fields = list(
        dict.fromkeys(
            [
                "stable_creator_id",
                "source_platform",
                "source_run",
                "data_status",
                *(key for row in all_discovered for key in row),
            ]
        )
    )
    _write_csv(directory / "all_discovered_inputs.csv", all_discovered, discovery_fields)
    write_text(
        directory / "research_queue.json",
        json.dumps([asdict(lead) for lead in pending], ensure_ascii=False, indent=2),
    )
    write_outreach(leads, directory)
    write_launch_kit(leads, directory / "launch-kit.md")
    build_workbook(
        root / config.workbook_template,
        directory / "IncuBrix_Submission_Workbook_Draft.xlsx",
        leads,
        config,
        metrics,
    )
    manifest = {
        "submission_ready": False,
        "lead_checks_passed": all(check.passed for check in checks),
        "metrics": metrics,
        "source_runs": measured,
        "config": asdict(config),
        "files": {},
        "note": "Assembly of existing measured source runs; source fetch dates preserved. Refer to source_runs for runtimes, not assembly time.",
    }
    write_text(directory / "manifest.json", json.dumps(manifest, indent=2))
    write_text(
        directory / "progress.json",
        json.dumps(
            {
                "status": "completed",
                **metrics,
                "lead_checks_passed": manifest["lead_checks_passed"],
            },
            indent=2,
        ),
    )
    result = support(root, directory, measured)
    write_text(
        root / "output/CURRENT_RUN.json",
        json.dumps(
            {
                "output_directory": result["output_directory"],
                "status_file": result["output_directory"] + "/submission_status.json",
            },
            indent=2,
        ),
    )
    relative_dashboard = (
        str(directory.relative_to(root / "output")).replace("\\", "/") + "/audit_dashboard.html"
    )
    write_text(
        root / "output/current.html",
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={relative_dashboard}"><a href="{relative_dashboard}">Open the latest complete production review</a>',
    )
    return result


async def production(root: Path, sources: str) -> dict:
    config = replace(Config.load(root / "config/production.json"), sender_name="[YOUR NAME]")
    wanted = ["apple", "youtube"] if sources == "both" else [sources]
    if sources == "auto":
        wanted = ["apple", "youtube"] if os.environ.get("YOUTUBE_API_KEY") else ["apple"]
    source_dirs = []
    failures = []
    for source in wanted:
        run_config = replace(
            config, output_dir=f"output_sources/{source}", state_dir=f"state_sources/{source}"
        )
        logger = configure_logging(
            root / f"logs/production-{source}-{datetime.now(UTC):%Y%m%dT%H%M%S}.jsonl"
        )
        try:
            if source == "youtube":
                await run_youtube_pipeline(root, run_config, logger)
            else:
                await run_pipeline(
                    root,
                    run_config,
                    logger,
                    input_path=root / "inputs/cached_discovery_expanded.csv",
                )
            source_dirs.append(root / run_config.output_dir)
        except (RuntimeError, OSError, ValueError, TypeError, httpx.HTTPError) as error:
            logger.error(
                "source_run_failed",
                extra={"data": {"source": source, "error_type": type(error).__name__}},
            )
            failures.append({"source": source, "error_type": type(error).__name__})
    if not source_dirs:
        raise RuntimeError(
            "No source run completed; inspect logs. Existing final exports were preserved."
        )
    result = assemble(root, source_dirs)
    write_text(
        root / "output/source_run_failures.json",
        json.dumps(
            {
                "failures": failures,
                "requested_sources": wanted,
                "youtube_skipped_missing_key": sources == "auto" and "youtube" not in wanted,
            },
            indent=2,
        ),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("production", "assemble", "support", "smoke"))
    parser.add_argument("--sources", choices=("auto", "both", "apple", "youtube"), default="auto")
    parser.add_argument("--source-dir", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.mode == "production":
        result = asyncio.run(production(root, args.sources))
    elif args.mode == "assemble":
        result = assemble(
            root,
            [
                (root / source).resolve()
                for source in (args.source_dir or [Path("output"), Path("output_youtube_verified")])
            ],
        )
    elif args.mode == "support":
        result = support(root, root / args.output)
    else:
        result = asyncio.run(run_demo(root))
        healthy = (
            result.get("repeat_keeps_stable_state_ids")
            and result.get("refresh_contains_new_ids")
            and result["failure_recovery"].get("continued_after_failure")
            and all(
                result[name]["duplicate_state_rows"] == 0
                for name in ("normal", "repeat", "new_input_refresh", "failure_recovery")
            )
        )
        if not healthy:
            raise RuntimeError(
                "Smoke execution checks failed; inspect verification/current/run_evidence.json"
            )
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
