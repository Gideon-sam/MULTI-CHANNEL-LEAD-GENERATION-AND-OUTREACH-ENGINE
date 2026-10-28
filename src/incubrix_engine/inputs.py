from __future__ import annotations

import csv
from dataclasses import fields
from pathlib import Path
from urllib.parse import urlparse

from .models import PodcastCandidate


def load_candidates(path: Path) -> list[PodcastCandidate]:
    """Import reviewer-supplied new inputs without inventing any platform identifier."""
    required = {field.name for field in fields(PodcastCandidate)} - {"release_date", "country_iso2"}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Candidate input missing columns: {sorted(missing)}")
        rows = []
        allowed = {field.name for field in fields(PodcastCandidate)}
        for line, values in enumerate(reader, start=2):
            if not values.get("apple_id", "").isdigit():
                raise ValueError(f"Line {line}: actual numeric Apple podcast ID required")
            for key in ("feed_url", "apple_url"):
                url = urlparse(values.get(key, ""))
                if url.scheme not in {"http", "https"} or not url.hostname or url.username:
                    raise ValueError(f"Line {line}: invalid {key}")
            row = {key: value for key, value in values.items() if key in allowed}
            row["country_iso2"] = ""  # Input country is never qualification evidence.
            rows.append(PodcastCandidate(**row))
    return rows
