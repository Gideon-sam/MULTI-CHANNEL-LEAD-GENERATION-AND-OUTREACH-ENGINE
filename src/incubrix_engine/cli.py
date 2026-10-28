from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import socketserver
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import Config
from .logging_utils import configure_logging
from .pipeline import run_pipeline
from .review_workflow import export_review_workbook, import_review_workbook
from .seed import SeedStore, serve_tracking, write_seed_plan
from .youtube_pipeline import run_youtube_pipeline


def _root() -> Path:
    return Path.cwd().resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incubrix-engine",
        description="Auditable creator lead qualification and outreach engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="discover, verify, score, export and refresh leads")
    run.add_argument("--config", default="config/production.json")
    run.add_argument(
        "--refresh", action="store_true", help="re-fetch live sources instead of current cache"
    )
    run.add_argument("--verbose", action="store_true")
    run.add_argument("--input", type=Path, help="new candidate input CSV; bypass API discovery")
    run.add_argument(
        "--source",
        choices=("apple", "youtube"),
        default="apple",
        help="discovery/enrichment source (YouTube requires YOUTUBE_API_KEY)",
    )
    run.add_argument(
        "--reviewed-only", action="store_true", help="recheck only IDs with review decisions"
    )
    review = sub.add_parser("review", help="export or import the editable evidence review workbook")
    review.add_argument("action", choices=["export", "import"])
    review.add_argument("--workbook", type=Path, default=Path("output/Human_Review.xlsx"))
    review.add_argument("--queue", type=Path, default=Path("output/research_queue.json"))
    review.add_argument("--reviews", type=Path, default=Path("config/reviews.json"))
    serve = sub.add_parser("serve", help="serve the local evidence dashboard")
    serve.add_argument("--port", type=int, default=8080)
    seed = sub.add_parser(
        "seed", help="owned-account scheduling, tracking and evidence ledger; never sends"
    )
    seed.add_argument("action", choices=["plan", "due", "record", "report", "serve"])
    seed.add_argument("--db", type=Path, default=Path("state/seed.sqlite3"))
    seed.add_argument("--accounts", type=Path, default=Path("config/seed_accounts.local.json"))
    seed.add_argument("--base-url", default="http://127.0.0.1:8081")
    seed.add_argument("--start", help="ISO 8601 time including UTC offset")
    seed.add_argument("--campaign", default="incubrix_option1_seed")
    seed.add_argument("--message-id")
    seed.add_argument("--event")
    seed.add_argument("--evidence")
    seed.add_argument("--port", type=int, default=8081)
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = _root()
    if args.command == "review":
        try:
            result = (
                export_review_workbook(args.queue, args.workbook)
                if args.action == "export"
                else import_review_workbook(args.workbook, args.reviews, args.queue)
            )
        except (ValueError, TypeError, OSError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, indent=2))
        return
    if args.command == "seed":
        if args.action == "serve":
            serve_tracking(args.db, args.port)
            return
        store = SeedStore(args.db)
        try:
            if args.action == "plan":
                if not args.start:
                    raise ValueError("--start with timezone is required")
                rows = store.plan(
                    args.accounts, args.base_url, datetime.fromisoformat(args.start), args.campaign
                )
                write_seed_plan(rows, root / "seed_private/plan.csv")
                print("Owned-account schedule saved to seed_private/plan.csv; no messages sent")
            elif args.action == "due":
                print(json.dumps(store.due(datetime.now(UTC)), indent=2))
            elif args.action == "record":
                if not all((args.message_id, args.event, args.evidence)):
                    raise ValueError("--message-id, --event and --evidence are required")
                store.record(args.message_id, args.event, args.evidence)
            else:
                print(json.dumps(store.report(), indent=2))
        finally:
            store.close()
        return
    if args.command == "serve":
        directory = root / "output"
        handler = lambda *items, **kwargs: http.server.SimpleHTTPRequestHandler(
            *items, directory=str(directory), **kwargs
        )
        with socketserver.TCPServer(("127.0.0.1", args.port), handler) as server:
            print(f"Audit dashboard: http://127.0.0.1:{args.port}/audit_dashboard.html")
            server.serve_forever()
        return

    config = Config.load(root / args.config)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    logger = configure_logging(root / config.log_dir / f"run-{timestamp}.jsonl", args.verbose)
    try:
        if args.source == "youtube":
            if args.input or args.reviewed_only:
                raise ValueError("--input and --reviewed-only are Apple workflow options")
            result = asyncio.run(run_youtube_pipeline(root, config, logger, refresh=args.refresh))
        else:
            result = asyncio.run(
                run_pipeline(
                    root,
                    config,
                    logger,
                    refresh=args.refresh,
                    input_path=args.input,
                    reviewed_only=args.reviewed_only,
                )
            )
    except (TypeError, ValueError, OSError) as error:
        logger.error("run_failed", extra={"data": {"error": str(error)}})
        print(f"Run could not complete: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        logger.warning("run_interrupted")
        raise SystemExit(130) from None
    print(json.dumps(result.metrics, indent=2))
    if not result.all_checks_passed:
        print(
            f"Submission gates did not pass; inspect {config.output_dir}/validation_report.json",
            file=sys.stderr,
        )
        raise SystemExit(2)
