from dataclasses import replace
from pathlib import Path

import pytest

from tests.gear.test_scoring_options import context
from tracker.content.loader import load_content
from tracker.domain.types import UnlockState
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import RoleConfig


@pytest.fixture(scope="module")
def catalog():
    content = load_content(Path("content"))
    return content, load_catalog(content)


def test_complete_exact_variants_and_wear_requirements(catalog):
    from tracker.gear.void_ranged import (
        ELITE_ROBES,
        ELITE_TOPS,
        RANGER_HELMS,
        VOID_GLOVES,
        is_elite_ranged,
    )

    _, gear = catalog
    groups = (RANGER_HELMS, ELITE_TOPS, ELITE_ROBES, VOID_GLOVES)
    for ids in groups:
        for item_id in ids:
            item = gear.items[item_id]
            assert (
                item.requirements_complete and not item.unsupported_effects and not item.tradeable
            )
            assert len(item.requires.to_yaml()["all_of"]) == 7
    assert is_elite_ranged((26475, 13072, 24180, 27002))
    assert not is_elite_ranged((11664, 13072, 8840, 8842))
    assert not is_elite_ranged((11664, 20467, 13073, 8842))
    assert not is_elite_ranged((11664, 13072, 13073))
    assert gear.items[20467].unsupported_effects


def test_western_diary_only_gates_elite_acquisition(catalog):
    content, gear = catalog
    snapshot, _, _, _ = context(RoleConfig(id="ranged", style="ranged"))
    for unlock, expected in (
        (UnlockState.UNLOCKED, "satisfied"),
        (UnlockState.LOCKED, "unsatisfied"),
    ):
        state = replace(snapshot, unlocks={"diary_western_hard": unlock})
        fact = equipment_fact(state, gear.items[13072], content, {}, state.last_sync_at)
        assert fact["acquisition_requirement"]["status"] == expected
        assert "diary_western_hard" not in str(gear.items[13072].requires)
        assert "acquisition_requirement" not in equipment_fact(
            state, gear.items[8842], content, {}, state.last_sync_at
        )


def test_published_fixture_armour(catalog):
    _, gear = catalog
    for item_id in (19933, 29022, 29025, 29028):
        item = gear.items[item_id]
        assert item.tradeable and item.requirements_complete and not item.unsupported_effects
    assert gear.items[29067].unsupported_effects  # Broken chestplate
    assert "dual macuahuitl" in gear.items[29028].omitted_set_effects[0]
