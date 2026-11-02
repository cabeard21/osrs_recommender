"""Iban Blast uses its own staff and fixed, non-elemental damage."""

from dataclasses import replace

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tests.gear.test_combat_options import account
from tests.gear.test_running_costs import evaluate, prices
from tools.import_equipment import REVIEWED
from tracker.api.gear_ui import combat_option_capabilities
from tracker.content.loader import load_content
from tracker.domain.types import QuestStatus
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout
from tracker.gear.combat_options import eligible_combat_options
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


@pytest.mark.parametrize("staff_id", [1409, 12658])
@pytest.mark.parametrize("automatic", [True, False])
def test_iban_staff_can_be_optimized_with_explicit_spell_filter(reviewed, staff_id, automatic):
    content, catalog = reviewed
    player = snapshot(owned=(staff_id,), quests={"underground_pass": QuestStatus.COMPLETE})
    role = RoleConfig(
        id="mage",
        style="magic",
        spell="iban_blast",
        combat_options=CombatOptionFilters(
            attack_types=("magic",), stances=("accurate",), spells=("iban_blast",)
        )
        if automatic
        else None,
    )
    request = OptimizationRequest(roles=(role,), mode="owned", locks={"weapon": staff_id})
    solution = optimize(player, request, catalog, content, {}, NOW)["selected_solution"]
    assert solution is not None
    loadout = solution["loadouts"]["mage"]
    if automatic:
        assert loadout["combat_option"]["spell"] == "iban_blast"
    assert loadout["performance"]["max_hit"] == 25
    assert catalog.items[staff_id].requirements_complete
    assert staff_id in REVIEWED


@pytest.mark.parametrize("level", [50, 99])
def test_iban_fixed_damage_does_not_affect_elemental_blasts(reviewed, level):
    _, catalog = reviewed
    target = CombatTarget(weakness_element="fire", weakness_percent=100)
    iban = evaluate_loadout(
        [catalog.items[12658]], "magic", {"magic": level}, target, spell="iban_blast"
    )
    assert iban.supported and iban.max_hit == 25
    fire = evaluate_loadout(
        [catalog.items[1387]],
        "magic",
        {"magic": level},
        spell="fire_blast" if level == 99 else "wind_blast",
    )
    assert fire.supported and fire.max_hit == (16 if level == 99 else 14)


@pytest.mark.parametrize("staff_id", [None, 1387, 12000])
def test_iban_requires_its_staff_even_for_fixed_evaluation(reviewed, staff_id):
    _, catalog = reviewed
    item = catalog.items[staff_id] if staff_id else None
    player = replace(account(), quests={"underground_pass": QuestStatus.COMPLETE})
    assert "iban_blast" not in {
        o.spell for o in eligible_combat_options(item, player, discipline="magic", levels={})
    }
    result = evaluate_loadout([item] if item else [], "magic", {"magic": 99}, spell="iban_blast")
    assert not result.supported


def test_iban_level_quest_and_capability_filter(reviewed):
    from types import SimpleNamespace

    _, catalog = reviewed
    gear = SimpleNamespace(equipment_catalog=lambda: catalog)
    for level, quests, available in [
        (49, {"underground_pass": QuestStatus.COMPLETE}, False),
        (50, {}, False),
        (50, {"underground_pass": QuestStatus.NOT_STARTED}, False),
        (50, {"underground_pass": QuestStatus.COMPLETE}, True),
    ]:
        player = replace(account(magic=level), quests=quests)
        options = eligible_combat_options(
            catalog.items[12658], player, discipline="magic", levels={}
        )
        assert ("iban_blast" in {o.spell for o in options}) is available
        spells = combat_option_capabilities(player, gear)["spells"]
        iban = next(row for row in spells if row["id"] == "iban_blast")
        assert iban["available"] is available


@pytest.mark.parametrize("attack", [49, None])
def test_iban_attack_requirement_and_unknown_charges(reviewed, attack):
    _, catalog = reviewed
    player = replace(account(), quests={"underground_pass": QuestStatus.COMPLETE})
    skills = {key: state for key, state in player.skills.items() if key != "attack"}
    if attack is not None:
        skills = {**skills, "attack": replace(player.skills["attack"], level=attack)}
    blocked = replace(player, skills=skills)
    assert not eligible_combat_options(catalog.items[12658], blocked, discipline="magic", levels={})
    options = eligible_combat_options(catalog.items[12658], player, discipline="magic", levels={})
    assert options and all(row.charges == "unknown" for row in options)


def test_iban_rune_recipe():
    result = evaluate(spell="iban_blast", staff=12658, records=prices(**{"554": 4, "560": 100}))
    assert result["status"] == "known"
    assert result["gp_per_attack"] == 120
    assert {r["item_id"]: r["consumed_quantity"] for r in result["resources"]} == {
        554: 5,
        560: 1,
    }
