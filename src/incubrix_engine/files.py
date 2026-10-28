from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_destination(path: Path):
    """Publish a single complete artifact; a failed writer leaves the previous file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".writing-", suffix=path.suffix, dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_text(path: Path, content: str) -> None:
    with atomic_destination(path) as temporary:
        temporary.write_text(content, encoding="utf-8")
