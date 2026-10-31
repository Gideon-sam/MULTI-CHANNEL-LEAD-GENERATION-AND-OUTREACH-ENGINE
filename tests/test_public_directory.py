import json

import openpyxl
import pytest

from incubrix_engine.public_directory import build_directory, public_url
from incubrix_engine.review import PROOF_KINDS


def test_directory_joins_ids_and_keeps_approvals_separate_from_missing_evidence(tmp_path):
    book = openpyxl.Workbook()
    index = book.active
    index.title = "REVIEW_INDEX"
    index.append(["stable_creator_id", "manual_decision", "current_engine_status"])
    index.append(["youtube-channel:first", "Approve", "Needs review"])
    index.append(["apple-podcast:second", "Pending", "Needs review"])
    candidates = book.create_sheet("Candidates")
    candidates.append(["stable_creator_id", "creator_name", "contact_hint", "content_count_30d"])
    candidates.append(["apple-podcast:second", "Second", "second@example.test", None])
    candidates.append(["youtube-channel:first", "First <script>bad()</script>", "first@example.test", 9])
    reviews = book.create_sheet("Reviews")
    headers = ["stable_creator_id", "decision", "reviewer"]
    for kind in PROOF_KINDS:
        headers.extend([f"{kind}_url", f"{kind}_quote"])
    reviews.append(headers)
    reviews.append(["apple-podcast:second", "Pending", "PRIVATE REVIEWER"] + [None] * 16)
    reviews.append(["youtube-channel:first", "Pending", "PRIVATE REVIEWER"] + ["https://example.test", "Excerpt"] * 8)
    source = tmp_path / "review.xlsx"
    book.save(source)
    book.close()
    destination = tmp_path / "data"
    stats = build_directory(source, destination)
    index = json.loads((destination / stats["version"] / "index.json").read_text())
    first = index["rows"][0]
    assert first["contact"] == "first@example.test"
    assert first["verdict"] == "Approve"
    assert first["engine_status"] == "Needs review"
    assert first["proof_count"] == 8
    assert index["rows"][1]["items30"] is None
    details = (destination / stats["version"] / "details-0.json").read_text()
    assert "PRIVATE REVIEWER" not in details
    assert json.loads(details)[first["key"]]["facts"]["import_decision"] == "Pending"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://user:password@example.test", "https://example.test/?api_key=secret",
    "https://example.test/?token=secret", "https://exa mple.test", "https://[invalid",
])
def test_directory_does_not_publish_credential_or_unsafe_links(url):
    assert public_url(url) == ""


def test_directory_preserves_public_source_links():
    url = "https://www.youtube.com/watch?v=public-id"
    assert public_url(url) == url
