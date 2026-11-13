"""Tome preparation, spell selection and resource savings integration."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tests.gear.test_running_costs import prices
from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig
from tracker.gear.running_costs import evaluate_running_cost


def test_empty_shield_lock_prepares_without_mutating_request():
    request = OptimizationRequest(
        roles=(RoleConfig(id="mage", style="magic"),),
        locks={"shield": 20716},
        fire_tome_pages="searing",
    )
    execution = request.prepared_weapon_locks()
    assert execution.locks["shield"] == 20714
    assert request.locks["shield"] == 20716
    assert execution.roles[0].fire_tome_pages == "searing"
    assert "fire_tome_pages" not in execution.roles[0].model_dump()
    with pytest.raises(ValueError, match="excluded"):
        request.model_copy(update={"excluded_item_ids": (20714,)}).prepared_weapon_locks()


@pytest.mark.parametrize("charged,empty", [(20714, 20716), (25574, 25576), (30064, 30066)])
def test_owned_empty_is_preparation_not_observed_charged(charged, empty):
    content = load_content()
    item = load_catalog(content).items[charged]
    fact = equipment_fact(snapshot(levels={"magic": 99}, owned=(empty,)), item, content, {}, NOW)
    assert fact["ownership"]["status"] != "owned"
    assert fact["planning_ownership"]["status"] == "owned"
    assert fact["preparation"]["source_item_id"] == empty
    assert fact["preparation"]["usable_item_id"] == charged
    assert fact["preparation"]["market_item_id"] == empty
    assert "excluded" in fact["preparation"]["message"]


@pytest.mark.parametrize(
    "spell,tome,rune,staff",
    [
        ("fire_surge", 20714, 554, 1381),
        ("iban_blast", 20714, 554, 1409),
        ("ice_barrage", 25574, 555, 4675),
        ("earth_wave", 30064, 557, 1381),
    ],
)
def test_tome_supplies_supported_spell_runes(spell, tome, rune, staff):
    catalog = load_catalog(load_content())
    result = evaluate_running_cost(
        {"weapon": catalog.items[staff], "shield": catalog.items[tome]},
        {"attack_type": "magic", "spell": spell},
        {"attack_interval": 3, "dps": 2},
        prices(**{str(i): 5 for i in (554, 555, 556, 557, 560, 565, 21880)}),
        NOW,
    )
    row = next(r for r in result["resources"] if r["item_id"] == rune)
    assert row["consumed_quantity"] == 0
    assert row["supplied_by"] == catalog.items[tome].name
    assert result["status"] == "known"
    assert "excluded" in result["charging_assumption"]


def test_staff_wins_duplicate_supply_and_empty_does_not_supply():
    catalog = load_catalog(load_content())
    for tome, staff in [(20714, 1387), (20716, 1381)]:
        result = evaluate_running_cost(
            {"weapon": catalog.items[staff], "shield": catalog.items[tome]},
            {"attack_type": "magic", "spell": "fire_strike"},
            {"attack_interval": 3, "dps": 2},
            prices(**{"554": 4, "556": 5, "558": 3}),
            NOW,
        )
        fire = next(r for r in result["resources"] if r["item_id"] == 554)
        assert fire["consumed_quantity"] == (3 if tome == 20716 else 0)
        if tome == 20714:
            assert fire["supplied_by"] == catalog.items[staff].name


@pytest.mark.parametrize(
    "tome,empty,element", [(20714, 20716, "fire"), (25574, 25576, "water"), (30064, 30066, "earth")]
)
@pytest.mark.parametrize("pages", ["burnt", "searing"])
def test_optimizer_prepares_owned_tome_and_selects_matching_spell(tome, empty, element, pages):
    from tracker.domain.types import UnlockState
    from tracker.gear.combat import ELEMENTAL_SPELLS
    from tracker.gear.evaluation import evaluate_configurations
    from tracker.gear.optimizer import CombatOptionFilters, optimize

    content = load_content()
    all_items = load_catalog(content).items
    catalog = SimpleNamespace(items={i: all_items[i] for i in (1381, tome, empty)})
    account = replace(
        snapshot(levels={"magic": 99}, owned=(1381, empty)),
        unlocks={"spellbook_standard": UnlockState.UNLOCKED},
    )
    request = OptimizationRequest(
        roles=(
            RoleConfig(
                id="mage",
                style="magic",
                combat_options=CombatOptionFilters(
                    attack_types=("magic",), stances=("accurate",), spells=tuple(ELEMENTAL_SPELLS)
                ),
                locks={"weapon": 1381, "shield": empty},
            ),
        ),
        mode="owned",
        fire_tome_pages=pages,
        max_swaps=0,
    )
    result = optimize(account, request, catalog, content, {}, NOW)
    selected = result["selected_solution"]
    assert selected is not None
    loadout = selected["loadouts"]["mage"]
    assert loadout["equipment"]["shield"] == tome
    assert loadout["combat_option"]["spell"] == element + "_surge"
    assert loadout["performance"]["max_hit"] == 26
    assert selected["purchase_cost_gp"] == 0
    assert loadout["preparations"][0]["source_item_id"] == empty
    evaluated = evaluate_configurations(
        account,
        request,
        loadout["equipment"],
        loadout["equipment"],
        catalog,
        content,
        {},
        NOW,
        baseline_combat_option=loadout["combat_option"],
        proposed_combat_option=loadout["combat_option"],
    )
    assert evaluated["proposed"]["performance"] == loadout["performance"]


def test_excluded_empty_market_form_blocks_purchase_but_not_owned_charged():
    from tracker.gear.evaluation import item_problems

    content = load_content()
    item = load_catalog(content).items[20714]
    request = OptimizationRequest(
        roles=(RoleConfig(id="mage", style="magic"),), excluded_item_ids=(20716,), budget_gp=1000
    )
    for owned, blocked in [((), True), ((20714,), False), ((20716,), True)]:
        fact = equipment_fact(
            snapshot(levels={"magic": 99}, owned=owned),
            item,
            content,
            prices(**{"20716": 100}),
            NOW,
        )
        assert bool(item_problems(20714, fact, request)) == blocked


def test_page_choice_is_global_only():
    with pytest.raises(ValueError, match="scenario-wide"):
        RoleConfig(id="mage", style="magic", fire_tome_pages="searing")
    with pytest.raises(ValueError):
        OptimizationRequest(roles=(RoleConfig(id="mage", style="magic"),), fire_tome_pages="other")
