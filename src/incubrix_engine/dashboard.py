from __future__ import annotations

import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path

from .files import write_text
from .models import Lead


def _rejection_row(row: Lead) -> dict:
    """Keep rejected payloads compact while retaining the fields used by the UI."""
    return {
        "creator_name": row.creator_name,
        "country_iso2": row.country_iso2,
        "stable_creator_id": row.stable_creator_id,
        "profile_url": row.profile_url,
        "source_feed_url": row.source_feed_url,
        "primary_platform": row.primary_platform,
        "candidate_status": row.candidate_status,
        "rejection_reason": row.rejection_reason,
        "checked_date": row.checked_date,
        "longform_count_60d": row.longform_count_60d,
        "content_count_30d": row.content_count_30d,
        "metadata": {"collection_name": row.metadata.get("collection_name", "")},
    }


def write_dashboard(
    leads: list[Lead], pending: list[Lead], rejected: list[Lead], summary: dict, path: Path
) -> None:
    """Write a private, dependency-free evidence desk with escaped embedded data."""
    rows = [asdict(row) for row in leads + pending] + [_rejection_row(row) for row in rejected]
    payload = json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False)
    # JSON in a script element must not contain HTML-closing characters from publisher text.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = (
        files("incubrix_engine").joinpath("templates/dashboard.html").read_text(encoding="utf-8")
    )
    write_text(path, template.replace("__PAYLOAD__", payload))
