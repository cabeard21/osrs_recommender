from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def run(items, roles, **kwargs):
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", NOW)
            for i in items
        },
    )
    return optimize(
        snapshot,
        OptimizationRequest(roles=roles, mode="owned", **kwargs),
        SimpleNamespace(items={i.id: i for i in items}, version="test"),
        Content(),
        {},
        NOW,
    )


def weapon(id, style, strength=0, **kwargs):
    return EquipmentDefinition(
        id=id,
        name=str(id),
        slot="weapon",
        attack_styles=(style,),
        requirements_complete=True,
        bonuses=EquipmentBonuses(melee_strength=strength, ranged_strength=strength),
        **kwargs,
    )


def test_single_style_chooses_supported_better_weapon():
    result = run(
        [weapon(1, "slash"), weapon(2, "slash", 50)],
        (RoleConfig(id="melee", style="slash"),),
        max_swaps=0,
    )
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 2


def test_partial_melee_ties_retain_strength_for_a_later_max_hit_breakpoint(monkeypatch):
    # At level 70, either +3 alone still hits 8; +6 together hits 9. A bounded
    # beam must not prefer the lower IDs with zero strength during exact ties.
    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", 1)
    items = [weapon(100, "slash")]
    for slot, low, high in (("head", 10, 20), ("cape", 11, 21)):
        items.extend(
            EquipmentDefinition(
                id=item_id,
                name=str(item_id),
                slot=slot,
                requirements_complete=True,
                bonuses=EquipmentBonuses(melee_strength=strength),
            )
            for item_id, strength in ((low, 0), (high, 3))
        )
    result = run(items, (RoleConfig(id="melee", style="slash"),), max_swaps=0)
    loadout = result["selected_solution"]["loadouts"]["melee"]
    assert loadout["equipment"]["head"] == 20
    assert loadout["equipment"]["cape"] == 21
    assert loadout["performance"]["max_hit"] == 9


def test_partial_strength_preference_never_overrides_a_real_dps_improvement(monkeypatch):
    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", 1)
    items = [
        weapon(100, "slash"),
        EquipmentDefinition(
            id=10,
            name="Strength below the next hit",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(melee_strength=3),
        ),
        EquipmentDefinition(
            id=20,
            name="Actual accuracy improvement",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(slash=10),
        ),
    ]
    result = run(items, (RoleConfig(id="melee", style="slash"),), max_swaps=0)
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["head"] == 20


def test_curve_is_feasible_monotone_and_shared_cost_once():
    items = [weapon(1, "slash", 30), weapon(2, "ranged", 30)]
    roles = (RoleConfig(id="m", style="slash"), RoleConfig(id="r", style="ranged"))
    result = run(items, roles, max_swaps=3)
    feasible = [point for point in result["curve"] if point["solution"]]
    assert feasible
    assert [p["solution"]["score"] for p in feasible] == sorted(
        p["solution"]["score"] for p in feasible
    )
    for point in feasible:
        assert all(
            t["action_count"] <= point["swap_limit"] for t in point["solution"]["transitions"]
        )
    assert result["unrestricted"]["purchase_cost_gp"] == 0
    assert result["curve"][0]["solution"] is None


def test_special_partial_locks_and_custom_edges():
    items = [weapon(1, "slash"), weapon(2, "slash", 50)]
    roles = (
        RoleConfig(id="m", style="slash"),
        RoleConfig(id="s", style="special", parent_role="m", locks={"weapon": 1}),
    )
    solution = run(items, roles, max_swaps=1)["selected_solution"]
    assert solution["loadouts"]["s"]["equipment"]["weapon"] == 1
    assert solution["loadouts"]["s"]["performance"]["dps"] is None
    assert len(solution["transitions"]) == 2


def test_request_validates_limits_and_conflicting_locks():
    with pytest.raises(ValueError):
        OptimizationRequest(roles=(RoleConfig(id="m", style="slash"),), max_swaps=13)
    with pytest.raises(ValueError):
        OptimizationRequest(
            roles=(RoleConfig(id="m", style="slash", locks={"weapon": 1}),), locks={"weapon": 2}
        )


def test_budget_counts_union_purchase_once_and_unknown_owned_is_not_free(make_content, make_item):
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    item = weapon(1, "slash", 30, tradeable=True)
    content = make_content(items=[make_item("test_sword", numeric_id=1)])
    price = PriceDTO(
        item_id=1,
        high_price_gp=100,
        high_trade_at=NOW,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=NOW,
        source=PriceSource.LIVE,
        provider="test",
    )
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={key: SkillState(70, None, Source.MANUAL, NOW) for key in ("attack", "strength")},
    )
    roles = (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="slash"))
    result = optimize(
        snapshot,
        OptimizationRequest(roles=roles, budget_gp=100, max_swaps=0),
        SimpleNamespace(items={1: item}),
        content,
        {1: price},
        NOW,
    )
    assert result["selected_solution"]["purchase_cost_gp"] == 100
    assert len(result["selected_solution"]["purchases"]) == 1
    assert result["selected_solution"]["purchases"][0]["conditional"]
    no_budget = optimize(
        snapshot,
        OptimizationRequest(roles=roles, budget_gp=99, max_swaps=0),
        SimpleNamespace(items={1: item}),
        content,
        {1: price},
        NOW,
    )
    assert no_budget["selected_solution"] is None


