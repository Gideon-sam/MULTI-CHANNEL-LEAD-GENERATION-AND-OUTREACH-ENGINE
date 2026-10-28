"""Read-only audit support for existing exports. Never approves or changes a lead."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from .exporters import _write_csv
from .files import write_text

AUDIT_SEED = 2027
PDF_CHECKS = (
    "identity",
    "country",
    "language",
    "activity",
    "commercial",
    "need",
    "contact",
    "contact_activity",
    "backup",
    "personalized",
    "complete_unique",
    "freshness",
    "working_sources",
)
VERDICTS = tuple(f"my_verdict_{kind}" for kind in PDF_CHECKS)
ACCURACY = ("my_channel_correct", "my_contact_correct")
APPROVED_MARKETS = frozenset({"US", "CA", "GB", "IE", "AU", "NZ", "SG"})


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def metadata(row: dict) -> dict:
    value = row.get("metadata", {})
    if isinstance(value, dict):
        return value
    # The ledger writes JSON. Never evaluate a Python-looking string from an external CSV.
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def evidence_chain(row: dict) -> list[dict]:
    meta = metadata(row)
    proofs = meta.get("review", {}).get("proofs", {})
    snapshots = meta.get("evidence_snapshots", {})
    automated = meta.get("automated_evidence", {})
    fields = {
        "identity": "profile_url",
        "country": "country_evidence_url",
        "language": "profile_url",
        "activity": "recent_content_url",
        "commercial": "monetization_evidence_url",
        "need": "need_evidence_url",
        "contact": "channel_evidence_url",
        "contact_activity": "channel_evidence_url",
        "backup": "backup_channel",
    }
    result = []
    for kind, field in fields.items():
        proof = proofs.get(kind, {})
        url = proof.get("url") or row.get(field) or meta.get(field) or ""
        if kind == "backup" and not proof:
            url = automated.get("backup_contact", "")
        snippet = proof.get("quote", "")
        provenance = "review_ledger_excerpt" if snippet else "missing"
        if not snippet and kind in {"identity", "commercial", "contact"}:
            key = {
                "identity": "identity",
                "commercial": "commercial_excerpt",
                "contact": "contact_excerpt",
            }[kind]
            snippet = automated.get(key, "")
            if snippet:
                provenance = "automated_recorded_excerpt_requires_manual_verification"
        snapshot = snapshots.get(url, {})
        result.append(
            {
                "check": kind,
                "url": url,
                "verbatim_snippet": snippet,
                "fetch_date": snapshot.get("retrieved_at", ""),
                "snippet_provenance": provenance,
                "fetch_provenance": snapshot.get(
                    "source", "ledger_snapshot" if snapshot else "missing"
                ),
                "sha256": snapshot.get("sha256", ""),
            }
        )
    for item in meta.get("activity_items", []):
        url = item.get("url", "")
        snapshot = snapshots.get(url, {})
        result.append(
            {
                "check": "activity",
                "url": url,
                "verbatim_snippet": item.get("title", ""),
                "fetch_date": snapshot.get("retrieved_at", ""),
                "snippet_provenance": "recorded_content_title",
                "fetch_provenance": snapshot.get(
                    "source", "ledger_snapshot" if snapshot else "missing"
                ),
                "published_date": item.get("date", ""),
                "duration_minutes": item.get("duration_minutes"),
            }
        )
    return result


def create_sample(
    leads_path: Path, ledger_path: Path, destination: Path, size: int = 40, seed: int = AUDIT_SEED
) -> dict:
    if size < 1:
        raise ValueError("Sample size must be positive")
    if destination.exists():
        raise FileExistsError("Audit sample exists; preserve your verdicts or choose a new --out")
    rows = sorted(read_rows(leads_path), key=lambda r: (r["lead_id"], r["stable_creator_id"]))
    ids = [row["lead_id"] for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Official leads have missing/duplicate lead_id values")
    selected = random.Random(seed).sample(rows, min(size, len(rows)))
    ledger = {row["lead_id"]: row for row in read_rows(ledger_path)}
    base = list(rows[0]) if rows else ["lead_id", "stable_creator_id", "creator_name"]
    evidence_columns = [
        f"{kind}_{field}"
        for kind in PDF_CHECKS
        for field in ("evidence_urls", "snippets", "fetch_dates")
    ]
    output = []
    for row in selected:
        chain = evidence_chain(ledger.get(row["lead_id"], row))
        audit = dict(row)
        for kind in PDF_CHECKS:
            entries = [entry for entry in chain if entry["check"] == kind]
            for column, key in (
                ("evidence_urls", "url"),
                ("snippets", "verbatim_snippet"),
                ("fetch_dates", "fetch_date"),
            ):
                audit[f"{kind}_{column}"] = "\n".join(
                    dict.fromkeys(entry[key] for entry in entries if entry[key])
                )
        audit["evidence_chain_json"] = json.dumps(chain, ensure_ascii=False)
        audit.update(dict.fromkeys((*VERDICTS, *ACCURACY, "my_notes"), ""))
        output.append(audit)
    fields = list(
        dict.fromkeys(
            [*base, *evidence_columns, "evidence_chain_json", *VERDICTS, *ACCURACY, "my_notes"]
        )
    )
    _write_csv(destination, output, fields)
    manifest = {
        "seed": seed,
        "requested_size": size,
        "population_size": len(rows),
        "sample_size": len(selected),
        "sample_complete": len(selected) == size,
        "source_sha256": hashlib.sha256(leads_path.read_bytes()).hexdigest(),
        "selected_lead_ids": [row["lead_id"] for row in selected],
        "verdict_values": ["pass", "fail", "blank (unreviewed)"],
        "note": "Random audit of official export only. Empty fields are missing evidence, not a pass. Automated snippets/fetch times require manual provenance checks.",
    }
    write_text(destination.with_suffix(".manifest.json"), json.dumps(manifest, indent=2))
    return manifest


def score_sample(path: Path) -> dict:
    rows = read_rows(path)
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    ids = [row.get("lead_id", "") for row in rows]
    if len(ids) != len(set(ids)) or sorted(ids) != sorted(manifest["selected_lead_ids"]):
        raise ValueError("Audit roster changed; do not replace, duplicate, or remove sampled leads")
    for row in rows:
        for field in (*VERDICTS, *ACCURACY):
            if str(row.get(field, "")).strip().lower() not in {"", "pass", "fail"}:
                raise ValueError(f"{row['lead_id']}: {field} must be pass, fail, or blank")

    def passed(row: dict, fields: tuple[str, ...]) -> bool:
        return all(row.get(field, "").strip().lower() == "pass" for field in fields)

    def complete(row: dict, fields: tuple[str, ...]) -> bool:
        return all(row.get(field, "").strip().lower() in {"pass", "fail"} for field in fields)

    n = len(rows)
    reviewed = sum(complete(row, VERDICTS) for row in rows)
    accuracy_reviewed = sum(complete(row, ACCURACY) for row in rows)
    rate = sum(passed(row, VERDICTS) for row in rows) / n if n and reviewed == n else None
    channel = (
        sum(passed(row, ACCURACY[:1]) for row in rows) / n
        if n and all(complete(row, ACCURACY[:1]) for row in rows)
        else None
    )
    contact = (
        sum(passed(row, ACCURACY[1:]) for row in rows) / n
        if n and all(complete(row, ACCURACY[1:]) for row in rows)
        else None
    )
    joint = sum(passed(row, ACCURACY) for row in rows) / n if n and accuracy_reviewed == n else None
    return {
        "sample_size": n,
        "qualification_reviewed": reviewed,
        "accuracy_reviewed": accuracy_reviewed,
        "qualification_pass_rate": rate,
        "channel_accuracy": channel,
        "contact_accuracy": contact,
        "joint_channel_contact_accuracy": joint,
        "standard_audit_thresholds_met": (rate >= 0.85 and joint >= 0.90)
        if rate is not None and joint is not None
        else None,
        "exceptional_audit_thresholds_met": (rate >= 0.90 and joint >= 0.95)
        if rate is not None and joint is not None
        else None,
        "requested_sample_complete": manifest["sample_complete"],
        "note": "Threshold results concern this sample only, not submission readiness or the assessor's independent random audit.",
    }


def country_mix(rows: list[dict]) -> dict:
    counts = Counter(row.get("country_iso2", "").strip().upper() for row in rows)
    n = len(rows)
    share = sum(counts[c] for c in APPROVED_MARKETS) / n if n else None
    known = {c: count for c, count in counts.items() if len(c) == 2 and c.isalpha()}
    maximum = max(known.values(), default=0) / n if n else None
    return {
        "rows": n,
        "countries": dict(counts),
        "known_country_count": len(known),
        "approved_share": share,
        "maximum_country_share": maximum,
        "approved_share_pass": share is not None and share >= 0.80,
        "country_count_pass": len(known) >= 3,
        "country_cap_pass": maximum is not None and maximum <= 0.60,
        "unknown_country_rows": sum(
            count for country, count in counts.items() if country not in known
        ),
    }


def source_name(row: dict) -> str:
    stable = row.get("stable_creator_id", "")
    if stable.startswith("apple-podcast:"):
        return "Apple Podcasts / publisher RSS"
    if stable.startswith("youtube-channel:"):
        return "YouTube"
    return row.get("primary_platform") or "Unknown"


def rejection_report(leads: list[dict], rejected: list[dict], pending: list[dict]) -> dict:
    grouped: Counter[tuple[str, str, str]] = Counter()
    exclusions = []
    for row in rejected:
        reasons = set(filter(None, row.get("rejection_reason", "").split(";"))) or {"unspecified"}
        for reason in reasons:
            grouped[reason, source_name(row), row.get("country_iso2") or "Unknown"] += 1
        if "not_clearly_creator_led" in reasons:
            exclusions.append(
                {
                    "stable_creator_id": row.get("stable_creator_id", ""),
                    "creator_name": row.get("creator_name", ""),
                    "source": source_name(row),
                    "reason": "not_clearly_creator_led",
                }
            )
    return {
        "qualified_rows": len(leads),
        "rejected_rows": len(rejected),
        "pending_rows": len(pending),
        "reason_counts": dict(
            Counter(
                {
                    reason: sum(v for (r, _s, _c), v in grouped.items() if r == reason)
                    for reason, _, _ in grouped
                }
            )
        ),
        "source_counts": dict(Counter(source_name(row) for row in rejected)),
        "country_counts": dict(Counter(row.get("country_iso2") or "Unknown" for row in rejected)),
        "grouped": [
            {"reason": reason, "source": source, "country": country, "count": count}
            for (reason, source, country), count in sorted(grouped.items())
        ],
        "country_mix": country_mix(leads),
        "creator_only_exclusions": exclusions,
        "note": "Multiple reasons can apply to one row. Pending evidence is reported separately. Exclusions reproduce existing decisions; they are not a new classifier or approval gate.",
    }


def trace(lead_id: str, ledger_path: Path) -> dict:
    matches = [
        row
        for row in read_rows(ledger_path)
        if row.get("lead_id") == lead_id or row.get("stable_creator_id") == lead_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one ledger record for {lead_id}; found {len(matches)}")
    row = matches[0]
    return {
        "lead_id": row.get("lead_id"),
        "creator_name": row.get("creator_name"),
        "status": row.get("candidate_status"),
        "evidence": evidence_chain(row),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--leads", type=Path, default=Path("output/leads.csv"))
    sample.add_argument("--ledger", type=Path, default=Path("output/evidence_ledger.csv"))
    sample.add_argument("--out", type=Path, default=Path("output/audit_sample.csv"))
    sample.add_argument("--size", type=int, default=40)
    sample.add_argument("--seed", type=int, default=AUDIT_SEED)
    score = sub.add_parser("score")
    score.add_argument("sample", type=Path)
    score.add_argument("--out", type=Path, default=Path("output/audit_results.json"))
    rejection = sub.add_parser("rejections")
    rejection.add_argument("--output", type=Path, default=Path("output"))
    tracing = sub.add_parser("trace")
    tracing.add_argument("lead_id")
    tracing.add_argument("--ledger", type=Path, default=Path("output/evidence_ledger.csv"))
    args = parser.parse_args()
    if args.command == "sample":
        result = create_sample(args.leads, args.ledger, args.out, args.size, args.seed)
    elif args.command == "score":
        result = score_sample(args.sample)
        write_text(args.out, json.dumps(result, indent=2))
    elif args.command == "trace":
        result = trace(args.lead_id, args.ledger)
    else:
        directory = args.output
        result = rejection_report(
            read_rows(directory / "leads.csv"),
            read_rows(directory / "rejections.csv"),
            read_rows(directory / "review_queue.csv"),
        )
        write_text(directory / "rejection_report.json", json.dumps(result, indent=2))
        _write_csv(
            directory / "rejection_counts.csv",
            result["grouped"],
            ["reason", "source", "country", "count"],
        )
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
