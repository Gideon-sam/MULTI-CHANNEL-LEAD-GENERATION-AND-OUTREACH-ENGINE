import json

from openpyxl import load_workbook

from incubrix_engine.review_pack import build


def test_review_pack_keeps_real_status_and_candidate_verdicts_blank(tmp_path):
    (tmp_path / "submission_status.json").write_text(
        json.dumps(
            {
                "output_directory": "output/runs/test",
                "engine_qualified_rows": 1,
                "pending_rows": 2,
                "rejected_rows": 3,
                "priority_a_rows": 1,
                "human_audit_pass_rate": None,
                "submission_ready": False,
                "audit_sample": "audit.csv",
                "audit_sample_rows": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "validation_report.json").write_text(json.dumps({"checks": []}), encoding="utf-8")
    (tmp_path / "rejection_report.json").write_text(json.dumps({"grouped": []}), encoding="utf-8")
    csv = "lead_id,stable_creator_id,creator_name,my_verdict_identity\nINC-1,test:1,Real Person,\n"
    (tmp_path / "leads.csv").write_text(csv, encoding="utf-8")
    (tmp_path / "audit.csv").write_text(csv, encoding="utf-8")
    destination = tmp_path / "pack.xlsx"
    build(tmp_path, destination)
    book = load_workbook(destination, read_only=True)
    try:
        assert book.sheetnames == [
            "00_OVERVIEW",
            "01_QUALIFIED_LEADS",
            "02_AUDIT_40",
            "03_FETCHED_EVIDENCE",
            "04_REJECTIONS",
            "05_MANUAL_TODOS",
        ]
        assert book["00_OVERVIEW"]["B6"].value == 1
        assert book["02_AUDIT_40"]["N5"].value is None
    finally:
        book.close()
