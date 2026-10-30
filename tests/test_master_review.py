from incubrix_engine.master_review import _eligible_youtube, select_candidates
from incubrix_engine.models import Lead


def lead(stable_id: str, name: str, reason: str = "") -> Lead:
    return Lead(stable_creator_id=stable_id, creator_name=name, rejection_reason=reason)


def test_hard_failures_are_not_returned_to_youtube_manual_pool():
    assert _eligible_youtube(lead("youtube-channel:1", "Good Creator"))
    assert not _eligible_youtube(
        lead("youtube-channel:2", "Inactive Creator", "activity_threshold_not_met")
    )


def test_selection_excludes_user_rejections_and_duplicate_creator_names():
    rows, index = select_candidates(
        [lead("apple-podcast:1", "Alex Creator"), lead("apple-podcast:2", "Rejected")],
        [lead("apple-podcast:3", "Alex Creator"), lead("apple-podcast:4", "Blair Creator")],
        [lead("youtube-channel:5", "Casey Creator")],
        {"apple-podcast:2"},
        {"apple-podcast:1"},
        3,
    )
    assert {row.stable_creator_id for row in rows} == {
        "apple-podcast:1",
        "apple-podcast:4",
        "youtube-channel:5",
    }
    assert index[0]["source_group"] == "source_rechecked"
