from __future__ import annotations

import csv
import html
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .dashboard import write_dashboard
from .files import atomic_destination
from .models import LEAD_COLUMNS, Lead


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        atomic_destination(path) as temporary,
        temporary.open("w", encoding="utf-8-sig", newline="") as handle,
    ):
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: _csv_safe(value) for key, value in row.items()} for row in rows)


def _csv_safe(value: object) -> object:
    # Treat publisher text as data when Excel opens a CSV, including whitespace-prefixed formulas.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_all(
    leads: list[Lead],
    rejected: list[Lead],
    output_dir: Path,
    *,
    pending: list[Lead] | None = None,
    metrics: dict | None = None,
) -> None:
    pending = pending or []
    _write_csv(output_dir / "leads.csv", [lead.workbook_row() for lead in leads], LEAD_COLUMNS)
    # Use the complete evidence schema even when no lead qualified. This keeps the
    # pending/rejection provenance column available in zero-lead runs.
    evidence_fields = list(leads[0].evidence_row()) if leads else list(Lead().evidence_row())
    _write_csv(
        output_dir / "evidence_ledger.csv",
        [lead.evidence_row() for lead in leads],
        evidence_fields,
    )
    _write_csv(
        output_dir / "rejections.csv",
        [lead.evidence_row() for lead in rejected],
        evidence_fields,
    )
    _write_csv(
        output_dir / "review_queue.csv", [lead.evidence_row() for lead in pending], evidence_fields
    )
    (output_dir / "review_queue.json").write_text(
        json.dumps([asdict(lead) for lead in pending], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = {
        "qualified": len(leads),
        "pending_review": len(pending),
        "run_metrics": metrics or {},
        "rejected": len(rejected),
        "countries": Counter(lead.country_iso2 for lead in leads),
        "channels": Counter(lead.best_channel for lead in leads),
        "priorities": Counter(lead.priority for lead in leads),
        "duplicates": len(leads) - len({lead.stable_creator_id for lead in leads}),
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=dict), encoding="utf-8"
    )
    write_dashboard(leads, pending, rejected, summary, output_dir / "audit_dashboard.html")


def _write_dashboard(leads: list[Lead], summary: dict, path: Path) -> None:
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(lead.lead_id)}</td>"
        f"<td>{html.escape(lead.creator_name)}</td>"
        f"<td>{html.escape(lead.country_iso2)}</td>"
        f"<td>{html.escape(lead.priority)}</td>"
        f"<td>{lead.lead_score:.1f}</td>"
        f"<td><a href='{html.escape(lead.profile_url)}' rel='noopener'>profile</a></td>"
        f"<td><a href='{html.escape(lead.recent_content_url)}' rel='noopener'>content</a></td>"
        f"<td><a href='{html.escape(lead.channel_evidence_url)}' rel='noopener'>contact proof</a></td>"
        "</tr>"
        for lead in leads
    )
    payload = html.escape(json.dumps(summary, default=dict))
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IncuBrix Lead Audit Dashboard</title>
<style>
body{{font:15px system-ui;margin:0;background:#f6f7fb;color:#172033}}main{{max-width:1400px;margin:auto;padding:24px}}
.cards{{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px}}.card{{background:white;padding:18px;border-radius:12px;box-shadow:0 2px 12px #16213a12}}
input{{width:100%;box-sizing:border-box;padding:12px;margin:18px 0;border:1px solid #ccd3df;border-radius:8px}}
table{{border-collapse:collapse;width:100%;background:white}}th,td{{padding:10px;border-bottom:1px solid #e8ebf1;text-align:left}}th{{position:sticky;top:0;background:#172033;color:white}}a{{color:#315bd6}}
@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}table{{font-size:12px}}}}
</style></head><body><main><h1>IncuBrix Lead Audit Dashboard</h1>
<p>Generated from the official leads.csv. Open each evidence link during review; no outreach was sent.</p>
<div class="cards"><div class="card"><b>Qualified</b><div>{summary["qualified"]}</div></div><div class="card"><b>Rejected</b><div>{summary["rejected"]}</div></div><div class="card"><b>Duplicates</b><div>{summary["duplicates"]}</div></div><div class="card"><b>Countries</b><div>{len(summary["countries"])}</div></div></div>
<input id="q" aria-label="Filter leads" placeholder="Filter by ID, creator, country or priority">
<table><thead><tr><th>ID</th><th>Creator</th><th>Country</th><th>Priority</th><th>Score</th><th>Profile</th><th>Recent content</th><th>Contact evidence</th></tr></thead><tbody id="rows">{rows}</tbody></table>
<script>const q=document.querySelector('#q');q.addEventListener('input',()=>{{const v=q.value.toLowerCase();document.querySelectorAll('#rows tr').forEach(r=>r.hidden=!r.innerText.toLowerCase().includes(v))}});</script>
<details><summary>Machine summary</summary><pre>{payload}</pre></details></main></body></html>"""
    path.write_text(document, encoding="utf-8")
