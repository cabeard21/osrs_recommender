"""Numeric running-cost ranking retains the original resource/provenance contract."""

import json
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from tests.gear.test_running_costs import NOW, prices
from tracker.gear.compact_costs import (
    CostEvaluator,
    active,
    aggregate_numeric_cost,
    compact_running_costs,
    evaluator,
)
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.running_costs import SPELL_RECIPES, evaluate_running_cost
from tracker.gear.running_frontier import aggregate_cost


def item(i, slot="weapon", **kwargs):
    return EquipmentDefinition(id=i, name=f"Item {i}", slot=slot, **kwargs)


def assert_parity(equipment, option, records, performance=None):
    performance = performance or {"attack_interval": 2.4, "dps": 3.14159}
    reference = evaluate_running_cost(equipment, option, performance, records, NOW)
    engine = CostEvaluator(records, NOW)
    prepared = engine.prepare(equipment, option)
    numeric = prepared.score(performance.get("attack_interval"), performance.get("dps"))
    report = prepared.report(numeric)
    assert report == reference
    # Numeric equality merges 0 and 0.0; published JSON participates in ties and IDs.
    assert json.dumps(report, sort_keys=True) == json.dumps(reference, sort_keys=True)
    for field in ("status", "gp_per_attack", "gp_per_second", "gp_per_hour", "gp_per_damage"):
        assert getattr(numeric, field) == reference[field]
    with compact_running_costs():
        active_report = evaluate_running_cost(equipment, option, performance, records, NOW)
        assert active_report == reference
        assert json.dumps(active_report, sort_keys=True) == json.dumps(reference, sort_keys=True)
    _assert_deferred_report(equipment, option, records, performance, reference)
    return prepared, numeric


def _assert_deferred_report(equipment, option, records, performance, reference):
    from types import SimpleNamespace

    from tracker.gear.running_frontier import add_solution_costs
    from tracker.gear.variant_reporting import materialize

    search = SimpleNamespace(
        items={i.id: i for i in equipment.values()},
        request=SimpleNamespace(roles=(SimpleNamespace(id="a", style="ordinary", weight=0.7),)),
        running_prices=records,
        running_at=NOW,
        compact_cost_ranking=True,
    )
    solution = {
        "loadouts": {
            "a": {
                "equipment": {slot: i.id for slot, i in equipment.items()},
                "combat_option": option,
                "performance": performance,
            }
        }
    }
    with compact_running_costs():
        candidate = add_solution_costs(solution, search)
    actual = materialize(candidate)
    assert actual["loadouts"]["a"]["running_cost"] == reference
    assert json.dumps(actual["loadouts"]["a"]["running_cost"], sort_keys=True) == json.dumps(
        reference, sort_keys=True
    )
    aggregate = aggregate_cost([(0.7, reference, performance.get("dps") or 0)])
    assert actual["running_cost"] == aggregate
    assert json.dumps(actual["running_cost"], sort_keys=True) == json.dumps(
        aggregate, sort_keys=True
    )


def test_deferred_cost_factory_does_not_retain_search_or_reopen_price_context(monkeypatch):
    import weakref
    from types import SimpleNamespace

    from tracker.gear import running_costs
    from tracker.gear.running_frontier import add_solution_costs
    from tracker.gear.variant_reporting import materialize

    class Search:
        pass

    search = Search()
    search.items = {1381: item(1381)}
    search.request = SimpleNamespace(roles=(SimpleNamespace(id="mage", style="magic", weight=1),))
    search.running_prices = prices(**{"558": 3, "554": 4})
    search.running_at = NOW
    search.compact_cost_ranking = True
    solution = {
        "loadouts": {
            "mage": {
                "equipment": {"weapon": 1381},
                "combat_option": {"attack_type": "magic", "spell": "fire_strike"},
                "performance": {"supported": True, "attack_interval": 3, "dps": 2.1},
            }
        }
    }
    reference = add_solution_costs(solution, search)
    search_ref = weakref.ref(search)
    with compact_running_costs():
        candidate = add_solution_costs(solution, search)
    del search
    assert search_ref() is None

    def unexpected(*args, **kwargs):
        pytest.fail("Deferred publication reopened the resource/price context")

    monkeypatch.setattr(running_costs, "evaluate_running_cost", unexpected)
    actual = materialize(candidate)
    assert actual == reference
    assert json.dumps(actual, sort_keys=True) == json.dumps(reference, sort_keys=True)


