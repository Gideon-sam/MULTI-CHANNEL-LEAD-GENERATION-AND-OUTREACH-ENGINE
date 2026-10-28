import csv
import json

from incubrix_engine.submission import lead_from_row, source_rows


def test_assembly_preserves_evidence_dates_status_and_numeric_fields():
    row = {
        "lead_id": "SYN-1",
        "stable_creator_id": "youtube-channel:synthetic",
        "candidate_status": "Needs review",
        "content_count_30d": "8",
        "longform_count_60d": "2",
        "lead_score": "95",
        "metadata": json.dumps(
            {
                "evidence_snapshots": {
                    "https://example.test": {"retrieved_at": "2026-10-01T00:00:00Z"}
                }
            }
        ),
    }
    result = lead_from_row(row)
    assert result.candidate_status == "Needs review"
    assert result.content_count_30d == 8 and result.lead_score == 95
    assert (
        result.metadata["evidence_snapshots"]["https://example.test"]["retrieved_at"]
        == "2026-10-01T00:00:00Z"
    )


def test_evidence_rows_label_source_without_changing_status():
    youtube = lead_from_row(
        {
            "stable_creator_id": "youtube-channel:UC-real",
            "candidate_status": "Needs review",
        }
    )
    apple = lead_from_row(
        {
            "stable_creator_id": "apple-podcast:123",
            "candidate_status": "Rejected",
        }
    )
    assert youtube.evidence_row()["source_system"] == "YouTube Data API"
    assert apple.evidence_row()["source_system"] == "Apple Podcasts + publisher RSS"
    assert youtube.candidate_status == "Needs review"
    assert apple.candidate_status == "Rejected"


def test_assembly_prefers_structured_pending_metadata(tmp_path):
    with (tmp_path / "review_queue.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["stable_creator_id", "metadata"])
        writer.writeheader()
        writer.writerow({"stable_creator_id": "apple-podcast:123", "metadata": "{'broken': 1}"})
    (tmp_path / "review_queue.json").write_text(
        json.dumps(
            [
                {
                    "stable_creator_id": "apple-podcast:123",
                    "metadata": {"activity_items": [{"title": "Real episode"}]},
                }
            ]
        ),
        encoding="utf-8",
    )
    rows = source_rows(tmp_path, "review_queue.csv")
    assert rows[0]["metadata"]["activity_items"][0]["title"] == "Real episode"
