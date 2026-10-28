import json

import pytest

from incubrix_engine.audit_support import (
    ACCURACY,
    VERDICTS,
    country_mix,
    create_sample,
    read_rows,
    rejection_report,
    score_sample,
    trace,
)
from incubrix_engine.exporters import _write_csv


def test_sample_is_reproducible_and_never_invents_rows(tmp_path):
    rows = [
        {"lead_id": str(i), "stable_creator_id": f"test:{i}", "creator_name": f"Synthetic {i}"}
        for i in range(60)
    ]
    source = tmp_path / "leads.csv"
    _write_csv(source, rows, list(rows[0]))
    first = create_sample(source, source, tmp_path / "one.csv")
    _write_csv(source, list(reversed(rows)), list(rows[0]))
    second = create_sample(source, source, tmp_path / "two.csv")
    assert first["selected_lead_ids"] == second["selected_lead_ids"]
    assert len(set(first["selected_lead_ids"])) == 40
    assert score_sample(tmp_path / "one.csv")["qualification_pass_rate"] is None
    with pytest.raises(FileExistsError):
        create_sample(source, source, tmp_path / "one.csv")


def test_small_audit_is_explicitly_incomplete_and_rates_require_all_verdicts(tmp_path):
    rows = [{"lead_id": str(i), "stable_creator_id": f"test:{i}"} for i in range(4)]
    source, sample = tmp_path / "leads.csv", tmp_path / "audit.csv"
    _write_csv(source, rows, list(rows[0]))
    manifest = create_sample(source, source, sample)
    assert manifest["sample_size"] == 4 and not manifest["sample_complete"]
    sampled = read_rows(sample)
    for row in sampled:
        row.update(dict.fromkeys((*VERDICTS, *ACCURACY), "pass"))
    sampled[0][VERDICTS[0]] = "fail"
    sampled[1][ACCURACY[1]] = "fail"
    _write_csv(sample, sampled, list(sampled[0]))
    scores = score_sample(sample)
    assert scores["qualification_pass_rate"] == 0.75
    assert scores["channel_accuracy"] == 1
    assert scores["contact_accuracy"] == 0.75
    sampled.pop()
    _write_csv(sample, sampled, list(sampled[0]))
    with pytest.raises(ValueError, match="roster"):
        score_sample(sample)


def countries(*values):
    return [{"country_iso2": value} for value in values]


def test_approved_market_share_boundary():
    assert country_mix(countries(*(["US"] * 8 + ["DE"] * 2)))["approved_share_pass"]
    assert not country_mix(countries(*(["US"] * 7 + ["DE"] * 3)))["approved_share_pass"]


def test_three_known_countries_required():
    assert country_mix(countries("US", "CA", "GB"))["country_count_pass"]
    assert not country_mix(countries("US", "CA", ""))["country_count_pass"]


def test_no_country_exceeds_sixty_percent():
    assert country_mix(countries("US", "US", "US", "CA", "GB"))["country_cap_pass"]
    assert not country_mix(countries("US", "US", "US", "US", "CA"))["country_cap_pass"]
    assert not country_mix([])["country_cap_pass"]


def test_creator_exclusions_and_multi_reason_grouping():
    rows = [
        {
            "stable_creator_id": "youtube-channel:test",
            "creator_name": "Synthetic Agency",
            "country_iso2": "US",
            "rejection_reason": "not_clearly_creator_led;activity_threshold_not_met",
        }
    ]
    report = rejection_report([], rows, [{}])
    assert report["source_counts"] == {"YouTube": 1}
    assert report["country_counts"] == {"US": 1}
    assert report["reason_counts"]["not_clearly_creator_led"] == 1
    assert len(report["creator_only_exclusions"]) == 1
    assert report["pending_rows"] == 1 and report["rejected_rows"] == 1


def test_trace_preserves_quotes_and_does_not_invent_missing_fetch_dates(tmp_path):
    row = {
        "lead_id": "test-1",
        "creator_name": "Synthetic",
        "metadata": json.dumps(
            {
                "review": {
                    "proofs": {
                        "identity": {
                            "url": "https://example.test",
                            "quote": "Exact  spacing & text.",
                        }
                    }
                },
                "evidence_snapshots": {
                    "https://example.test": {"retrieved_at": "2026-10-28T00:00:00Z"}
                },
            }
        ),
    }
    ledger = tmp_path / "ledger.csv"
    _write_csv(ledger, [row], list(row))
    result = trace("test-1", ledger)
    identity = result["evidence"][0]
    assert identity["verbatim_snippet"] == "Exact  spacing & text."
    assert identity["fetch_date"] == "2026-10-28T00:00:00Z"
    assert result["evidence"][1]["fetch_date"] == ""
