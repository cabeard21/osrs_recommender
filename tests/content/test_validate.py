"""Focused validation of the authored facts used by account and Gear services."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracker.content.loader import ContentValidationError, load_content
from tracker.content.validate import load_and_validate, main, validate_content

ROOT = Path(__file__).parents[2] / "content"
CORRUPT = Path(__file__).parent / "corrupt"


def test_shipped_factual_corpus_loads_and_validates() -> None:
    content = load_and_validate(ROOT)
    assert content.skills
    assert content.quests
    assert content.items
    assert validate_content(content) == []
    assert content.item_by_numeric_id(27690) is not None


@pytest.mark.parametrize(
    ("directory", "diagnostic"),
    [
        ("01_duplicate_id", "duplicate skill id"),
        ("07_live_price_without_item_id", "price_mode: live but no numeric item_id"),
        ("15_tier_without_ladder", "no gear ladder to sit on"),
        ("16_duplicate_gear_rung", "shares melee weapon tier 3"),
        ("17_item_id_claimed_twice", "claims item id 27690"),
        ("18_item_requires_dangling_reference", "references quest"),
        ("19_item_requires_cycle", "item requirements form a cycle"),
        ("20_item_gate_known_and_unknown", "declares both requires and gate_unknown"),
        ("21_item_acquired_from_without_untradeable", "declares acquired_from without"),
        ("22_shared_id_disagrees_about_the_piece", "not the same piece"),
    ],
)
def test_invalid_factual_content_is_located(directory: str, diagnostic: str) -> None:
    with pytest.raises(ContentValidationError) as caught:
        load_and_validate(CORRUPT / directory)
    assert diagnostic in str(caught.value)
    assert all(error.location.file is not None for error in caught.value.errors)


def test_missing_directory_and_unknown_item_field_fail(tmp_path: Path) -> None:
    with pytest.raises(ContentValidationError, match="does not exist"):
        load_content(tmp_path / "missing")
    items = tmp_path / "items"
    items.mkdir()
    (items / "bad.yaml").write_text("id: x\nname: X\nprice_moed: live\n", encoding="utf-8")
    with pytest.raises(ContentValidationError, match="price_moed"):
        load_content(tmp_path)


def test_validation_cli_reports_factual_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--content-dir", str(ROOT)]) == 0
    assert "skills" in capsys.readouterr().out
