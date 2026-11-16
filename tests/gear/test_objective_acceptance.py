"""An actual gear tradeoff that disappears in every two-axis defence projection."""

from itertools import combinations
from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tools.benchmark_objectives import objective_set
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.native import capture
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize


@pytest.mark.parametrize("use_native", [False, True])
@pytest.mark.parametrize("all_objectives", [False, True])
def test_interior_tradeoff_survives_every_pairwise_projection_and_native_execution(
    use_native, all_objectives
):
    items = [weapon(1, "slash")]
    styles = ("stab", "slash", "magic")
    for item_id, values in enumerate(((9, 9, 0), (9, 0, 9), (0, 9, 9), (6, 6, 6)), 2):
        items.append(
            EquipmentDefinition(
                id=item_id,
                name=str(item_id),
                slot="head",
                requirements_complete=True,
                bonuses=EquipmentBonuses(
                    **dict(
                        zip(
                            ("defence_" + style for style in styles),
                            values,
                            strict=True,
                        )
                    )
                ),
            )
        )
    snapshot = AccountSnapshot(
        1,
        "vector-acceptance",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (item.id, Container.BANK): ObservedItemFact(
                item.id,
                Container.BANK,
                1,
                "fixture",
                NOW,
            )
            for item in items
        },
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="a", style="slash"),),
        mode="owned",
        max_swaps=0,
        max_dps_loss_pct=100,
        objectives=objective_set(62)
        if all_objectives
        else [{"kind": "defence_roll", "styles": [style]} for style in styles],
    )
    args = (
        snapshot,
        request,
        SimpleNamespace(items={i.id: i for i in items}, version="fixture"),
        Content(),
        {},
        NOW,
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
    }
    reference = optimize(*args, **flags)
    native = reference
    if use_native:
        pytest.importorskip("tracker.gear.native._scoring")
        with capture() as evidence:
            native = optimize(*args, **flags, _native_search=True)
        assert evidence.snapshot()["native_requests"] > 0
        assert evidence.snapshot()["fallback_requests"] == 0

    def vectors(result):
        return {
            tuple(sorted(point["solution"]["objective_values"].items()))
            for point in result["objective_frontiers"][0]["points"]
        }

    assert vectors(native) == vectors(reference)
    points = [dict(values) for values in vectors(native)]
    assert len(points) == 4
    defence_axes = ["defence_roll:minimum:" + style for style in styles]
    interior = next(
        values for values in points if all(values[axis] == 78 * 70 for axis in defence_axes)
    )
    for axes in combinations(defence_axes, 2):
        assert any(all(row[axis] > interior[axis] for axis in axes) for row in points)
    for result in (reference, native) if use_native else (reference,):
        for group in result["objective_frontiers"]:
            group["points"].close()
