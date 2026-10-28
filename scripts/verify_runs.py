"""Measure normal/repeat/new-input executions using only actual cached discovery records.

Small-sample engine verification is not a 1,000-lead or 5,000-lead scale benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

from incubrix_engine.config import Config
from incubrix_engine.inputs import load_candidates
from incubrix_engine.logging_utils import configure_logging
from incubrix_engine.pipeline import run_pipeline


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=Path("output_preflight/discovered_inputs.csv")
    )
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()
    root = Path.cwd()
    candidates = load_candidates(args.input)
    if len(candidates) < args.count + 2:
        raise ValueError("At least count+2 real source records are required")
    directory = root / "verification"
    directory.mkdir(exist_ok=True)
    results = {}
    for label, size, refresh in (
        ("normal", args.count, False),
        ("repeat", args.count, False),
        ("new_input_refresh", args.count + 2, True),
    ):
        input_path = directory / f"{label}_inputs.csv"
        with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(candidates[0])))
            writer.writeheader()
            writer.writerows(asdict(candidate) for candidate in candidates[:size])
        config = replace(
            Config.load(root / "config/preflight.json"),
            output_dir=f"verification/{label}",
            state_dir="verification/state",
            max_candidates=size,
        )
        logger = configure_logging(directory / f"{label}.jsonl", True)
        result = await run_pipeline(root, config, logger, refresh=refresh, input_path=input_path)
        results[label] = {
            "metrics": result.metrics,
            "acceptance_passed": result.all_checks_passed,
            "approved_ids": [lead.stable_creator_id for lead in result.leads],
            "note": "Small real-input execution; not full submission acceptance.",
        }
    results["same_input_same_approved_ids"] = (
        results["normal"]["approved_ids"] == results["repeat"]["approved_ids"]
    )
    (directory / "run_evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    logging.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
