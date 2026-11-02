"""Running-resource objective stays independent from secondary priorities."""

from tracker.gear.running_frontier import aggregate_cost, cost_pareto, publish_groups


def row(dps, gp, name="a"):
    return {
        "score": dps,
        "maximum_actions": 0,
        "purchase_cost_gp": 0,
        "loadouts": {name: {}},
        "running_cost": {
            "status": "known" if gp is not None else "unavailable",
            "gp_per_damage": gp,
        },
    }


def test_dominance_minimizes_cost_and_excludes_unknown():
    rows = [row(10, 4), row(9, 2), row(8, 3), row(11, None)]
    assert cost_pareto(rows) == rows[:2]


def test_unknown_baseline_sets_loss_cap_without_becoming_free():
    baseline = row(10, None)
    groups = publish_groups({0: [row(9, 2), row(8, 1)]}, {0: baseline}, 10)
    assert groups[0]["baseline_solution"] == baseline
    assert [p["dps_loss_pct"] for p in groups[0]["points"]] == [10]


def test_weighted_cost_is_ratio_of_weighted_rates():
    roles = [
        (1, {"status": "known", "gp_per_hour": 3600}, 1),
        (3, {"status": "known", "gp_per_hour": 7200}, 10),
    ]
    result = aggregate_cost(roles)
    assert result["gp_per_damage"] == 7 / 31
    assert result["gp_per_hour"] == 6300


def test_zero_damage_and_unknown_active_role_are_unavailable():
    assert aggregate_cost([(1, {"status": "known", "gp_per_hour": 0}, 0)])["gp_per_damage"] is None
    assert (
        aggregate_cost([(1, {"status": "unavailable", "gp_per_hour": None}, 10)])["status"]
        == "unavailable"
    )
    assert (
        aggregate_cost([(1, {"status": "known", "gp_per_hour": None}, 0)])["status"]
        == "unavailable"
    )


def mage_result(**updates):
    from types import SimpleNamespace

    from tests.gear.test_optimizer import NOW
    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.models import EquipmentDefinition
    from tracker.gear.optimizer import (
        CombatOptionFilters,
        OptimizationRequest,
        RoleConfig,
        optimize,
    )

    items = [
        EquipmentDefinition(
            id=i,
            name=n,
            slot="weapon",
            attack_styles=("magic",),
            spell_compatibility=("wind_strike", "fire_blast"),
            requirements_complete=True,
        )
        for i, n in [(1381, "Staff of air"), (1387, "Staff of fire")]
    ]
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            k: SkillState(70, None, Source.MANUAL, NOW)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", NOW)
            for i in items
        },
    )
    prices = {
        i: SimpleNamespace(
            high_price_gp=p,
            low_price_gp=p,
            high_trade_at=NOW,
            low_trade_at=NOW,
            fetched_at=NOW,
            source="live",
        )
        for i, p in [(556, 2), (554, 5), (558, 2), (560, 100)]
    }
    role = RoleConfig(
        id="mage",
        style="magic",
        combat_options=CombatOptionFilters(
            attack_types=("magic",), stances=("accurate",), spells=("wind_strike", "fire_blast")
        ),
    )
    request = OptimizationRequest(
        roles=(role,), mode="owned", max_swaps=0, **{"max_dps_loss_pct": 100, **updates}
    )
    return optimize(
        snapshot, request, SimpleNamespace(items={i.id: i for i in items}), Content(), prices, NOW
    )


def test_real_mage_frontier_retains_cheaper_spell_and_staff_savings():
    result = mage_result()
    points = result["running_cost_frontiers"][0]["points"]
    assert {p["solution"]["loadouts"]["mage"]["combat_option"]["spell"] for p in points} == {
        "wind_strike",
        "fire_blast",
    }
    assert result["selected_solution"]["loadouts"]["mage"]["combat_option"]["spell"] == "fire_blast"
    for point in points:
        loadout = point["solution"]["loadouts"]["mage"]
        assert (
            point["solution"]["running_cost"]["gp_per_attack"]
            == loadout["running_cost"]["gp_per_attack"]
        )
        assert any(r["supplied_quantity"] > 0 for r in loadout["running_cost"]["resources"])
        assert point["solution"]["secondary_value"] is None


def test_cost_cap_and_existing_secondary_are_independent():
    result = mage_result(secondary_priority="prayer_bonus", max_dps_loss_pct=0)
    assert result["secondary_frontiers"]
    assert all(p["dps_loss_pct"] == 0 for p in result["running_cost_frontiers"][0]["points"])
    assert all(
        p["solution"]["secondary_priority"] == "prayer_bonus"
        for p in result["running_cost_frontiers"][0]["points"]
    )
