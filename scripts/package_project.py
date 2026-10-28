"""Build a private-review ZIP from an explicit allowlist; exclude caches and account files."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    root = Path.cwd().resolve()
    destination = root / "dist"
    destination.mkdir(exist_ok=True)
    archive_path = destination / f"IncuBrix_Project_Draft_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.zip"
    top_files = [
        "README.md",
        "START_HERE.md",
        "Run-Project.ps1",
        "Run-Submission.ps1",
        "pyproject.toml",
        "requirements.lock",
        "Dockerfile",
        ".dockerignore",
        ".gitignore",
        ".env.example",
    ]
    folders = [
        "src/incubrix_engine",
        "tests",
        "scripts",
        "docs",
        "config",
        "assets",
        ".github",
        "inputs",
        "verification",
    ]
    paths = [root / name for name in top_files]
    for name in folders:
        paths.extend((root / name).rglob("*"))
    current_pointer = root / "output/CURRENT_RUN.json"
    paths.extend((current_pointer, root / "output/current.html"))
    if current_pointer.exists():
        pointer = json.loads(current_pointer.read_text(encoding="utf-8"))
        current_run = (root / str(pointer.get("output_directory", ""))).resolve()
        if not current_run.is_relative_to((root / "output/runs").resolve()):
            raise ValueError("CURRENT_RUN output directory must be inside output/runs")
        paths.extend(current_run.rglob("*"))
    manifest = {}
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root)
            if (
                path.name.endswith(".local.json")
                or path.name.endswith(".json.bak")
                or path.suffix in {".sqlite3", ".db", ".pyc"}
                or "state" in relative.parts
            ):
                continue
            data = path.read_bytes()
            manifest[str(relative).replace("\\", "/")] = hashlib.sha256(data).hexdigest()
            archive.writestr(str(relative).replace("\\", "/"), data)
        archive.writestr(
            "PACKAGE_MANIFEST.json",
            json.dumps({"submission_ready": False, "files": manifest}, indent=2),
        )
    print(
        json.dumps(
            {
                "archive": str(archive_path),
                "files": len(manifest),
                "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                "submission_ready": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
