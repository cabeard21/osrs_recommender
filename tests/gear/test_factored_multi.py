"""Numeric Multi partial ranking retains physical assignments and complete archives."""

from dataclasses import replace
from itertools import product
from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import weapon
from tests.gear.test_prayer_search_efficiency import scenario, search
from tools.benchmark_gear_desktop import without_observations
from tracker.accounts.snapshot import ObservedItemFact
from tracker.domain.types import Container
from tracker.gear.combat import evaluate_loadout
from tracker.gear.execution_profile import execution_context
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig, optimize
from tracker.gear.prayers import PrayerPolicy


def multi_case(configured=False, special=False, priority="balanced_defence"):
    args = list(
        scenario("slash", PrayerPolicy(mode="optimize", allowed_ids=("sharp_eye", "piety")))
    )
    items = [
        weapon(1, "slash", 30, attack_profiles=(("slash", "accurate"), ("slash", "defensive"))),
        weapon(2, "ranged", 30, attack_profiles=(("ranged", "rapid"), ("ranged", "longrange"))),
        EquipmentDefinition(
            id=10,
            name="Melee helm",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(melee_strength=40, defence_magic=15),
        ),
        EquipmentDefinition(
            id=20,
            name="Ranged helm",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(ranged_strength=40, defence_ranged=30),
        ),
    ]
    first = args[1].roles[0].model_copy(update={"locks": {"weapon": 1}})
    second = first.model_copy(
        update={
            "id": "b",
            "style": "ranged",
            "stance": "rapid",
            "locks": {"weapon": 2},
            "weight": 2,
        }
    )
    roles = (first, second)
    if not configured:
        roles = tuple(
            r.model_copy(update={"combat_options": None, "prayers": PrayerPolicy()}) for r in roles
        )
    if special:
        roles += (RoleConfig(id="s", style="special", parent_role="a", locks={"weapon": 2}),)
    args[0] = replace(
        args[0],
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", args[5])
            for i in items
        },
    )
    args[1] = args[1].model_copy(
        update={
            "roles": roles,
            "max_swaps": 3,
            "secondary_priority": priority,
            "reserved_supply_slots": 25,
        }
    )
    args[2] = SimpleNamespace(items={i.id: i for i in items}, version="test")
    return args


@pytest.mark.parametrize("configured", [False, True])
def test_multi_partial_score_defers_reporting_only_in_factored_context(monkeypatch, configured):
    args = multi_case(configured)
    with execution_context("combined", args[1], fixed_reporting=True, factored_evaluation=True):
        instance = search(args)
        role = args[1].roles[0]
        equipment = {"weapon": 1, "head": 10}
        expected = instance.performance(equipment, role)
        instance.performance_cache.clear()

        def unexpected(*args, **kwargs):
            pytest.fail("Multi partial ranking constructed a rich combat report")

        monkeypatch.setattr("tracker.gear.optimizer.evaluate_prepared_loadout", unexpected)
        compact = instance.search_performance(equipment, role)
        assert compact["dps"] == expected["dps"]
        assert compact["supported"] == expected["supported"]
        assert not instance.performance_cache


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("priority", ["balanced_defence", "accuracy", "magic_ranged_defence_roll"])
@pytest.mark.parametrize("special", [False, True])
def test_multi_complete_curve_and_archives_match(configured, priority, special):
    args = multi_case(configured, special, priority)
    options = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
    }
    expected = optimize(*args, **options)
    actual = optimize(*args, **options, _factored_evaluation=True)
    assert without_observations(actual) == without_observations(expected)


def test_factored_multi_matches_small_exhaustive_assignments():
    args = multi_case()
    result = optimize(
        *args,
        _execution_profile="combined",
        _fixed_reporting=True,
        _factored_evaluation=True,
        _complete_frontiers=True,
        _running_frontier=True,
    )
    levels = {key: value.level for key, value in args[0].skills.items()}
    roles = args[1].roles
    for limit in (1, 2):
        scores = []
        for head_a, head_b in product((None, 10, 20), repeat=2):
            if 1 + (head_a != head_b) > limit:
                continue
            equipment = [{"weapon": args[2].items[1]}, {"weapon": args[2].items[2]}]
            for setup, head in zip(equipment, (head_a, head_b), strict=True):
                if head is not None:
                    setup["head"] = args[2].items[head]
            scores.append(
                sum(
                    evaluate_loadout(e, r, levels).dps * r.weight
                    for e, r in zip(equipment, roles, strict=True)
                )
                / 3
            )
        assert result["curve"][limit]["solution"]["score"] == max(scores)


@pytest.mark.parametrize(
    "profile,factored", [("baseline", True), ("combined", False), ("lazy", True)]
)
def test_other_profiles_keep_original_multi_reporting(profile, factored):
    args = multi_case(True)
    with execution_context(profile, args[1], fixed_reporting=True, factored_evaluation=factored):
        instance = search(args)
        role = args[1].roles[0]
        assert not instance.lazy_eligible(role)
        assert not instance.fixed_eligible(role)
        instance.performance_cache.clear()
        report = instance.search_performance({"weapon": 1}, role)
        assert "attack_roll" in report


def test_multi_numeric_ranking_preserves_actual_node_budget(monkeypatch):
    monkeypatch.setattr("tracker.gear.optimizer.MAX_EXPANSIONS", 100)
    args = multi_case(True)
    options = {"_execution_profile": "combined", "_fixed_reporting": True}
    expected = optimize(*args, **options)
    actual = optimize(*args, **options, _factored_evaluation=True)
    assert actual["search"]["explored_nodes"] == 100
    assert without_observations(actual) == without_observations(expected)


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("single,special", [(True, False), (False, False), (False, True)])
def test_factored_candidate_pools_and_retained_loadouts_need_no_reports(
    monkeypatch, configured, single, special
):
    args = multi_case(configured, special)
    if single:
        args[1] = args[1].model_copy(update={"roles": args[1].roles[:1]})
    reference = search(args)
    expected = {r.id: reference.loadouts((r,)) for r in args[1].roles}

    def unexpected(*args, **kwargs):
        pytest.fail("Candidate ranking and equipment retention need only numeric combat scores")

    monkeypatch.setattr("tracker.gear.optimizer.evaluate_prepared_loadout", unexpected)
    with execution_context("combined", args[1], fixed_reporting=True, factored_evaluation=True):
        instance = search(args)
        assert instance.pools == reference.pools
        assert instance.marginals == reference.marginals
        assert instance.secondary_marginals == reference.secondary_marginals
        assert {r.id: instance.loadouts((r,)) for r in args[1].roles} == expected
