"""Run only the README's documented smoke command in a new local Git clone."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    root = Path.cwd().resolve()
    workspace = Path(tempfile.mkdtemp(prefix="incubrix-clean-clone-"))
    clone = workspace / "project"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    subprocess.run(["git", "clone", "--no-local", str(root), str(clone)], check=True)
    log = root / "verification/clean_clone.log"
    log.parent.mkdir(exist_ok=True)
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(clone / "Run-Submission.ps1"),
        "-Mode",
        "smoke",
    ]
    environment = dict(os.environ)
    environment.pop("YOUTUBE_API_KEY", None)
    started = time.perf_counter()
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            cwd=clone,
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    evidence_path = clone / "verification/current/run_evidence.json"
    evidence = (
        json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
    )
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "clone_directory": str(clone),
        "command": "powershell -NoProfile -ExecutionPolicy Bypass -File .\\Run-Submission.ps1 -Mode smoke",
        "exit_code": result.returncode,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "passed": result.returncode == 0
        and evidence.get("refresh_contains_new_ids") is True
        and evidence.get("failure_recovery", {}).get("continued_after_failure") is True,
        "run_evidence": evidence,
        "log": "verification/clean_clone.log",
        "scope": "Clean installation, full test suite and small real-input smoke execution; not full production-scale acceptance.",
    }
    (root / "verification/clean_clone_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps({key: value for key, value in report.items() if key != "run_evidence"}, indent=2)
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
