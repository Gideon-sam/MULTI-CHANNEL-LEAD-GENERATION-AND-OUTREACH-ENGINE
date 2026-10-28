"""Losslessly convert legacy HTTP cache bodies to gzip after active runs have stopped."""

from __future__ import annotations

import argparse
import gzip
import hashlib
from pathlib import Path

from incubrix_engine.files import atomic_destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path(".cache/http"))
    parser.add_argument("--apply", action="store_true", help="perform the verified conversion")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    cache = args.cache.resolve()
    if not cache.is_relative_to(root) or cache == root:
        raise ValueError("Cache must be a project subdirectory")
    legacy = sorted(cache.glob("*.body"))
    before = sum(path.stat().st_size for path in legacy)
    if not args.apply:
        print({"legacy_files": len(legacy), "legacy_bytes": before, "apply": False})
        return
    converted = 0
    saved = 0
    for source in legacy:
        destination = source.with_suffix(".body.gz")
        original = source.read_bytes()
        digest = hashlib.sha256(original).digest()
        if destination.exists():
            compressed = destination.read_bytes()
        else:
            compressed = gzip.compress(original, compresslevel=6)
            with atomic_destination(destination) as temporary:
                temporary.write_bytes(compressed)
        restored = gzip.decompress(compressed)
        if hashlib.sha256(restored).digest() != digest:
            raise OSError(f"Verification failed; legacy source retained: {source}")
        source.unlink()
        converted += 1
        saved += len(original) - len(compressed)
    print({"converted": converted, "bytes_saved": saved, "apply": True})


if __name__ == "__main__":
    main()
