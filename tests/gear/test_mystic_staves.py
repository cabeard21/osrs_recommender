"""Ordinary mystic elemental staves must work through account-aware search."""

from dataclasses import replace

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tests.gear.test_combat_options import account
from tools.import_equipment import REVIEWED
from tracker.content.loader import load_content
from tracker.domain.types import SkillState, Source
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import ELEMENTAL_SPELLS
from tracker.gear.combat_options import eligible_combat_options
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

STAVES = (1401, 1403, 1405, 1407)


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


@pytest.mark.parametrize("item_id", STAVES)
def test_mystic_staff_review_and_standard_spells(reviewed, item_id):
    _, catalog = reviewed
    item = catalog.items[item_id]
    assert item.requirements_complete
    assert item.tradeable
    assert not item.unsupported_effects
    assert item_id in REVIEWED  # A subsequent catalog import must retain the review.
    assert set(item.spell_compatibility) == set(ELEMENTAL_SPELLS)
    assert {
        o.spell for o in eligible_combat_options(item, account(), discipline="magic", levels={})
    } == set(ELEMENTAL_SPELLS)


@pytest.mark.parametrize("item_id", STAVES)
def test_mystic_staff_wear_boundaries_without_creation_quest(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    for levels, expected in (
        ({"attack": 40, "magic": 40}, "satisfied"),
        ({"attack": 39, "magic": 40}, "unsatisfied"),
        ({"attack": 40, "magic": 39}, "unsatisfied"),
        ({"magic": 40}, "unknown"),
        ({"attack": 40}, "unknown"),
    ):
        fact = equipment_fact(snapshot(levels=levels, quests={}), item, content, {}, NOW)
        assert fact["wear"]["status"] == expected


@pytest.mark.parametrize("item_id", STAVES)
def test_owned_mystic_staff_can_be_selected_with_enchanted_robes(reviewed, item_id):
    content, catalog = reviewed
    equipment = {"weapon": item_id, "body": 7399, "legs": 7398}
    levels = {"attack": 40, "magic": 40, "defence": 20, "strength": 40}
    player = replace(
        account(magic=40),
        skills={key: SkillState(value, None, Source.MANUAL, NOW) for key, value in levels.items()},
        observed_items=snapshot(owned=tuple(equipment.values())).observed_items,
    )
    # Keep physical ownership exact, including the robes reported with this bug.
    role = RoleConfig(id="mage", style="magic", spell="fire_bolt")
    request = OptimizationRequest(roles=(role,), mode="owned", locks=equipment, max_swaps=0)
    result = optimize(player, request, catalog, content, {}, NOW)
    solution = result["selected_solution"]
    assert solution is not None
    assert solution["loadouts"]["mage"]["equipment"] == equipment
    assert solution["loadouts"]["mage"]["performance"]["dps"] > 0
    unknown_ownership = replace(player, observed_items={})
    assert (
        optimize(unknown_ownership, request, catalog, content, {}, NOW)["selected_solution"] is None
    )


def test_unreviewed_special_staff_remains_blocked(reviewed):
    _, catalog = reviewed
    assert catalog.items[12000].unsupported_effects  # Smoke damage/accuracy needs its own model.
