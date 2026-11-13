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


def test_running_cost_activation_covers_ranged_magic_auto_and_multi():
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig
    from tracker.gear.running_frontier import needs_running_cost_frontier

    for style in ("ranged", "magic"):
        assert needs_running_cost_frontier(
            OptimizationRequest(roles=(RoleConfig(id="a", style=style),))
        )
    assert not needs_running_cost_frontier(
        OptimizationRequest(roles=(RoleConfig(id="a", style="slash"),))
    )
    assert needs_running_cost_frontier(
        OptimizationRequest(
            roles=(RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="ranged"))
        )
    )
    from types import SimpleNamespace

    assert needs_running_cost_frontier(
        SimpleNamespace(
            roles=(SimpleNamespace(style="slash", allowed_disciplines=("melee", "ranged")),)
        )
    )

    assert not needs_running_cost_frontier(
        SimpleNamespace(roles=(SimpleNamespace(style="magic", allowed_disciplines=("melee",)),))
    )


def test_cost_scaffolds_keep_every_context_after_first_eight():
    from types import SimpleNamespace

    from tracker.gear.running_frontier import cost_scaffolds

    bases = [{"weapon": i, "ammunition": 100 + i} for i in range(12)]
    original = SimpleNamespace(baselines=lambda role: [*bases, bases[0]])
    assert cost_scaffolds(original, object()) == bases


def test_real_ranged_frontier_is_automatic_and_retains_cheaper_ammunition():
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
        ),
        SimpleNamespace(items={i.id: i for i in items}),
        Content(),
        prices,
        NOW,
    )
    group = result["running_cost_frontiers"][0]
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
        ),
        SimpleNamespace(items={i.id: i for i in items}),
        Content(),
        prices,
        NOW,
    )
    group = result["running_cost_frontiers"][0]
    cheapest = min(group["points"], key=lambda p: p["solution"]["running_cost"]["gp_per_damage"])
    assert cheapest["solution"]["loadouts"]["r"]["equipment"] == {
        "weapon": 10011,
        "ammunition": 893,
    }
