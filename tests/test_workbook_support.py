from pathlib import Path

from openpyxl import load_workbook

from incubrix_engine.workbook_support import supplement_workbook


def test_supplement_preserves_template_and_leaves_unmeasured_claims_blank(tmp_path):
    source = Path("assets/IncuBrix_Submission_Workbook_Template.xlsx")
    before = source.read_bytes()
    target = tmp_path / "review.xlsx"
    supplement_workbook(source, target, {"lead_count": 0})
    assert source.read_bytes() == before
    book = load_workbook(target)
    try:
        assert book["01_INSIGHT"]["B6"].value is None
        assert book["01_INSIGHT"]["B14"].value is None
        assert book["04_SELF_CHECK"]["C11"].value is None
        assert book["00_START"]["B17"].value is None
        assert "Gemini: NOT USED" in book["00_START"]["B16"].value
        assert "Podcast Index API" in book["00_START"]["B16"].value
        assert "Tavily" in book["00_START"]["B16"].value
        assert book["02_LEADS"]["AC5"].data_type == "f"
        assert "05_EVIDENCE_INDEX" in book.sheetnames
    finally:
        book.close()
