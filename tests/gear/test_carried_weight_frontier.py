"""Small fully enumerated kits exercise search, reporting and native screening."""

from functools import partial
from itertools import product
from types import SimpleNamespace

import pytest

from tests.gear import test_optimizer
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.native import capture
from tracker.gear.objectives import ObjectiveDescriptor
from tracker.gear.optimizer import SLOTS, RoleConfig
from tracker.gear.vector_search import VectorSearch


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("mixed_cost", [False, True])
def test_weight_frontier_matches_exhaustive_kit_oracle(monkeypatch, native, mixed_cost):
    if native:
        pytest.importorskip("tracker.gear.native._frontier")
        monkeypatch.setattr(
            test_optimizer,
            "optimize",
            partial(
                test_optimizer.optimize,
                _native_search=True,
                _native_required=True,
                _execution_profile="combined",
                _factored_evaluation=True,
                _compact_states=True,
            ),
        )
    weapon = test_optimizer.weapon(1, "slash", worn_weight_grams=500, inventory_weight_grams=500)
    heads = [
        EquipmentDefinition(
            id=item_id,
            name=str(item_id),
            slot="head",
            worn_weight_grams=worn,
            inventory_weight_grams=packed,
            bonuses=EquipmentBonuses(melee_strength=strength),
            requirements_complete=True,
        )
        for item_id, worn, packed, strength in [
            (2, 2500, 2500, 40),
            (3, -1000, 200, 0),
            (4, 1500, 1500, 20),
            (5, 1700, 1700, 20),
        ]
    ]
    roles = (
        RoleConfig(id="a", style="slash", locks={"weapon": 1}),
        RoleConfig(id="switch", style="special", parent_role="a", locks={"weapon": 1, "head": 3}),
    )
    goals = [{"kind": "carried_weight_kg"}]
    if mixed_cost:
        goals.append({"kind": "gp_per_damage"})
    with capture() as evidence:
        result = test_optimizer.run(
            [weapon, *heads],
            roles,
            objectives=goals,
            max_swaps=1,
            max_dps_loss_pct=100,
        )
    if native:
        diagnostics = evidence.snapshot()
        assert diagnostics["native_requests"] > 0
        assert diagnostics["fallback_requests"] == 0
        assert any(
            event["event"] == "vector_option_batch" and event["screened"] > 0
            for event in diagnostics["events"]
        )
    # Heavy, reducer, intermediate, dominated, and empty exhaust the ordinary
    # role's head slot. Empty ties the reducer on DPS. Item 5 ties item 4.
    for group in result["objective_frontiers"]:
        expected = {-0.5} if group["swap_limit"] == 0 else {-0.5, 2.2, 3.2}
        rows = [p["solution"] for p in group["points"]]
        assert {r["objective_values"]["carried_weight_kg"] for r in rows} == expected
        for row in rows:
            if mixed_cost:
                assert row["objective_values"]["gp_per_damage"] == 0
            setups = [r["equipment"] for r in row["loadouts"].values()]
            carried = set().union(*(set(e.values()) for e in setups))
            items = {obj.id: obj for obj in (weapon, *heads)}
            peak = (
                max(
                    sum(
                        items[i].worn_weight_grams
                        if i in setup.values()
                        else items[i].inventory_weight_grams
                        for i in carried
                    )
                    for setup in setups
                )
                / 1000
            )
            assert row["objective_values"]["carried_weight_kg"] == peak
        assert all(
            a["score"] > b["score"]
            or a["objective_values"]["carried_weight_kg"]
            < b["objective_values"]["carried_weight_kg"]
            for a, b in product(rows, repeat=2)
            if a is not b
        )


def test_worn_and_backpack_leaders_survive_crowded_slot_truncation():
    items = {
        i: SimpleNamespace(
            slot="head",
            worn_weight_grams=-500 if i == 91 else 100,
            inventory_weight_grams=0 if i == 93 else 100,
        )
        for i in range(1, 100)
    }
    engine = VectorSearch.__new__(VectorSearch)
    engine.objectives = (ObjectiveDescriptor(kind="carried_weight_kg"),)
    engine.options = SimpleNamespace(cost_index=None, risk_index=None)
    engine.search = SimpleNamespace(
        items=items,
        eligible=items,
        wilderness=None,
        request=SimpleNamespace(roles=(RoleConfig(id="a", style="slash"),)),
        pools={s: list(items) if s == "head" else [] for s in SLOTS},
        cost=sum,
        budget_item_rank=lambda item: (item,),
    )
    pool = engine.candidate_pools()["head"]
    assert len(pool) < len(items)
    assert {None, 91, 93} <= set(pool)
