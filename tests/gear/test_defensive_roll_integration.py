"""Complete-loadout defensive scoring across potion search and shared evaluation."""

import pytest

from tests.gear.test_optimizer import run, weapon
from tests.gear.test_secondary_priorities import armour
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.optimizer import RoleConfig
from tracker.gear.potions import boosted_levels
from tracker.gear.priorities import secondary_value


def test_multi_defensive_rolls_take_each_roles_minimum_before_weighting():
    result = run(
        [
            weapon(1, "slash"),
            armour(20, defence_magic=100, defence_ranged=10),
            armour(30, defence_magic=20, defence_ranged=100),
        ],
        (
            RoleConfig(id="a", style="slash", weight=1, locks={"head": 20}),
            RoleConfig(id="b", style="slash", weight=3, locks={"head": 30}),
        ),
        max_swaps=1,
        secondary_priority="magic_ranged_defence_roll",
    )
    # Level 70 in both stats gives effective defence 78 in both styles.
    # These loadouts have opposite weak sides; pooling first gives the wrong score.
    expected = ((10 + 64) * 78 + 3 * (20 + 64) * 78) / 4
    assert result["selected_solution"]["secondary_value"] == expected


@pytest.mark.parametrize(
    "priority,potion,expected_level",
    [
        ("ranged_defence_roll", "super_defence", 85),
        ("magic_defence_roll", "magic", 74),
        ("melee_defence_roll", "super_defence", 85),
        ("melee_ranged_defence_roll", "super_defence", 85),
        ("melee_magic_defence_roll", "super_defence", 85),
        ("stab_magic_defence_roll", "super_defence", 85),
        ("stab_ranged_defence_roll", "super_defence", 85),
        ("stab_magic_ranged_defence_roll", "super_defence", 85),
        ("slash_magic_defence_roll", "super_defence", 85),
        ("slash_ranged_defence_roll", "super_defence", 85),
        ("slash_magic_ranged_defence_roll", "super_defence", 85),
        ("crush_magic_defence_roll", "super_defence", 85),
        ("crush_ranged_defence_roll", "super_defence", 85),
        ("crush_magic_ranged_defence_roll", "super_defence", 85),
    ],
)
def test_defensive_potion_search_matches_fixed_setup_and_manual_evaluator(
    priority, potion, expected_level
):
    items = [weapon(1, "slash", 40)]
    role = RoleConfig(id="a", style="slash")
    options = {"max_swaps": 0, "secondary_priority": priority, "max_dps_loss_pct": 100}
    plain = run(items, (role,), **options)["selected_solution"]
    fixed = run(items, (role,), **options, potions={"mode": "fixed", "selected_ids": (potion,)})[
        "selected_solution"
    ]
    optimized = run(
        items, (role,), **options, potions={"mode": "optimize", "allowed_ids": (potion,)}
    )
    assert optimized["search"]["potion_selection"]["branch_count"] == 2
    best = optimized["secondary_frontiers"][0]["points"][-1]["solution"]
    assert best["potions"]["selected_ids"] == [potion]
    assert best["secondary_value"] == fixed["secondary_value"] > plain["secondary_value"]
    assert best["score"] == fixed["score"] == plain["score"]
    skill = "defence" if potion == "super_defence" else "magic"
    assert best["potions"]["boosted_levels"][skill] == expected_level

    levels = boosted_levels(
        dict.fromkeys(("attack", "strength", "defence", "ranged", "magic"), 70), (potion,)
    )
    row = best["loadouts"]["a"]
    manual = evaluate_equipment(row["equipment"], {i.id: i for i in items}, role, levels)
    assert secondary_value(priority, manual.model_dump(mode="json")) == best["secondary_value"]
    assert manual.dps == best["score"]


@pytest.mark.parametrize(
    "priority,other",
    [
        ("melee_defence_roll", "slash"),
        ("melee_magic_defence_roll", "magic"),
        ("melee_ranged_defence_roll", "ranged"),
        ("stab_magic_defence_roll", "magic"),
        ("stab_ranged_defence_roll", "ranged"),
        ("stab_magic_ranged_defence_roll", "ranged"),
        ("slash_magic_defence_roll", "magic"),
        ("slash_ranged_defence_roll", "ranged"),
        ("slash_magic_ranged_defence_roll", "ranged"),
        ("crush_magic_defence_roll", "magic"),
        ("crush_ranged_defence_roll", "ranged"),
        ("crush_magic_ranged_defence_roll", "ranged"),
    ],
)
def test_melee_multi_minimum_precedes_active_time_weighting(priority, other):
    first = {
        "defence_stab": 100,
        "defence_slash": 100,
        "defence_crush": 100,
        "defence_magic": 100,
        "defence_ranged": 100,
        "defence_" + other: 10,
    }
    second = {
        "defence_stab": 100,
        "defence_slash": 100,
        "defence_crush": 100,
        "defence_magic": 100,
        "defence_ranged": 100,
        "defence_" + ("stab" if priority.startswith("melee_") else priority.split("_")[0]): 20,
    }
    result = run(
        [weapon(1, "slash"), armour(20, **first), armour(30, **second)],
        (
            RoleConfig(id="a", style="slash", weight=1, locks={"head": 20}),
            RoleConfig(id="b", style="slash", weight=3, locks={"head": 30}),
        ),
        max_swaps=1,
        secondary_priority=priority,
    )
    assert (
        result["selected_solution"]["secondary_value"] == ((10 + 64) * 78 + 3 * (20 + 64) * 78) / 4
    )
