"""Exact frontier semantics over completed solutions."""

import pytest

from tracker.gear.frontier import pareto


def point(dps, secondary, identity):
    return {
        "score": dps,
        "secondary_value": secondary,
        "max_gear_inventory_slots": 0,
        "purchase_cost_gp": 0,
        "transitions": [],
        "loadouts": {identity: {}},
    }


def test_frontier_removes_dominated_and_equal_pairs():
    rows = [point(10, 1, "a"), point(9, 5, "b"), point(8, 2, "c"), point(9, 5, "z")]
    assert [(x["score"], x["secondary_value"]) for x in pareto(rows)] == [(10, 1), (9, 5)]


def test_negative_secondary_and_zero_dps():
    rows = [point(0, -5, "a"), point(0, -2, "b")]
    assert pareto(rows) == [rows[1]]


@pytest.mark.parametrize("priority", ["balanced_defence", "magic_ranged_defence"])
def test_real_defensive_tradeoff_and_baseline_preservation(priority):
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    items = [
        weapon(1, "slash"),
        armour(20, melee_strength=10),
        armour(30, defence_stab=100, defence_magic=40, defence_ranged=60),
    ]
    roles = (RoleConfig(id="a", style="slash"),)
    result = run(items, roles, max_swaps=0, secondary_priority=priority, max_dps_loss_pct=100)
    points = result["secondary_frontiers"][0]["points"]
    assert len(points) >= 2
    assert points[0]["dps_loss_pct"] == 0
    assert points[-1]["secondary_gain"] > 0
    assert result["selected_solution"]["score"] == points[0]["solution"]["score"]
    assert {30} <= {row["item_id"] for row in result["items"]}


def test_range_filters_completed_points():
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    result = run(
        [weapon(1, "slash"), armour(20, melee_strength=10), armour(30, defence_stab=100)],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        secondary_priority="balanced_defence",
        max_dps_loss_pct=0,
    )
    assert all(p["dps_loss_pct"] == 0 for p in result["secondary_frontiers"][0]["points"])


def test_omitted_defence_candidate_survives_and_joint_limits_are_valid():
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    items = [
        weapon(1, "slash"),
        *[armour(i, melee_strength=100 - i) for i in range(10, 35)],
        armour(100, defence_stab=500),
    ]
    result = run(
        items,
        (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="slash")),
        max_swaps=1,
        secondary_priority="stab_defence",
        max_dps_loss_pct=100,
    )
    assert result["secondary_frontiers"][0]["points"][-1]["solution"]["secondary_value"] == 500
    for group in result["secondary_frontiers"]:
        for point in group["points"]:
            if group["swap_limit"] is not None:
                assert point["solution"]["maximum_actions"] <= group["swap_limit"]


def test_accuracy_frontier_includes_slower_more_accurate_stance():
    from tests.gear.test_optimizer import run, weapon
    from tracker.gear.optimizer import CombatOptionFilters, RoleConfig

    item = weapon(1, "ranged", attack_profiles=(("ranged", "accurate"), ("ranged", "rapid")))
    result = run(
        [item],
        (
            RoleConfig(
                id="a",
                style="ranged",
                combat_options=CombatOptionFilters(
                    attack_types=("light",), stances=("accurate", "rapid"), spells=()
                ),
            ),
        ),
        max_swaps=0,
        secondary_priority="accuracy",
        max_dps_loss_pct=100,
    )
    points = result["secondary_frontiers"][0]["points"]
    assert {p["solution"]["loadouts"]["a"]["combat_option"]["stance"] for p in points} == {
        "accurate",
        "rapid",
    }


def test_thorough_substitution_budget_is_shared(monkeypatch):
    import tracker.gear.frontier as frontier
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    explore = frontier.explore
    monkeypatch.setattr(
        frontier,
        "explore",
        lambda search, winners, unlimited, thorough: explore(search, winners, unlimited, True),
    )
    result = run(
        [weapon(1, "slash"), armour(20, melee_strength=10), armour(30, defence_stab=100)],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        secondary_priority="stab_defence",
    )
    diagnostics = result["search"]["secondary_frontier"]
    assert 0 < diagnostics["assignment_attempts"] <= 10000
    assert diagnostics["explored_nodes"] <= 1500000


