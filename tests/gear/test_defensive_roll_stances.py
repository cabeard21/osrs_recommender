"""Defensive roll frontiers preserve complete legal stance alternatives."""

from tests.gear.test_optimizer import run, weapon
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig


def test_roll_frontier_keeps_longrange_and_rapid_with_selected_options():
    item = weapon(1, "ranged", attack_profiles=(("ranged", "rapid"), ("ranged", "longrange")))
    result = run(
        [item],
        (
            RoleConfig(
                id="a",
                style="ranged",
                combat_options=CombatOptionFilters(
                    attack_types=("light",),
                    stances=("rapid", "longrange"),
                    spells=(),
                ),
            ),
        ),
        max_swaps=0,
        secondary_priority="ranged_defence_roll",
        max_dps_loss_pct=100,
    )
    rows = [point["solution"] for point in result["secondary_frontiers"][0]["points"]]
    assert {row["loadouts"]["a"]["combat_option"]["stance"] for row in rows} == {
        "rapid",
        "longrange",
    }
    assert rows[0]["score"] > rows[-1]["score"]
    assert rows[0]["secondary_value"] < rows[-1]["secondary_value"]


def test_fixed_stance_is_not_changed_for_roll_metric():
    result = run(
        [weapon(1, "ranged")],
        (RoleConfig(id="a", style="ranged", stance="rapid"),),
        max_swaps=0,
        secondary_priority="ranged_defence_roll",
        max_dps_loss_pct=100,
    )
    rows = result["secondary_frontiers"][0]["points"]
    assert len(rows) == 1
    assert rows[0]["solution"]["secondary_value"] == (70 + 8) * 64