def test_mixed_shared_gear_improves_with_three_actions():
    items = [weapon(1, "slash", 30), weapon(2, "ranged", 30)]
    for offset, slot in enumerate(("head", "body", "legs")):
        items.extend(
            [
                EquipmentDefinition(
                    id=10 + offset,
                    name=f"melee {slot}",
                    slot=slot,
                    requirements_complete=True,
                    bonuses=EquipmentBonuses(melee_strength=40),
                ),
                EquipmentDefinition(
                    id=20 + offset,
                    name=f"ranged {slot}",
                    slot=slot,
                    requirements_complete=True,
                    bonuses=EquipmentBonuses(ranged_strength=40),
                ),
            ]
        )
    roles = (RoleConfig(id="m", style="slash"), RoleConfig(id="r", style="ranged"))
    result = run(items, roles, max_swaps=4)
    one = result["curve"][1]["solution"]
    three = result["curve"][3]["solution"]
    four = result["curve"][4]["solution"]
    assert one and three and four
    assert one["score"] < three["score"] < four["score"]
    assert all(t["action_count"] <= 3 for t in three["transitions"])


def test_special_unsupported_effect_is_not_approximated_as_damage():
    items = [
        weapon(1, "slash"),
        weapon(2, "slash", 50, unsupported_effects=("unmodeled special utility",)),
    ]
    roles = (
        RoleConfig(id="m", style="slash"),
        RoleConfig(id="s", style="special", parent_role="m", locks={"weapon": 2}),
    )
    result = run(items, roles, max_swaps=1)
    assert result["selected_solution"]["loadouts"]["s"]["equipment"]["weapon"] == 2
    assert result["selected_solution"]["loadouts"]["m"]["equipment"]["weapon"] == 1


def test_mappings_are_deep_frozen_and_request_serializes():
    source = {"weapon": 1}
    role = RoleConfig(id="m", style="slash", locks=source)
    source["weapon"] = 2
    assert role.locks["weapon"] == 1
    with pytest.raises(TypeError):
        role.locks["weapon"] = 2
    request = OptimizationRequest(roles=(role,))
    assert request.model_dump(mode="json")["roles"][0]["locks"] == {"weapon": 1}


def test_ordered_edges_do_not_force_all_pairwise():
    from tracker.gear.optimizer import required_transitions

    roles = tuple(RoleConfig(id=name, style="slash") for name in ("a", "b", "c"))
    assert required_transitions(
        OptimizationRequest(roles=roles, ordered_roles=("a", "b", "c"))
    ) == (("a", "b"), ("b", "c"))


def test_special_transitions_follow_parent_not_unrelated_base():
    from tracker.gear.optimizer import required_transitions

    roles = (
        RoleConfig(id="base", style="slash"),
        RoleConfig(id="r", style="ranged"),
        RoleConfig(id="spec", style="special", parent_role="r", locks={"weapon": 1}),
    )
    request = OptimizationRequest(roles=roles)
    assert set(required_transitions(request)) == {
        ("base", "r"),
        ("r", "base"),
        ("r", "spec"),
        ("spec", "r"),
    }
    ordered = request.model_copy(update={"ordered_roles": ("base", "spec", "r")})
    assert required_transitions(ordered) == (("base", "spec"), ("spec", "r"))


def test_cancelled_and_changed_snapshot():
    with pytest.raises(ValueError, match="snapshot_changed"):
        optimize(
            AccountSnapshot(1, "test"),
            OptimizationRequest(
                roles=(RoleConfig(id="m", style="slash"),), expected_snapshot_id="old"
            ),
            SimpleNamespace(items={}),
            Content(),
            {},
            NOW,
        )
    with pytest.raises(ValueError, match="optimization_cancelled"):
        optimize(
            AccountSnapshot(1, "test"),
            OptimizationRequest(roles=(RoleConfig(id="m", style="slash"),)),
            SimpleNamespace(items={}),
            Content(),
            {},
            NOW,
            cancelled=lambda: True,
        )


def test_wrong_slot_and_unknown_locks_fail_before_search():
    for locked_id, message in ((1, "does not occupy"), (999, "unknown locked")):
        with pytest.raises(ValueError, match=message):
            run(
                [weapon(1, "slash")],
                (RoleConfig(id="m", style="magic"),),
                locks={"body": locked_id},
            )
    with pytest.raises(ValueError):
        RoleConfig(id="m", style="slash", locks={"weapon": True})


def test_unscored_only_or_special_parent_cycles_are_rejected():
    with pytest.raises(ValueError, match="scored role"):
        OptimizationRequest(
            roles=(
                RoleConfig(id="a", style="special", parent_role="b", locks={"weapon": 1}),
                RoleConfig(id="b", style="special", parent_role="a", locks={"weapon": 2}),
            )
        )


