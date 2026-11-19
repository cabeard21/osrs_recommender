"""Running cost composes with other objectives and uses known resource prices."""

from tracker.gear.running_frontier import aggregate_cost


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


def mage_result(*, missing_price_ids=(), **updates):
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
        if i not in missing_price_ids
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
    result = mage_result(objectives=[{"kind": "gp_per_damage"}])
    points = result["objective_frontiers"][0]["points"]
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


def test_unpriced_fire_blast_remains_the_selected_dps_baseline():
    from tracker.gear.objective_store import close_result_archives

    for missing, cap, expect_points in [
        ((560,), 100, True),
        ((560,), 0, False),
        ((558, 560), 100, False),
    ]:
        result = mage_result(
            missing_price_ids=missing, objectives=[{"kind": "gp_per_damage"}], max_dps_loss_pct=cap
        )
        try:
            winner = result["selected_solution"]
            assert winner["loadouts"]["mage"]["combat_option"]["spell"] == "fire_blast"
            assert winner["running_cost"]["status"] == "unavailable"
            assert "gp_per_damage" not in winner["objective_values"]
            for group in result["objective_frontiers"]:
                assert group["baseline_solution"] == winner
                assert group["baseline_dps"] == winner["score"]
                assert bool(group["points"]) == expect_points
                for point in group["points"]:
                    assert (
                        point["solution"]["loadouts"]["mage"]["combat_option"]["spell"]
                        == "wind_strike"
                    )
                    assert point["dps_loss"] == winner["score"] - point["solution"]["score"]
        finally:
            close_result_archives({"result": result})


def test_only_selected_objectives_receive_search_work():
    for settings in (
        {},
        {"objectives": []},
        {"objectives": [{"kind": "prayer_bonus"}]},
        {"secondary_priority": "prayer_bonus"},
    ):
        result = mage_result(**settings)
        assert result["running_cost_frontiers"] == []
        assert not result["search"].get("running_cost_frontier")
        assert result["selected_solution"]["running_cost"]["gp_per_damage"] > 0


def test_cost_cap_applies_to_combined_objective_search():
    result = mage_result(
        objectives=[{"kind": "prayer_bonus"}, {"kind": "gp_per_damage"}], max_dps_loss_pct=0
    )
    points = result["objective_frontiers"][0]["points"]
    assert points and all(p["dps_loss_pct"] == 0 for p in points)
    for point in points:
        solution = point["solution"]
        assert (
            solution["objective_values"]["gp_per_damage"]
            == solution["running_cost"]["gp_per_damage"]
        )
        assert "prayer_bonus" in solution["objective_values"]


def test_ranged_cost_objective_retains_cheaper_ammunition():
    from types import SimpleNamespace

    from tests.gear.test_optimizer import NOW, weapon
    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

    items = [weapon(806, "ranged", 1), weapon(811, "ranged", 40)]
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={"ranged": SkillState(70, None, Source.MANUAL, NOW)},
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", NOW)
            for i in items
        },
    )
    prices = {
        i: SimpleNamespace(
            high_price_gp=gp,
            low_price_gp=gp,
            high_trade_at=NOW,
            low_trade_at=NOW,
            fetched_at=NOW,
            source="live",
        )
        for i, gp in [(806, 1), (811, 100)]
    }
    result = optimize(
        snapshot,
        OptimizationRequest(
            roles=(RoleConfig(id="ranged", style="ranged"),),
            mode="owned",
            max_swaps=0,
            max_dps_loss_pct=100,
            objectives=[{"kind": "gp_per_damage"}],
        ),
        SimpleNamespace(items={i.id: i for i in items}),
        Content(),
        prices,
        NOW,
    )
    group = result["objective_frontiers"][0]
    assert {
        p["solution"]["loadouts"]["ranged"]["equipment"]["weapon"] for p in group["points"]
    } == {806, 811}
    assert result["selected_solution"]["loadouts"]["ranged"]["equipment"]["weapon"] == 811


def test_cost_search_retains_cheap_compatible_context_beyond_first_eight():
    from types import SimpleNamespace

    from tests.gear.test_optimizer import NOW, weapon
    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.models import EquipmentDefinition
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

    items = []
    prices = {}
    for index in range(12):
        ammo_id = 882 + index
        ammo_type = f"arrow:{ammo_id}"
        items.extend(
            (
                weapon(10000 + index, "ranged", 60 - index * 3, ammo_for=(ammo_type,)),
                EquipmentDefinition(
                    id=ammo_id,
                    name=f"Ammo {index}",
                    slot="ammunition",
                    ammo_type=ammo_type,
                    requirements_complete=True,
                ),
            )
        )
        gp = 1 if index == 11 else 1000
        prices[ammo_id] = SimpleNamespace(
            high_price_gp=gp,
            low_price_gp=gp,
            high_trade_at=NOW,
            low_trade_at=NOW,
            fetched_at=NOW,
            source="live",
        )
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={"ranged": SkillState(70, None, Source.MANUAL, NOW)},
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", NOW)
            for i in items
        },
    )
    result = optimize(
        snapshot,
        OptimizationRequest(
            roles=(RoleConfig(id="r", style="ranged"),),
            mode="owned",
            max_swaps=0,
            max_dps_loss_pct=100,
            objectives=[{"kind": "gp_per_damage"}],
        ),
        SimpleNamespace(items={i.id: i for i in items}),
        Content(),
        prices,
        NOW,
    )
    group = result["objective_frontiers"][0]
    cheapest = min(group["points"], key=lambda p: p["solution"]["running_cost"]["gp_per_damage"])
    assert cheapest["solution"]["loadouts"]["r"]["equipment"] == {
        "weapon": 10011,
        "ammunition": 893,
    }