def test_display_sampling_preserves_extremes():
    from tracker.gear.frontier import diverse

    rows = [point(100 - i, i, str(i)) for i in range(100)]

    def rank(row):
        return (-row["score"], -row["secondary_value"])

    retained = diverse(rows, rank, 8)
    assert rows[0] in retained and rows[-1] in retained
    assert len(retained) == 8


@pytest.mark.parametrize("thorough", [False, True])
def test_shared_armour_compromises_survive_one_weapon_switch(thorough, monkeypatch):
    import tracker.gear.frontier as frontier
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    explore = frontier.explore
    monkeypatch.setattr(frontier, "explore", lambda s, w, u, _: explore(s, w, u, thorough))

    items = [
        weapon(1, "slash", 50),
        weapon(2, "ranged", 50),
        *[
            armour(
                10 + i, melee_strength=80 - 10 * i, ranged_strength=80 - 10 * i, defence_stab=10 * i
            )
            for i in range(7)
        ],
    ]
    result = run(
        items,
        (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="ranged")),
        max_swaps=8,
        secondary_priority="stab_defence",
        max_dps_loss_pct=100,
    )
    group = next(g for g in result["secondary_frontiers"] if g["swap_limit"] == 1)
    shared_heads = {
        p["solution"]["loadouts"]["a"]["equipment"].get("head")
        for p in group["points"]
        if p["solution"]["loadouts"]["a"]["equipment"].get("head")
        == p["solution"]["loadouts"]["b"]["equipment"].get("head")
    }
    assert {12, 13, 14} <= shared_heads
    assert all(p["solution"]["maximum_actions"] <= 1 for p in group["points"])
    diagnostics = result["search"]["secondary_frontier"]
    assert diagnostics["explored_nodes"] <= diagnostics["expansion_limit"]
    assert 0 < diagnostics["shared_assignment_attempts"] <= 10000


@pytest.mark.parametrize("global_lock", [False, True])
def test_shared_substitutions_preserve_locks_and_seeds(global_lock):
    from copy import deepcopy
    from types import SimpleNamespace

    from tracker.gear.frontier import _shared_assignments
    from tracker.gear.optimizer import SLOTS, RoleConfig

    seed = {
        **point(10, 1, "a"),
        "loadouts": {"a": {"equipment": {"head": 12}}, "b": {"equipment": {"head": 12}}},
    }
    before = deepcopy(seed)
    search = SimpleNamespace(
        request=SimpleNamespace(
            locks={"head": 12} if global_lock else {},
            roles=(
                RoleConfig(id="a", style="slash", locks={} if global_lock else {"head": 12}),
                RoleConfig(id="b", style="ranged"),
            ),
        ),
        pools={slot: [None, 12, 13] if slot == "head" else [None] for slot in SLOTS},
    )
    assert list(_shared_assignments(search, [[seed]])) == []
    assert seed == before


def test_metric_lane_ranks_metric_before_damage():
    from types import SimpleNamespace

    from tracker.gear.optimizer import _Search

    search = SimpleNamespace(frontier_search=True, metric_first=True)
    rows = [(10, 1), (3, 50), (7, 20)]
    selected = _Search.retain(search, rows, lambda row: (-row[0], -row[1]), 1)
    assert selected == [(3, 50)]


def test_metric_lane_runs_with_separate_equipment_allowance():
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    result = run(
        [weapon(1, "slash"), armour(20, melee_strength=30), armour(30, defence_stab=100)],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        secondary_priority="stab_defence",
        max_dps_loss_pct=100,
    )
    diagnostics = result["search"]["secondary_frontier"]
    assert diagnostics["metric_lane"]["explored_nodes"] > 0
    assert diagnostics["metric_lane"]["expansion_limit"] == (500000 - 25000) // 4
    points = result["secondary_frontiers"][0]["points"]
    assert points[-1]["solution"]["secondary_value"] == 100