@pytest.mark.parametrize("spell", sorted(SPELL_RECIPES))
@pytest.mark.parametrize("staff", [1381, 11998, 27788, 27676])
@pytest.mark.parametrize("missing", [False, True])
def test_all_spell_recipes_and_staff_supply(spell, staff, missing):
    records = prices(
        **{str(i): i % 37 for i in (556, 555, 557, 554, 558, 562, 560, 565, 566, 21880, 21820)}
    )
    if missing:
        records.pop(560)
        records.pop(556)
    assert_parity({"weapon": item(staff)}, {"attack_type": "magic", "spell": spell}, records)


@pytest.mark.parametrize(
    "staff", [11905, 11907, 12899, 28583, 28585, 25731, 22323, 24423, 27275, 999]
)
@pytest.mark.parametrize("missing", [False, True])
def test_powered_recipes_alternatives_and_unknowns(staff, missing):
    records = prices(
        **{str(i): i % 101 for i in (554, 557, 562, 560, 565, 566, 12934, 21820, 31111)}
    )
    if missing:
        records.pop(560)
        records.pop(565)
    assert_parity(
        {"weapon": item(staff)}, {"attack_type": "magic", "powered_attack": "fixture"}, records
    )


@pytest.mark.parametrize("cape", [None, 10499, 22109, 9756, 28947, 6570])
@pytest.mark.parametrize("body_bonus", [0, -1])
@pytest.mark.parametrize(
    "weapon,ammo",
    [(841, "arrow:882"), (9174, "bolt:877"), (841, "unknown"), (806, None), (999, None)],
)
def test_ranged_recovery_and_reviewed_resource_boundaries(cape, body_bonus, weapon, ammo):
    equipment = {
        "weapon": item(weapon, ammo_for=(ammo,) if ammo else ()),
        "body": item(1115, "body", bonuses=EquipmentBonuses(ranged=body_bonus)),
    }
    if ammo:
        equipment["ammunition"] = item(882, "ammunition", ammo_type=ammo)
    if cape:
        equipment["cape"] = item(cape, "cape")
    assert_parity(equipment, {"attack_type": "ranged"}, prices(**{"882": 10, "806": 3}))


@pytest.mark.parametrize("style", ["slash", "stab", "crush", "special", None, "magic", "ranged"])
@pytest.mark.parametrize("torag", [False, True])
def test_unknown_attack_empty_gear_and_degradation(style, torag):
    gear = {"weapon": item(4747)} if torag else {}
    assert_parity(gear, {"attack_type": style}, {})


@pytest.mark.parametrize("interval", [None, 0, -1, 1.8, 3])
@pytest.mark.parametrize("dps", [None, 0, -1, 2.91839])
def test_missing_and_zero_combat_rates(interval, dps):
    assert_parity({}, {"attack_type": "slash"}, {}, {"attack_interval": interval, "dps": dps})


def test_frozen_records_reuse_only_relevant_equipment_and_price_context(monkeypatch):
    from tracker.gear import compact_costs

    records = prices(**{"556": 5, "554": 4, "558": 3})
    engine = CostEvaluator(records, NOW)
    calls = []
    original = compact_costs.resolve_price

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(compact_costs, "resolve_price", counted)
    gear = {"weapon": item(1381)}
    option = {"attack_type": "magic", "spell": "fire_strike"}
    prepared = engine.prepare(gear, option)
    assert len(calls) == 2
    assert engine.prepare({**gear, "ring": item(2, "ring")}, option) is prepared
    assert engine.prepare(gear, {**option, "stance": "defensive"}) is prepared
    other = engine.prepare({"weapon": item(1387)}, option)
    assert other is not prepared
    assert len(calls) == 3
    with pytest.raises(FrozenInstanceError):
        prepared.gp_per_attack = 0
    with pytest.raises(FrozenInstanceError):
        prepared.resources[0].quantity = 99
    assert CostEvaluator({}, NOW).prepare(gear, option).gp_per_attack is None
    assert (
        CostEvaluator(records, NOW + timedelta(days=30)).prepare(gear, option).gp_per_attack is None
    )


