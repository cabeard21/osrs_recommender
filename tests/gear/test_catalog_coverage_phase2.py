"""Exact-ID Phase 2 reviews and fail-closed ordinary-combat acceptance.

Requirements are independently transcribed from the pinned item pages in the
Phase 2 report; full physical fields are compared with the upstream capture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.import_equipment import normalize
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.evaluation import evaluate_configuration, evaluate_equipment, item_problems
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)
QUEST = "death_plateau"
BATCHES = {
    "batch1": (33101, 3105, 23413),
    "batch2": (19994, 21736, 7398, 7399, 23249),
    "batch3": (7400, 4101, 4103, 4111, 4113),
}
RULES = {
    33101: {},
    3105: {},
    23413: {},
    19994: {"ranged": 40},
    21736: {"defence": 50, "strength": 50},
    7398: {"defence": 20, "magic": 40},
    7399: {"defence": 20, "magic": 40},
    23249: {"ranged": 40},
    7400: {"defence": 20, "magic": 40},
    4101: {"defence": 20, "magic": 40},
    4103: {"defence": 20, "magic": 40},
    4111: {"defence": 20, "magic": 40},
    4113: {"defence": 20, "magic": 40},
}
CASES = [pytest.param(i, id=f"{batch}-{i}") for batch, ids in BATCHES.items() for i in ids]
TRADEABLE_CASES = [
    pytest.param(i, id=f"{batch}-{i}") for batch, ids in BATCHES.items() for i in ids if i != 33101
]
SOURCE_ROWS = {
    row["id"]: row
    for row in json.loads(
        Path("tests/fixtures/gear_coverage_phase2_source.json").read_text(encoding="utf-8")
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
        "phase2-synthetic",
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
    if item.id in (19994, 23249):
        return {"weapon": 857, "ammunition": 886, item.slot: item.id}, "ranged"
    if "magic" in RULES[item.id]:
        return {"weapon": 1387, item.slot: item.id}, "magic"
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
    assert item.tradeable is (item_id != 33101)
    assert normalize(source)["unsupported_effects"] == []
    if item_id != 33101:
        authored = [entry for entry in content.items.values() if entry.item_id == item_id]
        assert len(authored) == 1
        assert authored[0].variant_item_ids == ()
        assert authored[0].tier is None
        assert authored[0].price_mode == "live"
        assert authored[0].fallback_price_gp is None


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


@pytest.mark.parametrize("item_id", (3105, 23413))
@pytest.mark.parametrize(
    "state", (QuestStatus.NOT_STARTED, QuestStatus.IN_PROGRESS, QuestStatus.UNKNOWN, None)
)
def test_batch1_both_boot_forms_require_completed_death_plateau(reviewed, item_id, state):
    content, catalog = reviewed
    account = snapshot(quests={} if state is None else {QUEST: state})
    expected = "unknown" if state in (None, QuestStatus.UNKNOWN) else "unsatisfied"
    assert (
        equipment_fact(account, catalog.items[item_id], content, {}, NOW)["wear"]["status"]
        == expected
    )


def test_batch1_mooleta_postquest_drop_is_not_a_wear_gate_or_purchase(reviewed):
    content, catalog = reviewed
    item = catalog.items[33101]
    account = snapshot(levels={}, quests={})
    fact = equipment_fact(account, item, content, {33101: quote(33101)}, NOW)
    assert fact["wear"]["status"] == "satisfied"
    assert fact["acquisition"] == "untradeable"
    assert fact["price"]["amount_gp"] is None
    request = OptimizationRequest(roles=(RoleConfig(id="one", style="slash"),), mode="usable")
    assert item_problems(item.id, fact, request)


@pytest.mark.parametrize("item_id", CASES)
def test_owned_access_needs_no_price_and_unknown_ownership_stays_unknown(reviewed, item_id):
    content, catalog = reviewed
    request = OptimizationRequest(roles=(RoleConfig(id="one", style="slash"),), mode="owned")
    item = catalog.items[item_id]
    observed = equipment_fact(snapshot(owned=(item_id,)), item, content, {}, NOW)
    assert not item_problems(item_id, observed, request)
    assert observed["price"]["amount_gp"] is None
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
    assert item_problems(item_id, no_quote, request)
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


@pytest.mark.parametrize(
    "owned,other",
    (
        pytest.param(3105, 23413, id="batch1-boots-gold"),
        pytest.param(23413, 3105, id="batch1-boots-plain"),
        pytest.param(4091, 4101, id="batch3-blue-dark"),
        pytest.param(4101, 4111, id="batch3-dark-light"),
        pytest.param(4111, 4091, id="batch3-light-blue"),
    ),
)
def test_statistically_equal_variants_do_not_share_ownership_or_prices(reviewed, owned, other):
    content, catalog = reviewed
    account = snapshot(owned=(owned,))
    fact = equipment_fact(account, catalog.items[other], content, {owned: quote(owned)}, NOW)
    assert fact["ownership"]["status"] == "unknown"
    assert fact["price"]["amount_gp"] is None


def test_batch1_mooleta_cannot_accompany_a_two_handed_bow(reviewed):
    _, catalog = reviewed
    result = evaluate_equipment(
        {"weapon": 857, "ammunition": 886, "shield": 33101},
        catalog.items,
        RoleConfig(id="one", style="ranged"),
        LEVELS,
    )
    assert not result.supported
    assert any("Two-handed" in reason for reason in result.limitations)


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


@pytest.mark.parametrize("item_id", (3107, 23050, 23053, 26533))
def test_unreviewed_spiked_dusk_and_ornament_forms_remain_blocked(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    assert item.unsupported_effects
    assert not item.requirements_complete
    fact = equipment_fact(snapshot(owned=(item_id,)), item, content, {}, NOW)
    assert fact["wear"]["status"] == "unknown"
    assert fact["limitations"]


def test_batch3_enchanted_set_has_only_its_ordinary_numeric_bonuses(reviewed):
    """Independent arithmetic anchor: no invented enchanted set multiplier."""
    _, catalog = reviewed
    result = evaluate_equipment(
        {"weapon": 1387, "body": 7399, "legs": 7398, "head": 7400},
        catalog.items,
        RoleConfig(id="one", style="magic"),
        {"magic": 70},
    )
    assert result.supported
    assert result.bonuses.magic == 10 + 20 + 15 + 4 == 49
    assert result.bonuses.magic_damage == 0
    assert result.attack_roll == 81 * 113 == 9153
    assert result.defence_roll == 640
    assert result.max_hit == 8
    assert result.attack_interval == 3
    assert result.dps == pytest.approx((1 - 642 / 18308) * (4 + 1 / 9) / 3)
