"""Exact frontier semantics over completed solutions."""

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


def test_real_defensive_tradeoff_and_baseline_preservation():
    from tests.gear.test_optimizer import run, weapon
    from tests.gear.test_secondary_priorities import armour
    from tracker.gear.optimizer import RoleConfig

    items = [weapon(1, "slash"), armour(20, melee_strength=10), armour(30, defence_stab=100)]
    roles = (RoleConfig(id="a", style="slash"),)
    result = run(
        items, roles, max_swaps=0, secondary_priority="balanced_defence", max_dps_loss_pct=100
    )
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
    assert 0 < diagnostics["assignment_attempts"] <= 2000
    assert diagnostics["explored_nodes"] <= 300000


def test_display_sampling_preserves_extremes():
    from tracker.gear.frontier import diverse

    rows = [point(100 - i, i, str(i)) for i in range(100)]

    def rank(row):
        return (-row["score"], -row["secondary_value"])

    retained = diverse(rows, rank, 8)
    assert rows[0] in retained and rows[-1] in retained
    assert len(retained) == 8
