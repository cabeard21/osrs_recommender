"""Independent ordering, fractional arithmetic and physical identity regressions."""

import json
from dataclasses import replace
from itertools import combinations
from types import SimpleNamespace

import pytest

from tests.gear.test_auto_disciplines import context
from tests.gear.test_prayer_search_efficiency import search
from tools.benchmark_gear_desktop import without_observations
from tracker.accounts.snapshot import ObservedItemFact
from tracker.domain.types import Container
from tracker.gear.combat import evaluate_prepared_loadout
from tracker.gear.compact_acquisition import AcquisitionFacts
from tracker.gear.compact_states import AssignmentState, EquipmentState
from tracker.gear.evaluation import purchase_cost, unowned_untradeables
from tracker.gear.execution_profile import execution_context
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig, _Search, optimize
from tracker.gear.scoring import EquipmentScorer


def test_assignment_tie_keeps_lexical_item_numbers_and_role_order():
    args = context()
    rows = [{"z": {"weapon": item}, "a": {"head": 3}} for item in (2, 10)]
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        actual = [instance.assignment_json(AssignmentState.from_mapping(row)) for row in rows]
        assert actual == [json.dumps(row, sort_keys=True) for row in rows]
        assert actual[1] < actual[0]  # JSON lexical 10 precedes 2, unlike numeric IDs.
        reverse = AssignmentState.from_mapping(dict(reversed(list(rows[0].items()))))
        assert instance.assignment_json(reverse) == actual[0]
        assert instance._assignment_json.cache_info().hits >= 1


def magic_args():
    args = list(context("magic"))
    additions = {
        item_id: EquipmentDefinition(
            id=item_id,
            name=str(item_id),
            slot=slot,
            requirements_complete=True,
            bonuses=EquipmentBonuses(magic_damage=damage),
        )
        for item_id, slot, damage in ((10, "head", 19.7), (11, "body", 0.1), (12, "legs", 0.2))
    }
    args[2] = type(args[2])(items={**args[2].items, **additions}, version="compact-fractions")
    args[0] = replace(
        args[0],
        observed_items={
            **args[0].observed_items,
            **{
                (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", args[5])
                for i in additions
            },
        },
    )
    role = RoleConfig(
        id="a", style="magic", stance="accurate", combat_options=args[1].roles[0].combat_options
    )
    args[1] = args[1].model_copy(update={"roles": (role,)})
    return args


@pytest.mark.parametrize("reverse", [False, True])
def test_fractional_magic_order_and_max_hit_match_original(reverse):
    args = magic_args()
    mapping = {"weapon": 3, "head": 10, "body": 11, "legs": 12}
    if reverse:
        mapping = dict(reversed(list(mapping.items())))
    compact = EquipmentState.from_mapping(mapping)
    # Exercise substitution's remove/reappend order, which differs from fixed slots.
    compact = compact.without_slot("head").with_slot("head", 10)
    mapping.pop("head")
    mapping["head"] = 10
    scorer = EquipmentScorer(args[2].items)
    expected = scorer.prepare(mapping)
    actual = scorer.prepare(compact)
    assert actual.equipment == expected.equipment
    assert actual._magic_terms == expected._magic_terms
    assert actual.bonuses.magic_damage == sum(expected._magic_terms)
    levels = {name: skill.level for name, skill in args[0].skills.items()}
    role = args[1].roles[0].model_copy(update={"powered_attack": "fixture"})
    reference = evaluate_prepared_loadout(expected, role, levels)
    candidate = evaluate_prepared_loadout(actual, role, levels)
    assert candidate.supported and candidate.max_hit == reference.max_hit
    assert candidate == reference


def test_fractional_magic_complete_optimizer_parity():
    args = magic_args()
    flags = {
        "_execution_profile": "combined",
        "_factored_evaluation": True,
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
        "local_refinement": True,
    }
    reference = optimize(*args, **flags)
    candidate = optimize(*args, **flags, _compact_states=True)
    assert reference["selected_solution"] is not None
    assert without_observations(candidate) == without_observations(reference)


def test_reference_counts_remove_only_last_physical_use():
    state = AssignmentState.from_mapping(
        {"a": {"weapon": 2}, "b": {"weapon": 2}, "c": {"weapon": 10}}
    )
    first = state.with_role("a", {})
    assert first.reference_counts == ((2, 1), (10, 1))
    assert first.carried == frozenset((2, 10))
    last = first.with_slot("b", "weapon", None)
    assert last.carried == frozenset((10,))
    assert last.reference_counts == ((10, 1),)
    assert state.reference_counts == ((2, 2), (10, 1))
    assert first == {"a": {}, "b": {"weapon": 2}, "c": {"weapon": 10}}
    with pytest.raises(TypeError):
        hash(state)


def test_market_alias_overwrite_preserves_physical_inventory_and_cost():
    request = SimpleNamespace(mode="upgrade", include_untradeables=True, assumed_item_ids=(5,))

    def fact(price, **extra):
        return {
            "ownership": {"status": "not_owned"},
            "price": {"amount_gp": price},
            "acquisition": "tradeable",
            **extra,
        }

    facts = {
        2: fact(100, preparation={"market_item_id": 90}),
        10: fact(200, preparation={"market_item_id": 90}),
        3: fact(300, planning_ownership={"status": "owned"}),
        4: fact(None, acquisition="untradeable"),
        5: fact(500),
        6: fact(600, budget_exempt=True),
        7: fact(None),
    }
    acquisition = AcquisitionFacts.from_facts(facts, request)
    assert acquisition.totals(frozenset((2, 10))) == (200, 0)
    state = AssignmentState.from_mapping({"a": {"weapon": 2}, "b": {"weapon": 10}})
    assert state.carried == frozenset((2, 10))  # Market aliases do not merge physical gear.
    instance = _Search.__new__(_Search)
    instance.compact_states = True
    instance._acquisition = acquisition.totals
    for size in range(len(facts) + 1):
        for subset in combinations(facts, size):
            ids = set(subset)
            expected = (
                purchase_cost(ids, facts, request),
                len(unowned_untradeables(ids, facts, request)),
            )
            assert acquisition.totals(frozenset(ids)) == expected
            assert instance.cost(ids) == expected[0]
            assert instance.untradeable_acquisitions(ids) == expected[1]
