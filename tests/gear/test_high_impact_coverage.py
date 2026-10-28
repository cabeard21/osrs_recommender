"""Exact-ID High-impact reviews and fail-closed ordinary-combat acceptance.

Requirements are independently transcribed from the pinned item pages in the
High-impact report; full physical fields are compared with the upstream capture.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.import_equipment import normalize
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source, UnlockState
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.evaluation import evaluate_configuration, evaluate_equipment, item_problems
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)
QUEST = "recipe_for_disaster_culinaromancer"
RULES = {
    7460: {},
    7459: {"defence": 13},
    7458: {},
    29280: {"ranged": 60, "defence": 50},
    29286: {"ranged": 60, "defence": 50},
    29289: {"ranged": 60, "defence": 50},
    2501: {"ranged": 60, "defence": 40},
    2495: {"ranged": 60},
    6733: {},
    2577: {"ranged": 40},
}
CASES = list(RULES)
UNTRADEABLE = (7458, 7459, 7460)
TRADEABLE_CASES = [i for i in CASES if i not in UNTRADEABLE]
SOURCE_ROWS = {
    row["id"]: row
    for row in json.loads(
        Path("tests/fixtures/gear_high_impact_source.json").read_text(encoding="utf-8")
    )["rows"]
}
LEVELS = dict.fromkeys(("attack", "strength", "defence", "magic", "ranged"), 70)


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


def snapshot(*, levels=None, owned=(), quests=None):
    return AccountSnapshot(
        1,
        "high-impact-synthetic",
        skills={
            key: SkillState(value, None, Source.MANUAL, NOW)
            for key, value in (LEVELS if levels is None else levels).items()
        },
        quests={QUEST: QuestStatus.COMPLETE} if quests is None else quests,
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "test", NOW)
            for i in owned
        },
    )


def scaffold(item):
    if item.id not in UNTRADEABLE:
        return {"weapon": 857, "ammunition": 886, item.slot: item.id}, "ranged"
    return {"weapon": 1333, item.slot: item.id}, "slash"


def quote(item_id, *, age=0):
    return SimpleNamespace(
        item_id=item_id,
        high_price_gp=100,
        high_trade_at=NOW - timedelta(days=age),
        low_price_gp=90,
        low_trade_at=NOW - timedelta(days=age),
        fetched_at=NOW,
        source="live",
    )


@pytest.mark.parametrize("item_id", CASES)
def test_reviewed_identity_statistics_and_exact_ordinary_approval(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    source = SOURCE_ROWS[item_id]
    assert item.id == source["id"]
    assert item.name == source["name"]
    assert item.slot == source["slot"]
    assert item.two_handed == source["isTwoHanded"] is False
    assert item.attack_speed == max(1, source["speed"])
    assert item.attack_styles == ()
    assert item.attack_profiles == ()
    assert item.ammo_type is None
    assert item.ammo_for == ()
    assert item.bonuses.model_dump() == {
        **source["offensive"],
        "melee_strength": source["bonuses"]["str"],
        "ranged_strength": source["bonuses"]["ranged_str"],
        "magic_damage": source["bonuses"]["magic_str"] / 10,
        **{"defence_" + key: value for key, value in source["defensive"].items()},
        "prayer": source["bonuses"]["prayer"],
    }
    assert item.requirements_complete
    assert not item.unsupported_effects
    assert item.tradeable is (item_id not in UNTRADEABLE)
    assert normalize(source)["unsupported_effects"] == []
    if item_id not in UNTRADEABLE:
        authored = [entry for entry in content.items.values() if entry.item_id == item_id]
        assert len(authored) == 1
        assert authored[0].variant_item_ids == ()
        assert authored[0].tier is None or item_id in (29280, 29286, 29289)
        assert authored[0].price_mode == "live"
        assert authored[0].fallback_price_gp is None or item_id in (29280, 29286, 29289)


@pytest.mark.parametrize("item_id", CASES)
def test_wear_skill_boundaries_and_missing_facts_remain_fail_closed(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    rules = RULES[item_id]
    for delta in (0, 1):
        account = snapshot(levels={key: value + delta for key, value in rules.items()})
        assert equipment_fact(account, item, content, {}, NOW)["wear"]["status"] == "satisfied"
    for skill, required in rules.items():
        below = snapshot(levels={**rules, skill: required - 1})
        missing = snapshot(levels={key: value for key, value in rules.items() if key != skill})
        assert equipment_fact(below, item, content, {}, NOW)["wear"]["status"] == "unsatisfied"
        assert equipment_fact(missing, item, content, {}, NOW)["wear"]["status"] == "unknown"


@pytest.mark.parametrize("item_id", CASES)
def test_owned_access_needs_no_price_and_unknown_ownership_stays_unknown(reviewed, item_id):
    content, catalog = reviewed
    request = OptimizationRequest(roles=(RoleConfig(id="one", style="slash"),), mode="owned")
    item = catalog.items[item_id]
    observed = equipment_fact(snapshot(owned=(item_id,)), item, content, {}, NOW)
    assert not item_problems(item_id, observed, request)
    assert observed["price"]["amount_gp"] is None or item_id in (29280, 29286, 29289)
    unknown = equipment_fact(snapshot(), item, content, {}, NOW)
    assert unknown["ownership"]["status"] == "unknown"
    assert item_problems(item_id, unknown, request)


@pytest.mark.parametrize("item_id", TRADEABLE_CASES)
def test_purchases_require_exact_price_and_respect_budget(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    equipment, style = scaffold(item)
    role = RoleConfig(id="one", style=style)
    account = snapshot(owned=tuple(i for i in equipment.values() if i != item_id))
    request = OptimizationRequest(roles=(role,), mode="usable", budget_gp=99)
    no_quote = equipment_fact(account, item, content, {}, NOW)
    assert item_problems(item_id, no_quote, request) or item_id in (29280, 29286, 29289)
    facts = {
        i: equipment_fact(account, catalog.items[i], content, {item_id: quote(item_id)}, NOW)
        for i in equipment.values()
    }
    assert facts[item_id]["ownership"]["status"] == "unknown"
    assert facts[item_id]["price"]["amount_gp"] == 100
    result = evaluate_configuration(equipment, catalog.items, facts, request, role, LEVELS)
    assert result["status"] == "invalid"
    assert result["purchase_cost_gp"] == 100
    assert result["purchases"] == [{"item_id": item_id, "cost_gp": 100, "conditional": True}]
    affordable = evaluate_configuration(
        equipment,
        catalog.items,
        facts,
        request.model_copy(update={"budget_gp": 100}),
        role,
        LEVELS,
    )
    assert affordable["status"] == "valid"
    stale = equipment_fact(account, item, content, {item_id: quote(item_id, age=31)}, NOW)
    assert stale["price"]["layer"] == "cached"
    assert stale["price"]["amount_gp"] == 100


@pytest.mark.parametrize("item_id", CASES)
def test_each_reviewed_item_evaluates_and_optimizes_as_concrete_locked_equipment(reviewed, item_id):
    content, catalog = reviewed
    equipment, style = scaffold(catalog.items[item_id])
    role = RoleConfig(id="one", style=style)
    exact = evaluate_equipment(equipment, catalog.items, role, LEVELS)
    assert exact.supported
    assert exact.dps > 0
    account = snapshot(owned=tuple(equipment.values()))
    request = OptimizationRequest(roles=(role,), mode="owned", locks=equipment, max_swaps=0)
    answer = optimize(account, request, catalog, content, {}, NOW)
    assert answer["search"]["quality"] == "best_found"
    solution = answer["selected_solution"]
    assert solution is not None
    assert solution["purchase_cost_gp"] == 0
    assert solution["loadouts"]["one"]["equipment"] == equipment
    assert solution["loadouts"]["one"]["performance"] == exact.model_dump(mode="json")
    before = EquipmentCatalog(
        {
            i: item.model_copy(update={"unsupported_effects": ("Unreviewed effect",)})
            if i == item_id
            else item
            for i, item in catalog.items.items()
        }
    )
    assert optimize(account, request, before, content, {}, NOW)["selected_solution"] is None


def test_rune_gloves_explicit_training_or_final_subquest_not_defence_or_mm1(reviewed):
    content, catalog = reviewed

    def wear(account):
        return equipment_fact(account, catalog.items[7460], content, {}, NOW)["wear"]["status"]

    absent = snapshot(quests={"monkey_madness_i": QuestStatus.COMPLETE})
    assert wear(absent) == "unknown"
    assert wear(snapshot()) == "satisfied"
    assert (
        wear(replace(absent, unlocks={"daero_training_complete": UnlockState.UNLOCKED}))
        == "satisfied"
    )
    denied = snapshot(quests={QUEST: QuestStatus.NOT_STARTED})
    assert (
        wear(replace(denied, unlocks={"daero_training_complete": UnlockState.LOCKED}))
        == "unsatisfied"
    )


@pytest.mark.parametrize("item_id", (7458, 7459, 2501))
def test_acquisition_quests_are_not_wear_gates(reviewed, item_id):
    content, catalog = reviewed
    assert (
        equipment_fact(snapshot(quests={}), catalog.items[item_id], content, {}, NOW)["wear"][
            "status"
        ]
        == "satisfied"
    )


@pytest.mark.parametrize("item_id", (7457, 29283, 11771))
def test_related_unreviewed_items_do_not_inherit_approval(reviewed, item_id):
    _, catalog = reviewed
    assert catalog.items[item_id].unsupported_effects


@pytest.mark.parametrize("item_id", UNTRADEABLE)
def test_gloves_cannot_be_bought_from_a_market_quote(reviewed, item_id):
    content, catalog = reviewed
    fact = equipment_fact(
        snapshot(), catalog.items[item_id], content, {item_id: quote(item_id)}, NOW
    )
    assert fact["acquisition"] == "untradeable"
    assert fact["price"]["amount_gp"] is None
    request = OptimizationRequest(roles=(RoleConfig(id="one", style="slash"),), mode="usable")
    assert item_problems(item_id, fact, request)


@pytest.mark.parametrize("owned,other", ((7458, 7459), (7459, 7460), (6733, 11771)))
def test_no_ownership_or_price_aliases(reviewed, owned, other):
    content, catalog = reviewed
    fact = equipment_fact(
        snapshot(owned=(owned,)), catalog.items[other], content, {owned: quote(owned)}, NOW
    )
    assert fact["ownership"]["status"] == "unknown"
    assert fact["price"]["amount_gp"] is None
