"""Qualify only the targeted discovery increment and keep its artifacts isolated for merging."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from incubrix_engine.config import Config
from incubrix_engine.logging_utils import configure_logging
from incubrix_engine.pipeline import run_pipeline


async def main() -> None:
    root = Path.cwd()
    config = replace(
        Config.load(root / "config/production.json"),
        max_candidates=12000,
        output_dir="output_additional",
        state_dir="state_additional",
    )
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    logger = configure_logging(root / config.log_dir / f"additional-{timestamp}.jsonl", True)
    result = await run_pipeline(
        root,
        config,
        logger,
        input_path=root / "inputs/additional_discovery.csv",
    )
    print(result.metrics)


if __name__ == "__main__":
    asyncio.run(main())
