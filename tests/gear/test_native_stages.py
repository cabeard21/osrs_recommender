"""Native stage comparisons use the existing Python search as the oracle."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.compact_costs import CostEvaluator, aggregate_numeric_cost
from tracker.gear.execution_profile import execution_context
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import (
    CombatOptionFilters,
    OptimizationRequest,
    RoleConfig,
    _Search,
    prepare_optimization,
)

ScoringContext = pytest.importorskip("tracker.gear.native._scoring").ScoringContext
StageContext = pytest.importorskip("tracker.gear.native._stages").StageContext


@contextmanager
def stage_search(*, multiple=False, include_untradeables=False):
    now = datetime(2026, 11, 12, tzinfo=UTC)
    items = (
        [
            EquipmentDefinition(
                id=i,
                name=str(i),
                slot="weapon",
                attack_styles=("slash", "crush"),
                attack_profiles=(
                    ("slash", "accurate"),
                    ("slash", "aggressive"),
                    ("crush", "defensive"),
                ),
                requirements_complete=True,
                bonuses=EquipmentBonuses(melee_strength=5 if i == 10 else 0),
                two_handed=i == 100,
            )
            for i in (2, 10, 100)
        ]
        + [
            EquipmentDefinition(
                id=i,
                name=str(i),
                slot="head",
                requirements_complete=True,
                bonuses=EquipmentBonuses(defence_stab=i % 5, melee_strength=i % 3),
            )
            for i in range(201, 225)
        ]
        + [EquipmentDefinition(id=300, name="Shield", slot="shield", requirements_complete=True)]
    )
    role = RoleConfig(
        id="z",
        style="slash",
        combat_options=CombatOptionFilters(
            attack_types=("slash", "crush"),
            stances=("accurate", "aggressive", "defensive"),
            spells=(),
        ),
    )
    roles = (role, role.model_copy(update={"id": "a"})) if multiple else (role,)
    request = OptimizationRequest(
        roles=roles,
        mode="owned",
        max_swaps=2,
        secondary_priority="balanced_defence",
        include_untradeables=include_untradeables,
    )
    snapshot = AccountSnapshot(
        1,
        "native-test",
        skills={
            name: SkillState(70, None, Source.MANUAL, now)
            for name in ("attack", "strength", "ranged", "defence", "magic", "prayer")
        },
        observed_items={
            (item.id, Container.BANK): ObservedItemFact(item.id, Container.BANK, 1, "test", now)
            for item in items
        },
    )
    catalog = SimpleNamespace(items={item.id: item for item in items}, version="native-test")
    prepared = prepare_optimization(snapshot, request, catalog, Content(), {}, now)
    with execution_context(
        "combined", request, fixed_reporting=True, factored_evaluation=True, compact_states=True
    ):
        search = _Search(
            prepared.snapshot,
            request,
            prepared.catalog.items,
            prepared.facts,
            None,
            prepared.eligible,
        )
        yield search


def drain(expansion, limit, chunk=1024):
    consumed = 0
    while not expansion.done:
        consumed += expansion.advance(chunk)
    return expansion.finish(limit), consumed


def test_native_expansion_preserves_original_equipment_insertion_order():
    with stage_search() as search:
        actual, _ = drain(
            StageContext(ScoringContext(search), search).begin(
                kind="loadout",
                states=[{"head": 201, "weapon": 2}],
                choices=[300],
                slot="shield",
                roles=("z",),
            ),
            8,
        )
        assert list(actual[0]) == ["head", "weapon", "shield"]


def test_native_cost_lane_unavailable_recipe_does_not_change_dps_retention():
    with stage_search() as search:
        search.native_cost_objective = True
        search.running_prices = {}
        search.running_at = datetime(2026, 11, 12, tzinfo=UTC)
        context = StageContext(ScoringContext(search), search)
        actual, _ = drain(
            context.begin(
                kind="loadout", states=[{}], choices=[2, 10, 100], slot="weapon", roles=("z",)
            ),
            8,
        )
        assert actual[0] == {"weapon": 10}


def test_special_roles_do_not_reject_otherwise_legal_native_joint_states():
    with stage_search(multiple=True) as search:
        first, second = search.request.roles
        second = second.model_copy(
            update={"style": "special", "parent_role": first.id, "locks": {"weapon": 2}}
        )
        search.request = search.request.model_copy(update={"roles": (first, second)})
        context = StageContext(ScoringContext(search), search)
        actual, _ = drain(
            context.begin(
                kind="joint",
                states=[{"z": {"weapon": 2}, "a": {"weapon": 2}}],
                choices=[[201], [201]],
                slot="head",
                roles=("z", "a"),
            ),
            8,
        )
        assert len(actual) == 1


@pytest.mark.parametrize("metric", [False, True])
def test_native_running_cost_rank_matches_python_hourly_aggregation(metric):
    with stage_search() as search:
        now = datetime(2026, 11, 12, tzinfo=UTC)
        original = search.items[2]
        search.items = {
            item_id: original.model_copy(
                update={
                    "id": item_id,
                    "attack_styles": ("ranged",),
                    "attack_profiles": (),
                    "bonuses": EquipmentBonuses(ranged=40, ranged_strength=strength),
                }
            )
            for item_id, strength in ((806, 1), (807, 25))
        }
        search.facts = dict.fromkeys(search.items, search.facts[2])
        search.eligible = set(search.items)
        role = RoleConfig(id="z", style="ranged", stance="rapid")
        search.request = search.request.model_copy(update={"roles": (role,)})
        search.running_at = now
        search.running_prices = {
            item_id: SimpleNamespace(
                high_price_gp=price,
                high_trade_at=now,
                low_price_gp=None,
                low_trade_at=None,
                fetched_at=now,
                source="live",
            )
            for item_id, price in ((806, 3), (807, 100))
        }
        search.native_cost_objective = True
        scorer = ScoringContext(search)
        engine = CostEvaluator(search.running_prices, now)

        def key(equipment):
            performance = scorer.score(equipment, 0, metric)
            recipe = engine.prepare(
                {slot: search.items[item] for slot, item in equipment.items()},
                {"attack_type": "ranged"},
            )
            numeric = recipe.score(performance["interval"], performance["dps"])
            aggregate = aggregate_numeric_cost([(role.weight, numeric, performance["dps"])])
            rank = (-performance["dps"], aggregate.gp_per_damage)
            return (rank[1], rank[0]) if metric else rank

        expected = sorted([{"weapon": 806}, {"weapon": 807}], key=key)
        actual, _ = drain(
            StageContext(scorer, search).begin(
                kind="loadout",
                states=[{}],
                choices=[806, 807],
                slot="weapon",
                roles=("z",),
                metric=metric,
            ),
            8,
        )
        assert actual == expected


@pytest.mark.parametrize("interference,repair", [(False, False), (True, False), (False, True)])
def test_native_ranged_recovery_and_unavailable_cost_ranking(interference, repair):
    with stage_search() as search:
        now = datetime(2026, 11, 12, tzinfo=UTC)
        bow = search.items[2].model_copy(
            update={
                "attack_styles": ("ranged",),
                "attack_profiles": (),
                "ammo_for": ("arrow:test",),
                "bonuses": EquipmentBonuses(ranged=40, ranged_strength=25),
            }
        )
        items = [
            bow,
            EquipmentDefinition(id=3, name="Arrow", slot="ammunition", ammo_type="arrow:test"),
            EquipmentDefinition(id=10498, name="Known recovery", slot="cape"),
            EquipmentDefinition(id=9756, name="Unknown recovery", slot="cape"),
            EquipmentDefinition(
                id=50, name="Interfering body", slot="body", bonuses=EquipmentBonuses(ranged=-10)
            ),
            EquipmentDefinition(id=4747, name="Repair limitation", slot="head"),
        ]
        search.items = {item.id: item for item in items}
        search.facts = dict.fromkeys(search.items, search.facts[2])
        search.eligible = set(search.items)
        role = RoleConfig(id="z", style="ranged", stance="rapid")
        search.request = search.request.model_copy(update={"roles": (role,)})
        search.running_at = now
        search.running_prices = {
            3: SimpleNamespace(
                high_price_gp=7,
                high_trade_at=now,
                low_price_gp=None,
                low_trade_at=None,
                fetched_at=now,
                source="live",
            ),
        }
        search.native_cost_objective = True
        base = {
            "weapon": 2,
            "ammunition": 3,
            **({"body": 50} if interference else {}),
            **({"head": 4747} if repair else {}),
        }
        scorer = ScoringContext(search)
        actual, _ = drain(
            StageContext(scorer, search).begin(
                kind="loadout",
                states=[base],
                choices=[9756, 10498],
                slot="cape",
                roles=("z",),
                metric=True,
            ),
            8,
        )
        engine = CostEvaluator(search.running_prices, now)

        def rank(equipment):
            performance = scorer.score(equipment, 0, True)
            recipe = engine.prepare(
                {slot: search.items[item] for slot, item in equipment.items()},
                {"attack_type": "ranged"},
            )
            numeric = recipe.score(performance["interval"], performance["dps"])
            aggregate = aggregate_numeric_cost([(1, numeric, performance["dps"])])
            return (
                aggregate.gp_per_damage if aggregate.gp_per_damage is not None else 1e100,
                -performance["dps"],
                tuple(sorted(equipment.items())),
            )

        assert actual == sorted([{**base, "cape": 9756}, {**base, "cape": 10498}], key=rank)


def test_stage_expansion_counts_rejected_candidates_and_chunks():
    with stage_search() as search:
        context = StageContext(ScoringContext(search), search)
        args = {
            "kind": "loadout",
            "states": [{}],
            "choices": [None, 2, 10, 100],
            "slot": "weapon",
            "roles": ("z",),
        }
        whole, count = drain(context.begin(**args), 256)
        chunked, chunk_count = drain(context.begin(**args), 256, chunk=1)
        assert whole == chunked
        assert count == chunk_count == 4
        assert whole[0] == {"weapon": 10}


@pytest.mark.parametrize("frontier,metric", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("limit", [1, 7, 40])
def test_loadout_retention_matches_python_rank_and_diversity(frontier, metric, limit):
    with stage_search() as search:
        search.frontier_search = frontier
        search.metric_first = metric
        context = StageContext(ScoringContext(search), search)
        choices = [None, *range(201, 225)]
        candidates = [{"weapon": 2, **({"head": item} if item else {})} for item in choices]

        def rank(equipment):
            performance = search.search_performance(equipment, search.request.roles[0])
            return (
                -(performance.get("dps") or 0),
                -search.search_secondary(equipment, search.request.roles),
                search.cost(set(equipment.values())),
                -sum(search.items[i].bonuses.melee_strength for i in equipment.values()),
                search.untradeable_acquisitions(set(equipment.values())),
                tuple(sorted(equipment.items())),
            )

        expected = search.retain(candidates, rank, limit)
        actual, count = drain(
            context.begin(
                kind="loadout",
                states=[{"weapon": 2}],
                choices=choices,
                slot="head",
                roles=("z",),
                frontier=frontier,
                metric=metric,
            ),
            limit,
            chunk=3,
        )
        assert count == len(choices)
        assert actual == expected


def test_joint_transition_cap_and_native_json_ties():
    with stage_search(multiple=True) as search:
        # Equal marginals force the original serialized item-ID ordering.
        search.marginals = dict.fromkeys(search.marginals, 0.0)
        context = StageContext(ScoringContext(search), search)
        actual, count = drain(
            context.begin(
                kind="joint",
                states=[{"z": {}, "a": {}}],
                choices=[[2, 10, 100], [2, 10, 100]],
                slot="weapon",
                roles=("z", "a"),
                cap=0,
            ),
            16,
        )
        assert count == 9
        expected = [{"z": {"weapon": i}, "a": {"weapon": i}} for i in (2, 10, 100)]
        assert actual == sorted(expected, key=lambda row: json.dumps(row, sort_keys=True))
        assert all(row["z"] == row["a"] for row in actual)


def test_stage_rejects_invalid_chunk_size():
    with stage_search() as search:
        expansion = StageContext(ScoringContext(search), search).begin(
            kind="loadout", states=[{}], choices=[2], slot="weapon", roles=("z",)
        )
        for count in (0, -1, 1025, True):
            with pytest.raises(ValueError):
                expansion.advance(count)


def test_finish_keeps_only_attempted_prefix_when_budget_exhausted():
    with stage_search() as search:
        expansion = StageContext(ScoringContext(search), search).begin(
            kind="loadout", states=[{}], choices=[2, 10, 100], slot="weapon", roles=("z",)
        )
        assert expansion.advance(1) == 1
        assert not expansion.done
        assert expansion.finish(256) == [{"weapon": 2}]
        with pytest.raises(ValueError):
            expansion.advance(1)
        with pytest.raises(ValueError):
            expansion.finish(256)


def test_joint_inventory_uses_union_without_extra_tuple_pruning():
    with stage_search(multiple=True) as search:
        search.request = search.request.model_copy(update={"reserved_supply_slots": 28})
        context = StageContext(ScoringContext(search), search)
        joint, count = drain(
            context.begin(
                kind="joint",
                states=[{"z": {}, "a": {}}],
                choices=[[2], [10]],
                slot="weapon",
                roles=("z", "a"),
            ),
            16,
        )
        assert count == 1 and joint == []
        tuples, count = drain(
            context.begin(
                kind="tuple",
                states=[{"z": {"weapon": 2}}],
                choices=[{"weapon": 10}],
                roles=("z", "a"),
                tuple_role="a",
            ),
            256,
        )
        assert count == 1 and tuples == [{"z": {"weapon": 2}, "a": {"weapon": 10}}]


def test_tuple_directional_two_handed_lower_bound():
    with stage_search(multiple=True) as search:
        search.edges = (("z", "a"),)
        context = StageContext(ScoringContext(search), search)
        args = {
            "kind": "tuple",
            "states": [{"z": {"weapon": 2, "shield": 300}}],
            "choices": [{"weapon": 100}],
            "roles": ("z", "a"),
            "tuple_role": "a",
        }
        assert drain(context.begin(**args, cap=1), 256)[0]
        assert not drain(context.begin(**args, cap=0), 256)[0]


def test_market_alias_cost_uses_highest_physical_id_quote(monkeypatch):
    from tracker.gear.compact_acquisition import AcquisitionFacts

    with stage_search(multiple=True) as search:
        quotes = dict.fromkeys(search.facts)
        quotes.update({2: (999, 100), 10: (999, 10)})
        monkeypatch.setattr(
            AcquisitionFacts,
            "from_facts",
            classmethod(lambda cls, facts, request: cls(quotes, frozenset({10}))),
        )
        search.request = search.request.model_copy(update={"budget_gp": 10})
        context = StageContext(ScoringContext(search), search)
        rows, _ = drain(
            context.begin(
                kind="joint",
                states=[{"z": {}, "a": {}}],
                choices=[[2], [10]],
                slot="weapon",
                roles=("z", "a"),
            ),
            16,
        )
        assert rows == [{"z": {"weapon": 2}, "a": {"weapon": 10}}]


def test_pack_rejects_acquisition_overflow(monkeypatch):
    from tracker.gear.compact_acquisition import AcquisitionFacts

    with stage_search() as search:
        quotes = dict.fromkeys(search.facts)
        quotes[2] = (999, 2**56)
        monkeypatch.setattr(
            AcquisitionFacts,
            "from_facts",
            classmethod(lambda cls, facts, request: cls(quotes, frozenset())),
        )
        with pytest.raises(ValueError, match="supported range"):
            StageContext(ScoringContext(search), search)


def test_stage_rejects_mismatched_scoring_role_dimensions():
    with (
        stage_search() as single,
        stage_search(multiple=True) as multi,
        pytest.raises(ValueError, match="role dimensions differ"),
    ):
        StageContext(ScoringContext(single), multi)


@pytest.mark.parametrize("weight", [float("inf"), float("nan"), -1.0, 1e13])
def test_preflight_rejects_unbounded_weights(weight):
    from tracker.gear.native.stage_context import preflight

    with stage_search() as search:
        role = search.request.roles[0].model_copy(update={"weight": weight})
        search.request = search.request.model_copy(update={"roles": (role,)})
        assert "weights" in preflight(search)


@pytest.mark.parametrize("count", [0, 5])
def test_preflight_rejects_unsupported_role_count(count):
    from tracker.gear.native.stage_context import preflight

    with stage_search() as search:
        search.request = search.request.model_copy(update={"roles": search.request.roles * count})
        assert "roles" in preflight(search)


def test_preflight_preserves_exact_integer_cost_ranking_boundary():
    from tracker.gear.compact_acquisition import AcquisitionFacts
    from tracker.gear.native.stage_context import MAX_NATIVE_ITEM_COST, preflight

    with stage_search() as search:
        safe = AcquisitionFacts({2: (999, MAX_NATIVE_ITEM_COST)}, frozenset())
        unsafe = AcquisitionFacts({2: (999, MAX_NATIVE_ITEM_COST + 1)}, frozenset())
        assert preflight(search, safe) is None
        assert "acquisition integers" in preflight(search, unsafe)