def test_report_is_fresh_and_ranking_does_not_expand_provenance(monkeypatch):
    from tracker.gear.compact_costs import Resource

    engine = CostEvaluator(prices(**{"558": 3}), NOW)
    prepared = engine.prepare(
        {"weapon": item(11998)}, {"attack_type": "magic", "spell": "fire_strike"}
    )
    numeric = prepared.score(2.4, 2.3)
    first = prepared.report(numeric)
    first["resources"][0]["name"] = "changed"
    assert prepared.report(numeric)["resources"][0]["name"] != "changed"
    monkeypatch.setattr(
        Resource, "report", lambda self: pytest.fail("ranking expanded resource report")
    )
    for dps in (1.5, 2.1, 3.2):
        assert prepared.score(2.4, dps).gp_per_damage is not None


def test_numeric_aggregation_preserves_float_order_and_unknowns():
    inputs = []
    reports = []
    for weight, dps, interval in [(0.3, 2.1, 1.8), (2.7, 0.003, 2.4), (0, 0, 0)]:
        prepared, numeric = assert_parity(
            {"weapon": item(1381)},
            {"attack_type": "magic", "spell": "fire_strike"},
            prices(**{"558": 13, "554": 21}),
            {"dps": dps, "attack_interval": interval},
        )
        inputs.append((weight, numeric, dps))
        reports.append((weight, prepared.report(numeric), dps))
    for rows, rich in [(inputs, reports), ([], []), (inputs[-1:], reports[-1:])]:
        numeric = aggregate_numeric_cost(rows)
        report = aggregate_cost(rich)
        assert all(getattr(numeric, key) == report[key] for key in numeric.__dataclass_fields__)
        numeric_fields = {key: getattr(numeric, key) for key in numeric.__dataclass_fields__}
        report_fields = {key: report[key] for key in numeric.__dataclass_fields__}
        assert json.dumps(numeric_fields, sort_keys=True) == json.dumps(
            report_fields, sort_keys=True
        )


def test_context_is_nested_isolated_and_cleans_up_exceptions():
    records = prices(**{"556": 5})
    assert not active()
    with pytest.raises(RuntimeError), compact_running_costs():
        first = evaluator(records, NOW)
        assert first is evaluator(records, NOW)
        with compact_running_costs():
            assert evaluator(records, NOW) is not first
        assert evaluator(records, NOW) is first
        raise RuntimeError("test")
    assert not active()
    assert evaluator(records, NOW) is not evaluator(records, NOW)


def test_bounded_recipe_cache():
    engine = CostEvaluator({}, NOW, capacity=2)
    option = {"attack_type": "magic", "spell": "fire_strike"}
    first = engine.prepare({"weapon": item(1381)}, option)
    engine.prepare({"weapon": item(1383)}, option)
    engine.prepare({"weapon": item(1387)}, option)
    assert engine.prepare({"weapon": item(1381)}, option) is not first
    with pytest.raises(ValueError):
        CostEvaluator({}, NOW, capacity=-1)


def test_complete_frontier_parity():
    from tests.gear.test_running_frontier import mage_result
    from tools.benchmark_gear_desktop import without_observations

    reference = mage_result(secondary_priority="ranged_defence_roll")
    with compact_running_costs():
        actual = mage_result(secondary_priority="ranged_defence_roll")
    assert without_observations(actual) == without_observations(reference)


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["balanced_defence", "accuracy", "ranged_defence_roll"])
@pytest.mark.parametrize("thorough", [False, True])
def test_complete_prayer_and_potion_archives(style, priority, thorough):
    from tests.gear.test_prayer_search_efficiency import scenario
    from tools.benchmark_gear_desktop import without_observations
    from tracker.gear.optimizer import optimize
    from tracker.gear.potions import PotionPolicy
    from tracker.gear.prayers import PrayerPolicy

    args = list(
        scenario(
            style,
            PrayerPolicy(
                mode="optimize", allowed_ids=("steel_skin", "eagle_eye", "ultimate_strength")
            ),
        )
    )
    args[1] = args[1].model_copy(
        update={
            "secondary_priority": priority,
            "potions": PotionPolicy(mode="fixed", selected_ids=("ranging",)),
        }
    )
    reference = optimize(
        *args, local_refinement=thorough, _complete_frontiers=True, _running_frontier=True
    )
    with compact_running_costs():
        result = optimize(
            *args, local_refinement=thorough, _complete_frontiers=True, _running_frontier=True
        )
    assert without_observations(result) == without_observations(reference)


