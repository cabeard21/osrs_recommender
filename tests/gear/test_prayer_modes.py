"""Prayer policies retain per-role identity through composed search modes."""

from dataclasses import replace

from tests.gear.test_auto_disciplines import OPTIONS, context
from tracker.domain.types import SkillState, Source
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize
from tracker.gear.prayers import PrayerPolicy


def test_joint_prayers_remain_independent_with_potions_and_frontiers():
    snapshot, _, catalog, content, prices, now = context()
    snapshot = replace(
        snapshot, skills={**snapshot.skills, "prayer": SkillState(99, None, Source.MANUAL, now)}
    )
    roles = tuple(
        RoleConfig(
            id=rid,
            style=style,
            combat_options=OPTIONS,
            prayers=PrayerPolicy(mode="optimize", allowed_ids=(prayer,)),
        )
        for rid, style, prayer in (
            ("melee", "slash", "ultimate_strength"),
            ("range", "ranged", "eagle_eye"),
        )
    )
    request = OptimizationRequest(
        roles=roles,
        mode="owned",
        max_swaps=2,
        secondary_priority="balanced_defence_roll",
        potions={"mode": "optimize", "allowed_ids": ["super_strength"]},
    )
    result = optimize(snapshot, request, catalog, content, prices, now)
    assert result["selected_solution"] is not None
    expected = {"melee": ["ultimate_strength"], "range": ["eagle_eye"]}
    for solution in (
        result["selected_solution"],
        result["unrestricted"],
        *(p["solution"] for p in result["curve"]),
    ):
        if solution is None:
            continue
        assert {
            rid: row["selected_prayer_ids"] for rid, row in solution["loadouts"].items()
        } == expected
    ids = [p["id"] for group in result["secondary_frontiers"] for p in group["points"]]
    assert ids and len(ids) == len(set(ids))