def test_small_joint_search_matches_independent_exhaustive_assignments():
    from itertools import product

    from tracker.gear.combat import evaluate_loadout

    items = [
        weapon(1, "slash", 30),
        weapon(2, "ranged", 30),
        EquipmentDefinition(
            id=10,
            name="Melee helm",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(melee_strength=40),
        ),
        EquipmentDefinition(
            id=20,
            name="Ranged helm",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(ranged_strength=40),
        ),
    ]
    roles = (
        RoleConfig(id="m", style="slash", locks={"weapon": 1}),
        RoleConfig(id="r", style="ranged", locks={"weapon": 2}),
    )
    result = run(items, roles, max_swaps=2)
    catalog = {i.id: i for i in items}
    levels = {"attack": 70, "strength": 70, "ranged": 70}
    for limit in (1, 2):
        scores = []
        for head_m, head_r in product((None, 10, 20), repeat=2):
            if 1 + (head_m != head_r) > limit:
                continue
            setups = [{"weapon": catalog[1]}, {"weapon": catalog[2]}]
            for setup, head in zip(setups, (head_m, head_r), strict=True):
                if head is not None:
                    setup["head"] = catalog[head]
            scores.append(
                sum(evaluate_loadout(s, r, levels).dps for s, r in zip(setups, roles, strict=True))
                / 2
            )
        assert result["curve"][limit]["solution"]["score"] == pytest.approx(max(scores))


def test_node_budget_and_zero_normalization_are_honest(monkeypatch):
    import tracker.gear.optimizer as module

    zero_roll = weapon(1, "slash", -64).model_copy(
        update={"bonuses": EquipmentBonuses(slash=-64, melee_strength=-64)}
    )
    result = run([zero_roll], (RoleConfig(id="m", style="slash"),), max_swaps=0)
    assert result["selected_solution"]["score"] == 0
    assert result["curve"][0]["relative_performance"] is None
    monkeypatch.setattr(module, "MAX_EXPANSIONS", 10)
    bounded = run([weapon(1, "slash")], (RoleConfig(id="m", style="slash"),), max_swaps=1)
    assert bounded["search"]["explored_nodes"] == 10
    assert bounded["search"]["termination_reason"] == "node_limit"
    assert bounded["search"]["quality"] == "best_found"


def test_future_assumptions_are_explicit_and_snapshot_is_unchanged(make_content):
    from tracker.content.requirements import SkillLeaf

    content = make_content()
    item = weapon(1, "slash", requires=SkillLeaf(skill="attack", level=60))
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            "attack": SkillState(59, None, Source.MANUAL, NOW),
            "strength": SkillState(70, None, Source.MANUAL, NOW),
        },
        observed_items={(1, Container.BANK): ObservedItemFact(1, Container.BANK, 1, "test", NOW)},
    )
    roles = (RoleConfig(id="m", style="slash"),)
    result = optimize(
        snapshot,
        OptimizationRequest(
            roles=roles, mode="future", skill_overrides={"attack": 60}, max_swaps=0
        ),
        SimpleNamespace(items={1: item}),
        content,
        {},
        NOW,
    )
    assert result["selected_solution"]
    assert result["snapshot_id"] == snapshot.fingerprint
    assert snapshot.skills["attack"].level == 59
    with pytest.raises(ValueError, match="unknown skill"):
        optimize(
            snapshot,
            OptimizationRequest(roles=roles, mode="future", skill_overrides={"invented": 99}),
            SimpleNamespace(items={1: item}),
            content,
            {},
            NOW,
        )


def test_contextual_slot_alternatives_keep_surrounding_constraints():
    items = [
        weapon(1, "slash", 30),
        weapon(2, "slash", 20),
        weapon(3, "slash", 60, two_handed=True),
        EquipmentDefinition(id=4, name="Shield", slot="shield", requirements_complete=True),
    ]
    result = run(items, (RoleConfig(id="m", style="slash", locks={"shield": 4}),), max_swaps=0)
    rows = result["alternatives"]["weapon"]
    assert [row["item_id"] for row in rows] == [2]
    assert rows[0]["score_delta"] < 0
    assert result["alternatives"]["shield"] == []
    assert 2 in {item["item_id"] for item in result["items"]}


def test_contextual_alternatives_do_not_exceed_budget(make_content, make_item):
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    items = [weapon(1, "slash", 30, tradeable=True), weapon(2, "slash", 20, tradeable=True)]
    content = make_content(items=[make_item(f"sword_{i}", numeric_id=i) for i in (1, 2)])
    prices = {
        i: PriceDTO(i, cost, NOW, None, None, "test", NOW, PriceSource.LIVE)
        for i, cost in ((1, 100), (2, 101))
    }
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={key: SkillState(70, None, Source.MANUAL, NOW) for key in ("attack", "strength")},
    )
    result = optimize(
        snapshot,
        OptimizationRequest(roles=(RoleConfig(id="m", style="slash"),), budget_gp=100, max_swaps=0),
        SimpleNamespace(items={i.id: i for i in items}),
        content,
        prices,
        NOW,
    )
    assert result["selected_solution"]["purchase_cost_gp"] == 100
    assert result["alternatives"]["weapon"] == []
