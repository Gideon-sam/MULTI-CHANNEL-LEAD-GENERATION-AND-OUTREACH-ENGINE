"""Merge the base and targeted research runs into one auditable review handoff."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from incubrix_engine.config import Config
from incubrix_engine.dashboard import write_dashboard
from incubrix_engine.exporters import _write_csv
from incubrix_engine.launch_kit import write_launch_kit
from incubrix_engine.models import Lead
from incubrix_engine.outreach import write_outreach
from incubrix_engine.pipeline import _dedupe_leads
from incubrix_engine.review_workflow import export_review_workbook
from incubrix_engine.validation import validate
from incubrix_engine.workbook import build_workbook


def load_leads(path: Path) -> list[Lead]:
    return [Lead(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def minimal_rejection(row: dict[str, str]) -> Lead:
    return Lead(
        creator_name=row.get("creator_name", ""),
        country_iso2=row.get("country_iso2", ""),
        stable_creator_id=row.get("stable_creator_id", ""),
        profile_url=row.get("profile_url", ""),
        source_feed_url=row.get("source_feed_url", ""),
        candidate_status="Rejected",
        rejection_reason=row.get("rejection_reason", ""),
        checked_date=row.get("checked_date", ""),
        longform_count_60d=int(row.get("longform_count_60d") or 0),
        metadata={"collection_name": ""},
    )


def main() -> None:
    root = Path.cwd()
    output = root / "output"
    additional = root / "output_additional"
    expanded_input = root / "inputs/cached_discovery_expanded.csv"
    required = [
        output / "review_queue.json",
        output / "rejections.csv",
        output / "manifest.json",
        additional / "research_queue.json",
        additional / "rejections.csv",
        additional / "manifest.json",
        expanded_input,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Research run artifacts missing: {missing}")
    review_workbook = output / "Human_Review.xlsx"
    if review_workbook.exists():
        raise ValueError("Human_Review.xlsx already exists; preserve edits and merge manually")

    pending, removed = _dedupe_leads(
        load_leads(output / "review_queue.json") + load_leads(additional / "research_queue.json")
    )
    pending.sort(key=lambda lead: (-lead.lead_score, lead.stable_creator_id))
    pending_ids = {lead.stable_creator_id for lead in pending}
    fields, base_rejected = read_csv(output / "rejections.csv")
    other_fields, extra_rejected = read_csv(additional / "rejections.csv")
    if fields != other_fields:
        raise ValueError("Rejection CSV schemas differ")
    rejected_by_id = {
        row["stable_creator_id"]: row
        for row in [*base_rejected, *extra_rejected]
        if row["stable_creator_id"] not in pending_ids
    }
    rejected_rows = [rejected_by_id[key] for key in sorted(rejected_by_id)]

    metrics = {
        "target_leads": 2000,
        "input_size": len(pending) + len(rejected_rows),
        "qualified_pool": 0,
        "produced": 0,
        "rejected": len(rejected_rows),
        "duplicates_removed": removed,
        "pending_review": len(pending),
        "runtime_minutes": round(
            sum(
                json.loads((directory / "manifest.json").read_text())["metrics"]["runtime_minutes"]
                for directory in (output, additional)
            ),
            2,
        ),
    }
    _write_csv(output / "review_queue.csv", [lead.evidence_row() for lead in pending], fields)
    (output / "review_queue.json").write_text(
        json.dumps([asdict(lead) for lead in pending], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output / "research_queue.json").write_text(
        json.dumps([asdict(lead) for lead in pending], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_csv(output / "rejections.csv", rejected_rows, fields)
    shutil.copyfile(expanded_input, output / "discovered_inputs.csv")

    summary = {
        "qualified": 0,
        "pending_review": len(pending),
        "run_metrics": metrics,
        "rejected": len(rejected_rows),
        "countries": {},
        "channels": {},
        "priorities": {},
        "duplicates": 0,
    }
    (output / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    rejected = [minimal_rejection(row) for row in rejected_rows]
    write_dashboard([], pending, rejected, summary, output / "audit_dashboard.html")
    config = Config.load(root / "config/production.json")
    validate([], config, output / "validation_report.json")
    write_outreach([], output)
    write_launch_kit([], output / "launch-kit.md")
    build_workbook(
        root / config.workbook_template,
        output / "IncuBrix_Submission_Workbook_Draft.xlsx",
        [],
        config,
        metrics,
    )
    export_review_workbook(output / "research_queue.json", review_workbook)

    manifests = [
        json.loads((directory / "manifest.json").read_text()) for directory in (output, additional)
    ]
    http = Counter()
    for manifest in manifests:
        http.update(manifest.get("http", {}))
    manifest = {
        "submission_ready": False,
        "lead_checks_passed": False,
        "metrics": metrics,
        "http": dict(http),
        "config": asdict(config),
        "discovery": {
            "base_input": 10153,
            "targeted_new_input": 3480,
            "combined_unique_input": metrics["input_size"],
        },
        "files": {
            str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in output.rglob("*")
            if path.is_file() and path.name not in {"manifest.json", "progress.json"}
        },
        "pending_external": [
            "creator_specific_evidence_review",
            "authenticated_product_test",
            "three_channel_seed_test",
            "unedited_videos",
            "candidate_declaration",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "progress.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "processed": metrics["input_size"],
                "total": metrics["input_size"],
                **metrics,
                "lead_checks_passed": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(metrics)


if __name__ == "__main__":
    main()