def test_complementary_defence_frontier_matches_tiny_exhaustive_oracle():
    from itertools import product

    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    heads = [
        armour(20, melee_strength=35),
        armour(21, defence_magic=90, defence_ranged=-10),
        armour(22, defence_magic=25, defence_ranged=25, melee_strength=10),
    ]
    bodies = [
        armour(30, melee_strength=35).model_copy(update={"slot": "body"}),
        armour(31, defence_magic=-10, defence_ranged=90).model_copy(update={"slot": "body"}),
        armour(32, defence_magic=25, defence_ranged=25, melee_strength=10).model_copy(
            update={"slot": "body"}
        ),
    ]
    items = [weapon(1, "slash"), *heads, *bodies]
    roles = (RoleConfig(id="a", style="slash"),)
    args = {"max_swaps": 0, "secondary_priority": "magic_ranged_defence", "max_dps_loss_pct": 100}
    exhaustive = [
        run(items, roles, locks={"weapon": 1, "head": h, "body": b}, **args)["selected_solution"]
        for h, b in product([None, 20, 21, 22], [None, 30, 31, 32])
    ]
    expected = {(r["score"], r["secondary_value"]) for r in pareto(exhaustive)}
    result = run(items, roles, **args)
    points = result["secondary_frontiers"][0]["points"]
    assert {(p["solution"]["score"], p["solution"]["secondary_value"]) for p in points} == expected
    assert points[-1]["solution"]["secondary_value"] == 80
    assert points[-1]["dps_loss_pct"] > 10
    diagnostics = result["search"]["secondary_frontier"]
    assert diagnostics["explored_nodes"] <= diagnostics["expansion_limit"]


@pytest.mark.parametrize(
    "priority,styles",
    [
        ("melee_defence_roll", ("stab", "slash", "crush")),
        ("melee_magic_defence_roll", ("stab", "slash", "crush", "magic")),
        ("melee_ranged_defence_roll", ("stab", "slash", "crush", "ranged")),
    ],
)
def test_melee_complementary_frontier_matches_exhaustive_oracle(priority, styles):
    from itertools import product

    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    head_bonus = {"defence_" + style: (-10 if style == styles[-1] else 90) for style in styles}
    body_bonus = {"defence_" + style: (90 if style == styles[-1] else -10) for style in styles}
    items = [
        weapon(1, "slash"),
        armour(20, melee_strength=35),
        armour(21, **head_bonus),
        armour(30, melee_strength=35).model_copy(update={"slot": "body"}),
        armour(31, **body_bonus).model_copy(update={"slot": "body"}),
    ]
    roles = (RoleConfig(id="a", style="slash"),)
    options = {"max_swaps": 0, "secondary_priority": priority, "max_dps_loss_pct": 100}
    exhaustive = [
        run(items, roles, locks={"weapon": 1, "head": head, "body": body}, **options)[
            "selected_solution"
        ]
        for head, body in product([None, 20, 21], [None, 30, 31])
    ]
    expected = {(row["score"], row["secondary_value"]) for row in pareto(exhaustive)}
    result = run(items, roles, **options)
    points = result["secondary_frontiers"][0]["points"]
    assert {(p["solution"]["score"], p["solution"]["secondary_value"]) for p in points} == expected
    assert points[-1]["solution"]["secondary_value"] == (80 + 64) * 78


@pytest.mark.parametrize(
    "priority,styles",
    [
        ("melee_defence_roll", ("stab", "slash", "crush")),
        ("melee_magic_defence_roll", ("stab", "slash", "crush", "magic")),
        ("melee_ranged_defence_roll", ("stab", "slash", "crush", "ranged")),
    ],
)
def test_truncated_metric_pools_retain_each_melee_component_leader(priority, styles):
    from types import SimpleNamespace

    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.frontier import _metric_pools
    from tracker.gear.optimizer import SLOTS

    ordinary = [armour(i) for i in range(1, 101)]
    leaders = [
        armour(200 + index, **{"defence_" + style: 100}) for index, style in enumerate(styles)
    ]
    items = {item.id: item for item in [*ordinary, *leaders]}
    search = SimpleNamespace(
        eligible=items,
        items=items,
        secondary_marginals={},
        marginals={},
        request=SimpleNamespace(
            secondary_priority=priority, roles=(SimpleNamespace(id="a", style="slash"),)
        ),
        cost=lambda _: 0,
    )
    pools = _metric_pools(search, SimpleNamespace(pools={slot: [None] for slot in SLOTS}))
    assert len(pools["head"]) == 48
    assert {item.id for item in leaders}.issubset(pools["head"])
