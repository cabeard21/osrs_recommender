"""Exact-ID reviewed coverage, independent physical inputs and ordinary references.

Wear rules are transcribed from item-specific Wiki evidence linked in the authored
overlay. Raw statistics come from the separate pinned source-shaped test fixture.
No synthetic approval is installed into the real catalog by these tests.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.import_equipment import normalize
from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.coverage_audit import audit_snapshot
from tracker.gear.evaluation import evaluate_configuration, evaluate_equipment, item_problems
from tracker.gear.facts import equipment_fact
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)
QUEST = "the_fremennik_trials"
BATCHES = {
    "batch1": (882, 886, 1387),
    "batch2": (1077, 1125, 1165, 1201, 857),
    "batch3": (1017, 2579, 3753, 3755),
    "batch4": (6809, 10564, 10589, 21643),
}
RULES = {
    882: {},
    886: {"ranged": 5},
    1387: {},
    1077: {"defence": 10},
    1125: {"defence": 10},
    1165: {"defence": 10},
    1201: {"defence": 40},
    857: {"ranged": 40},
    1017: {},
    2579: {"magic": 20},
    3753: {"defence": 45},
    3755: {"defence": 45},
    6809: {"defence": 50, "strength": 50},
    10564: {"defence": 50, "strength": 50},
    10589: {"defence": 50, "strength": 50},
    21643: {"defence": 50, "strength": 50},
}
CASES = [pytest.param(i, id=f"{batch}-{i}") for batch, ids in BATCHES.items() for i in ids]
SOURCE_ROWS = {
    row["id"]: row
    for row in json.loads(
        Path("tests/fixtures/gear_coverage_phase1_source.json").read_text(encoding="utf-8")
    )["rows"]
}


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


def snapshot(*, levels=None, owned=(), quests=None, complete_scans=False):
    return AccountSnapshot(
        1,
        "phase1-synthetic",
        skills={
            key: SkillState(value, None, Source.MANUAL, NOW)
            for key, value in (
                levels
                if levels is not None
                else dict.fromkeys(("attack", "strength", "defence", "magic", "ranged"), 70)
            ).items()
        },
        quests={QUEST: QuestStatus.COMPLETE} if quests is None else quests,
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "test", NOW)
            for i in owned
        },
        container_scans={c: ContainerScanFact(c, NOW, "test") for c in Container}
        if complete_scans
        else {},
    )


@pytest.mark.parametrize("item_id", CASES)
def test_reviewed_physical_identity_requirements_and_full_statistics(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    source = SOURCE_ROWS[item_id]
    assert item.id == source["id"]
    assert item.name == source["name"]
    assert item.slot == ("ammunition" if source["slot"] == "ammo" else source["slot"])
    assert item.two_handed == source["isTwoHanded"]
    assert item.attack_speed == max(1, source["speed"])
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
    assert item.tradeable is True
    authored = [entry for entry in content.items.values() if entry.item_id == item_id]
    assert len(authored) == 1
    assert authored[0].tier is None
    assert authored[0].variant_item_ids == ()
    assert authored[0].price_mode == "live"
    assert normalize(source)["unsupported_effects"] == []


@pytest.mark.parametrize("item_id", CASES)
def test_wear_boundaries_and_unknown_account_facts(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    rules = RULES[item_id]
    for delta in (0, 1):
        account = snapshot(levels={key: value + delta for key, value in rules.items()})
        assert equipment_fact(account, item, content, {}, NOW)["wear"]["status"] == "satisfied"
    if not rules:
        assert (
            equipment_fact(snapshot(levels={}), item, content, {}, NOW)["wear"]["status"]
            == "satisfied"
        )
    for skill, required in rules.items():
        below = snapshot(levels={**rules, skill: required - 1})
        missing = snapshot(levels={key: value for key, value in rules.items() if key != skill})
        assert equipment_fact(below, item, content, {}, NOW)["wear"]["status"] == "unsatisfied"
        assert equipment_fact(missing, item, content, {}, NOW)["wear"]["status"] == "unknown"


@pytest.mark.parametrize("item_id", (3753, 3755), ids=("batch3-3753", "batch3-3755"))
@pytest.mark.parametrize(
    "state", (QuestStatus.NOT_STARTED, QuestStatus.IN_PROGRESS, QuestStatus.UNKNOWN, None)
)
def test_fremennik_quest_is_a_wear_gate_not_an_acquisition_assumption(reviewed, item_id, state):
    content, catalog = reviewed
    account = snapshot(quests={} if state is None else {QUEST: state})
    expected = "unknown" if state in (None, QuestStatus.UNKNOWN) else "unsatisfied"
    assert (
        equipment_fact(account, catalog.items[item_id], content, {}, NOW)["wear"]["status"]
        == expected
    )


@pytest.mark.parametrize("item_id", CASES)
def test_owned_only_and_purchase_access_preserve_unknowns(reviewed, item_id):
    content, catalog = reviewed
    owned_request = OptimizationRequest(roles=(RoleConfig(id="one", style="crush"),), mode="owned")
    buy_request = owned_request.model_copy(update={"mode": "usable", "budget_gp": 100})
    item = catalog.items[item_id]
    observed = equipment_fact(snapshot(owned=(item_id,)), item, content, {}, NOW)
    assert not item_problems(item_id, observed, owned_request)
    assert observed["price"]["amount_gp"] is None
    unknown = equipment_fact(snapshot(), item, content, {}, NOW)
    assert unknown["ownership"]["status"] == "unknown"
    assert item_problems(item_id, unknown, owned_request)
    assert item_problems(item_id, unknown, buy_request)
    quote = SimpleNamespace(
        item_id=item_id,
        high_price_gp=100,
        high_trade_at=NOW,
        low_price_gp=90,
        low_trade_at=NOW,
        fetched_at=NOW,
        source="live",
    )
    priced = equipment_fact(snapshot(), item, content, {item_id: quote}, NOW)
    assert not item_problems(item_id, priced, buy_request)
    assert priced["ownership"]["status"] == "unknown"
    assert priced["price"]["amount_gp"] == 100
    stale = SimpleNamespace(
        **{
            **vars(quote),
            "high_trade_at": NOW - timedelta(days=31),
            "low_trade_at": NOW - timedelta(days=31),
        }
    )
    old = equipment_fact(snapshot(), item, content, {item_id: stale}, NOW)
    assert old["price"]["layer"] == "cached"


@pytest.mark.parametrize("item_id", CASES)
def test_each_reviewed_item_has_a_supported_ordinary_scaffold(reviewed, item_id):
    _, catalog = reviewed
    item = catalog.items[item_id]
    if item_id in (857, 882, 886):
        equipment = {
            "weapon": 857 if item_id == 857 else 843,
            "ammunition": 886 if item_id == 857 else item_id,
        }
        role = RoleConfig(id="one", style="ranged")
    elif item_id in (1017, 2579, 3755, 1387):
        equipment = {"weapon": 1387, item.slot: item_id}
        role = RoleConfig(id="one", style="magic")
    else:
        equipment = {"weapon": 1333, item.slot: item_id}
        role = RoleConfig(id="one", style="slash")
    result = evaluate_equipment(
        equipment,
        catalog.items,
        role,
        dict.fromkeys(("attack", "strength", "defence", "magic", "ranged"), 70),
    )
    assert result.supported
    assert result.dps > 0
    wrong_slot = {"ring": item_id}
    assert not evaluate_equipment(wrong_slot, catalog.items, role, {"magic": 70}).supported


def test_batch2_yew_requires_exact_ordinary_ammunition_and_two_hands(reviewed):
    _, catalog = reviewed
    item = catalog.items[857]
    expected = tuple(f"arrow:{i}" for i in (882, 884, 886, 888, 890, 892))
    assert item.ammo_for == expected
    assert normalize(SOURCE_ROWS[857])["ammo_for"] == expected
    assert item.attack_profiles == tuple(("ranged", s) for s in ("accurate", "rapid", "longrange"))
    role = RoleConfig(id="one", style="ranged")
    for equipment, reason in (
        ({"weapon": 857}, "Compatible ammunition"),
        ({"weapon": 857, "ammunition": 9140}, "Compatible ammunition"),
        ({"weapon": 857, "ammunition": 886, "shield": 1201}, "Two-handed"),
    ):
        result = evaluate_equipment(equipment, catalog.items, role, {"ranged": 70})
        assert not result.supported
        assert any(reason in value for value in result.limitations)


@pytest.mark.parametrize("stance,speed", (("accurate", 2.4), ("rapid", 1.8), ("longrange", 2.4)))
def test_batch2_yew_full_ranged_reference_and_defence_subtype(reviewed, stance, speed):
    _, catalog = reviewed
    role = RoleConfig(
        id="one",
        style="ranged",
        stance=stance,
        target=CombatTarget(
            defence_level=10, ranged_light=400, ranged_standard=20, ranged_heavy=700
        ),
    )
    result = evaluate_equipment(
        {
            "weapon": 857,
            "ammunition": 886,
            "head": 1169,
            "body": 1129,
            "legs": 1095,
            "hands": 1059,
            "feet": 1061,
            "neck": 1731,
            "cape": 1019,
        },
        catalog.items,
        role,
        {"ranged": 60},
    )
    assert result.supported
    assert result.bonuses.ranged_strength == 16
    # Yew + coif + body + chaps + gloves + boots + power amulet + cape.
    assert result.bonuses.ranged == 47 + 2 + 2 + 4 + 0 + 0 + 6 + 0 == 61
    stance_bonus = 3 if stance == "accurate" else 0
    assert result.max_hit == (320 + (60 + 8 + stance_bonus) * 80) // 640
    assert result.attack_roll == (60 + 8 + stance_bonus) * (61 + 64)
    assert result.defence_roll == 19 * 84
    assert result.attack_interval == pytest.approx(speed)


@pytest.mark.parametrize(
    "style,stance",
    (
        ("crush", "accurate"),
        ("crush", "aggressive"),
        ("crush", "defensive"),
        ("magic", "accurate"),
        ("magic", "defensive"),
    ),
)
def test_batch1_fire_staff_legal_ordinary_profiles(reviewed, style, stance):
    _, catalog = reviewed
    result = evaluate_equipment(
        {"weapon": 1387},
        catalog.items,
        RoleConfig(id="one", style=style, stance=stance),
        {"attack": 50, "strength": 50, "magic": 50},
    )
    assert result.supported
    assert result.attack_interval == 3.0
    if style == "magic":
        assert result.max_hit == 8
        assert result.attack_roll == (59 + (2 if stance == "accurate" else 0)) * 74
    else:
        assert result.attack_roll == (58 + (3 if stance == "accurate" else 0)) * 73
        assert result.max_hit == (320 + (58 + (3 if stance == "aggressive" else 0)) * 70) // 640


def test_batch1_staff_spell_level_and_illegal_cast_stance_stay_blocked(reviewed):
    _, catalog = reviewed
    for magic, stance in ((12, "accurate"), (50, "aggressive")):
        result = evaluate_equipment(
            {"weapon": 1387},
            catalog.items,
            RoleConfig(id="one", style="magic", stance=stance),
            {"magic": magic},
        )
        assert not result.supported


def test_batch4_granite_body_does_not_invent_shop_or_slayer_wear_requirements(reviewed):
    content, catalog = reviewed
    account = snapshot(levels={"defence": 50, "strength": 50}, quests={})
    for item_id in BATCHES["batch4"]:
        assert (
            equipment_fact(account, catalog.items[item_id], content, {}, NOW)["wear"]["status"]
            == "satisfied"
        )


def test_batch4_complete_melee_loadout_has_independent_ordinary_reference(reviewed):
    _, catalog = reviewed
    equipment = {
        "weapon": 1333,
        "head": 1165,
        "body": 1125,
        "legs": 1077,
        "shield": 1201,
        "feet": 21643,
        "neck": 1725,
        "hands": 1059,
        "cape": 1019,
    }
    result = evaluate_equipment(
        equipment,
        catalog.items,
        RoleConfig(id="one", style="slash"),
        {"attack": 59, "strength": 59},
    )
    assert result.supported
    assert result.bonuses.melee_strength == 44 + 10 + 3 == 57
    assert result.bonuses.slash == 45
    assert result.max_hit == 13
    assert result.attack_roll == 70 * 109 == 7630
    assert result.defence_roll == 640
    accuracy = 1 - 642 / 15262
    assert result.accuracy == pytest.approx(accuracy)
    assert result.dps == pytest.approx(accuracy * (6.5 + 1 / 14) / 2.4)


def test_batch3_complete_magic_loadout_has_independent_ordinary_reference(reviewed):
    _, catalog = reviewed
    equipment = {
        "weapon": 1387,
        "head": 3755,
        "feet": 2579,
        "body": 577,
        "legs": 1033,
        "neck": 1727,
        "cape": 1019,
    }
    result = evaluate_equipment(
        equipment, catalog.items, RoleConfig(id="one", style="magic"), {"magic": 50}
    )
    assert result.supported
    assert result.bonuses.magic == 10 + 6 + 4 + 3 + 2 + 10 == 35
    assert result.bonuses.magic_damage == 0
    assert result.max_hit == 8
    assert result.attack_roll == 61 * 99 == 6039
    assert result.defence_roll == 640
    accuracy = 1 - 642 / 12080
    assert result.dps == pytest.approx(accuracy * (4 + 1 / 9) / 3)


def test_nonbatch_definitions_and_unreviewed_variants_are_unchanged(reviewed):
    content, _ = reviewed
    # This historical physical/approved-metadata guard predates partial bulk gates.
    catalog = load_catalog(content, use_requirements_source=False)
    # Phase 2 independently tests these exact forms against its pinned raw fixture.
    # High-impact forms are independently tested too. Digest recomputed from the
    # frozen pre-high-impact catalog, after verifying its original digest.
    phase2 = {33101, 3105, 23413, 19994, 21736, 7398, 7399, 23249, 7400, 4101, 4103, 4111, 4113}
    high_impact = {7460, 7459, 7458, 29280, 29286, 29289, 2501, 2495, 6733, 2577}
    payload = {
        i: v.model_dump(
            mode="json",
            exclude={
                "spell_compatibility",
                "powered_attack",
                "powered_attack_base_max_hit",
                "powered_attack_stances",
            },
        )
        for i, v in catalog.items.items()
        if i not in RULES and i not in phase2 and i not in high_impact
    }
    # Source-pinned bulk tests independently cover these 23 exact approvals:
    # chainbodies (7), full helms (3), kiteshields (8), platebodies (3), legs (2).
    # Verified against HEAD: only their generic effect markers changed physically.
    # Restore only approved metadata; retain the original digest so every physical
    # field and every item outside this explicit allowlist remain protected.
    bulk_approved = (
        1101,
        1103,
        1105,
        1107,
        1109,
        1111,
        1113,
        1155,
        6623,
        11335,
        1189,
        1191,
        1193,
        1195,
        1197,
        1199,
        6633,
        21895,
        1117,
        6617,
        21892,
        1075,
        6625,
    )
    for item_id in bulk_approved:
        payload[item_id] = {
            **payload[item_id],
            "requires": None,
            "requirements_complete": False,
            "tradeable": None,
            "content_ids": [],
            "unsupported_effects": ["Offensive effects have not been validated."],
        }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == "e6872e89c7e99f756e1ff03fec15c492ce65201954c0c1ba8b4f3ac699d085fc"
    for variant in (883, 887, 2591, 2583, 12453, 12455, 33565):
        item = catalog.items.get(variant)
        if item is not None:
            assert item.unsupported_effects
            assert not item.requirements_complete


def test_batch2_purchase_budget_and_exact_physical_ownership(reviewed):
    content, catalog = reviewed
    item = catalog.items[857]
    role = RoleConfig(id="one", style="ranged")
    request = OptimizationRequest(roles=(role,), mode="usable", budget_gp=99)
    account = snapshot(owned=(886,))
    quote = SimpleNamespace(
        item_id=857,
        high_price_gp=100,
        high_trade_at=NOW,
        low_price_gp=90,
        low_trade_at=NOW,
        fetched_at=NOW,
        source="live",
    )
    facts = {
        i: equipment_fact(account, catalog.items[i], content, {857: quote}, NOW) for i in (857, 886)
    }
    result = evaluate_configuration(
        {"weapon": 857, "ammunition": 886}, catalog.items, facts, request, role, {"ranged": 70}
    )
    assert result["status"] == "invalid"
    assert result["purchase_cost_gp"] == 100
    assert result["purchases"] == [{"item_id": 857, "cost_gp": 100, "conditional": True}]
    assert (
        equipment_fact(snapshot(owned=(858,)), item, content, {}, NOW)["ownership"]["status"]
        == "unknown"
    )
    assert (
        evaluate_configuration(
            {"weapon": 857, "ammunition": 886},
            catalog.items,
            facts,
            request.model_copy(update={"budget_gp": 100}),
            role,
            {"ranged": 70},
        )["status"]
        == "valid"
    )


@pytest.mark.parametrize(
    "style,ids,locks",
    (
        ("slash", (1333, 1077, 1125, 1165, 1201, 21643, 1725, 1059, 1019, 1635), {"shield": 1201}),
        ("ranged", (857, 886, 1169, 1129, 1095, 1059, 1061, 1731, 1019), {"weapon": 857}),
        ("magic", (1387, 1017, 2579, 577, 1033, 1727, 1019), {"weapon": 1387}),
    ),
)
def test_completed_loadouts_optimize_after_review_without_search_changes(
    reviewed, style, ids, locks
):
    content, catalog = reviewed
    account = snapshot(owned=ids)
    role = RoleConfig(id="one", style=style)
    request = OptimizationRequest(roles=(role,), mode="owned", locks=locks, max_swaps=0)
    answer = optimize(account, request, catalog, content, {}, NOW)
    assert answer["search"]["quality"] == "best_found"
    solution = answer["selected_solution"]
    assert solution is not None
    loadout = solution["loadouts"]["one"]
    exact = evaluate_equipment(
        loadout["equipment"],
        catalog.items,
        role,
        dict.fromkeys(("attack", "strength", "defence", "magic", "ranged"), 70),
    )
    assert exact.supported
    assert loadout["performance"] == exact.model_dump(mode="json")
    assert solution["purchase_cost_gp"] == 0
    # Undo only this batch's reviews in immutable copies: a locked new item becomes unavailable.
    before = EquipmentCatalog(
        {
            i: v.model_copy(update={"requirements_complete": False}) if i in RULES else v
            for i, v in catalog.items.items()
        }
    )
    baseline = optimize(account, request, before, content, {}, NOW)
    assert baseline["selected_solution"] is None


def test_expanded_ordinary_heads_expose_repeatable_retention_without_policy_changes(reviewed):
    """Pool omission is measured directly; it is not proof of a lost global optimum."""
    content, catalog = reviewed
    heads = (1017, 1163, 1165, 1169, 3749, 3751, 3753, 3755, 4089, 6326, 10828, 13385, 10589)
    account = snapshot(
        owned=(*heads, 1333),
        complete_scans=True,
        quests=dict.fromkeys((QUEST, "the_fremennik_isles"), QuestStatus.COMPLETE),
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="slash", style="slash"),), mode="owned", max_swaps=0
    )
    first = audit_snapshot(account, content, catalog, {}, NOW, (request,))
    assert first == audit_snapshot(account, content, catalog, {}, NOW, (request,))
    pool = first["scenarios"][0]["pools"]["head"]
    assert len(pool) == 12
    assert None in pool
    eligible = [
        row
        for row in first["items"]
        if row["item_id"] in heads and row["scenario_results"][0]["initial_eligible"]
    ]
    assert len(eligible) == 13
    omitted = [
        row for row in eligible if row["scenario_results"][0]["candidate_retention"] == "omitted"
    ]
    assert len(omitted) == 2
    for row in omitted:
        assert row["fully_supported"]
        assert row["item_id"] not in pool
        assert row["scenario_results"][0]["later_search"] == "not_measured"
        exact = evaluate_equipment(
            {"weapon": 1333, "head": row["item_id"]},
            catalog.items,
            request.roles[0],
            {"attack": 70, "strength": 70},
        )
        assert exact.supported
