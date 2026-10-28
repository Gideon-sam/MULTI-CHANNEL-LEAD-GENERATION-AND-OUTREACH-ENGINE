from __future__ import annotations

from incubrix_engine.sources.youtube import (
    _contact,
    _creator_led,
    _creator_name,
    _iso_duration_minutes,
)


def test_iso_duration_parser() -> None:
    assert _iso_duration_minutes("PT12M35S") == 12
    assert _iso_duration_minutes("PT1H2M") == 62
    assert _iso_duration_minutes("not-a-duration") == 0


def test_creator_filter_requires_personal_or_expert_signal() -> None:
    assert _creator_led("Alex Smith", "I help founders improve their sales process.")
    assert not _creator_led("Example News Network", "Daily reporting from our newsroom.")
    assert (
        _creator_name("Creator Upload", "A podcast hosted by Lauren Schnipper and Joshua Cohen.")
        == "Lauren Schnipper and Joshua Cohen"
    )


def test_contact_uses_public_description_without_guessing() -> None:
    result = _contact(
        "Business: alex@example.com More: https://instagram.com/alex",
        "https://www.youtube.com/channel/abc",
    )
    assert result[:4] == (
        "Email",
        "alex@example.com",
        "Instagram",
        "https://instagram.com/alex",
    )