def test_cost_ranking_avoids_rich_reports(monkeypatch):
    import inspect

    from tests.gear.test_running_frontier import mage_result
    from tracker.gear import running_costs

    reference = running_costs.evaluate_running_cost
    calls = []

    def counted(*args, **kwargs):
        calls.append(inspect.currentframe().f_back.f_code.co_name)
        return reference(*args, **kwargs)

    monkeypatch.setattr(running_costs, "evaluate_running_cost", counted)
    mage_result()
    assert "secondary" in calls
    calls.clear()
    with compact_running_costs():
        mage_result()
    assert calls
    assert "secondary" not in calls


def test_candidate_costs_expand_only_for_ties_or_publication(monkeypatch):
    from types import SimpleNamespace

    from tracker.gear.compact_costs import Resource
    from tracker.gear.running_frontier import add_solution_costs
    from tracker.gear.variant_reporting import CompactVariant, loadout_tie, materialize

    role = SimpleNamespace(id="mage", style="magic", weight=1)
    search = SimpleNamespace(
        items={1381: item(1381)},
        request=SimpleNamespace(roles=(role,)),
        running_prices=prices(**{"558": 3, "554": 4}),
        running_at=NOW,
        compact_cost_ranking=True,
    )
    solution = {
        "loadouts": {
            "mage": {
                "equipment": {"weapon": 1381},
                "combat_option": {"attack_type": "magic", "spell": "fire_strike"},
                "performance": {"supported": True, "attack_interval": 3, "dps": 2.1},
            }
        }
    }
    reference = add_solution_costs(solution, search)
    original = Resource.report
    calls = []

    def report(resource):
        calls.append(1)
        return original(resource)

    monkeypatch.setattr(Resource, "report", report)
    with compact_running_costs():
        candidate = add_solution_costs(solution, search)
        assert isinstance(candidate, CompactVariant)
        assert not calls
        assert (
            candidate["running_cost"]["gp_per_damage"] == reference["running_cost"]["gp_per_damage"]
        )
        assert not calls
        assert loadout_tie(candidate) == loadout_tie(reference)
        assert calls
        count = len(calls)
        assert materialize(candidate) == reference
        assert len(calls) == count


def test_deferred_cost_candidate_preserves_inert_magic_ammunition_cleanup():

    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.facts import equipment_fact
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search, _solution_key
    from tracker.gear.refinement import _no_worse, refine_ammunition
    from tracker.gear.variant_reporting import CompactVariant, materialize

    class DeferredCostSearch(_Search):
        compact_cost_ranking = True

    gear = {
        1381: item(1381, attack_styles=("magic",), requirements_complete=True),
        882: item(
            882,
            "ammunition",
            ammo_type="arrow:882",
            requirements_complete=True,
            bonuses=EquipmentBonuses(ranged_strength=7),
        ),
    }
    snapshot = AccountSnapshot(
        1,
        "cost-refinement",
        skills={
            k: SkillState(70, None, Source.MANUAL, NOW)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in gear
        },
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="mage", style="magic", spell="fire_strike"),),
        mode="owned",
        max_swaps=0,
        secondary_priority="accuracy",
    )
    records = prices(**{"558": 3, "554": 4})
    facts = {i: equipment_fact(snapshot, row, Content(), records, NOW) for i, row in gear.items()}
    search = DeferredCostSearch(snapshot, request, gear, facts, None)
    search.running_prices, search.running_at = records, NOW
    original = search.solution({"mage": {"weapon": 1381, "ammunition": 882}}, None)
    assert original is not None
    with compact_running_costs():
        candidate = search.solution({"mage": {"weapon": 1381}}, None)
        assert isinstance(candidate, CompactVariant)
        assert _no_worse(original, candidate)
        diagnostics = {"evaluated_assignments": 0, "improved_finalists": 0}
        refined = materialize(refine_ammunition(search, original, _solution_key, diagnostics))
    assert "ammunition" not in refined["loadouts"]["mage"]["equipment"]
    assert diagnostics == {"evaluated_assignments": 1, "improved_finalists": 1}
