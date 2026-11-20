from datetime import UTC, datetime

import pytest

from tests.gear.test_wilderness import quote
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import evaluate_running_cost, resource_item_ids
from tracker.gear.wilderness import WildernessPolicy, WildernessRisk

NOW = datetime(2026, 11, 20, tzinfo=UTC)


@pytest.mark.parametrize(
    "weapon_id,option,interval,ether",
    [
        (22545, {"attack_type": "stab"}, 2.4, 1),
        (27660, {"attack_type": "crush"}, 2.4, 1),
        (22542, {"attack_type": "stab"}, 2.4, 0),
        (27657, {"attack_type": "crush"}, 2.4, 0),
        (22550, {"attack_type": "ranged"}, 1.8, 1),
        (27655, {"attack_type": "ranged"}, 2.4, 1),
        (22555, {"attack_type": "magic", "powered_attack": "thammaron"}, 2.4, 1),
        (27665, {"attack_type": "magic", "powered_attack": "accursed"}, 2.4, 1),
        (27788, {"attack_type": "magic", "spell": "wind_strike"}, 3.0, 1),
        (27679, {"attack_type": "magic", "spell": "wind_strike"}, 3.0, 1),
        (27785, {"attack_type": "magic", "spell": "wind_strike"}, 3.0, 0),
        (27676, {"attack_type": "magic", "spell": "wind_strike"}, 3.0, 0),
    ],
)
@pytest.mark.parametrize("priced", [True, False])
def test_exact_form_costs(weapon_id, option, interval, ether, priced):
    records = {i: quote(i, 4, NOW) for i in (556, 558)}
    if priced:
        records[21820] = quote(21820, 100, NOW)
    equipment = {
        "weapon": EquipmentDefinition(id=weapon_id, name="Weapon", slot="weapon"),
        "cape": EquipmentDefinition(id=10499, name="Ava's accumulator", slot="cape"),
    }
    engine = CostEvaluator(records, NOW)
    report = evaluate_running_cost(
        equipment, option, {"dps": 2.5, "accuracy": 0, "attack_interval": interval}, records, NOW
    )
    recipe = engine.prepare(equipment, option)
    assert report == recipe.report(recipe.score(interval, 2.5, 0), 0, interval=interval)
    quantities = {r["item_id"]: r["consumed_quantity"] for r in report["resources"]}
    assert quantities == {
        **({556: 1, 558: 1} if option.get("spell") else {}),
        **({21820: 1} if ether else {}),
    }
    if not priced and ether:
        assert report["status"] == "unavailable"
        assert report["gp_per_hour"] is None
        return
    per_attack = ether * 100 + (8 if option.get("spell") else 0)
    assert report["gp_per_attack"] == per_attack
    assert report["gp_per_hour"] == pytest.approx(per_attack * 3600 / interval)
    assert report["gp_per_damage"] == pytest.approx(per_attack / (interval * 2.5))


def test_resource_price_sync_includes_all_revenant_market_forms():
    assert resource_item_ids() >= {22542, 27657, 22547, 27652, 22552, 27662, 27785, 27676, 21820}


@pytest.mark.parametrize("priced", [False, True])
@pytest.mark.parametrize(
    "weapon_id, style, stance", [(22550, "ranged", "rapid"), (27660, "crush", "accurate")]
)
def test_native_cost_uses_ether_per_attempt(weapon_id, style, stance, priced):
    from tests.gear.test_native_effect_costs import assert_cost_projection, cost_scorer
    from tests.gear.test_native_stages import stage_search
    from tracker.gear.models import EquipmentBonuses
    from tracker.gear.optimizer import RoleConfig

    with stage_search() as search:
        weapon = EquipmentDefinition(
            id=weapon_id,
            name="Weapon",
            slot="weapon",
            attack_styles=(style,),
            attack_profiles=((style, stance),),
            attack_speed=4,
            bonuses=EquipmentBonuses(ranged=90, ranged_strength=90, crush=90, melee_strength=90),
        )
        cape = EquipmentDefinition(id=10499, slot="cape", name="Accumulator")
        search.items = {item.id: item for item in (weapon, cape)}
        search.eligible = search.items
        search.facts = dict.fromkeys(search.items, search.facts[2])
        search.request = search.request.model_copy(
            update={"roles": (RoleConfig(id="z", style=style, stance=stance),)}
        )
        search.running_at = NOW
        search.running_prices = {21820: quote(21820, 100, NOW)} if priced else {}
        scoring = cost_scorer(search)
        assert_cost_projection(search, scoring, {"weapon": weapon_id, "cape": 10499})


def test_ready_charged_and_empty_maces_each_count_for_python_and_native_risk():
    from tests.gear.test_native_stages import ScoringContext, StageContext, drain, stage_search
    from tracker.gear.models import EquipmentBonuses
    from tracker.gear.optimizer import RoleConfig

    with stage_search(multiple=True) as search:
        search.items = {
            i: EquipmentDefinition(
                id=i,
                name="Mace",
                slot="weapon",
                attack_styles=("crush",),
                attack_profiles=(("crush", "accurate"),),
                tradeable=(i == 22542),
                bonuses=EquipmentBonuses(crush=90, melee_strength=90),
            )
            for i in (22542, 22545)
        }
        search.eligible = search.items
        search.facts = dict.fromkeys(search.items, search.facts[2])
        policy = WildernessPolicy(skulled=True, max_loss_gp=101001)
        search.request = search.request.model_copy(
            update={
                "wilderness": policy,
                "roles": tuple(
                    RoleConfig(id=r, style="crush", stance="accurate") for r in ("z", "a")
                ),
            }
        )
        risk = WildernessRisk.build(
            policy,
            policy.max_loss_gp,
            search.items,
            {},
            {22542: quote(22542, 100000, NOW), 21820: quote(21820, 1, NOW)},
            NOW,
        )
        search.wilderness = risk
        assert not risk.feasible({22542, 22545})
        assert risk.lower_bound({22542, 22545}) == 201001
        assignment = {"z": {"weapon": 22545}, "a": {"weapon": 22542}}
        assert risk.report(assignment)["loss_gp"] == 201001
        context = StageContext(ScoringContext(search), search)
        rows, _ = drain(
            context.begin(
                kind="joint",
                states=[{"z": {}, "a": {}}],
                choices=[[22545], [22542]],
                slot="weapon",
                roles=("z", "a"),
            ),
            16,
        )
        assert rows == []


def test_distinct_ready_sceptre_modes_use_separate_reserves():
    attacks = 8001
    forms = (22555, 27788)
    items = {i: EquipmentDefinition(id=i, name="Sceptre", slot="weapon") for i in forms}
    records = {i: quote(i, 1, NOW) for i in (22552, 27785, 21820, 556, 558)}
    risk = WildernessRisk.build(
        WildernessPolicy(attacks_per_setup=attacks), None, items, {}, records, NOW
    )
    result = risk.trip_report(
        {"powered": {"weapon": 22555}, "cast": {"weapon": 27788}},
        {
            "powered": {"attack_type": "magic", "powered_attack": "thammaron"},
            "cast": {"attack_type": "magic", "spell": "wind_strike"},
        },
        items,
        styles={"powered": "magic", "cast": "magic"},
    )
    assert result["loss_gp"] is not None
    assert {
        row["item_id"]: row["quantity"]
        for row in result["quantities"]
        if row["resource_id"] == 21820
    } == {22555: 9001, 27788: 9001}
    assert sum(row["quantity"] for row in result["items"] if row["item_id"] in forms) == 2


@pytest.mark.parametrize("charged,empty,alternate", [(27788, 27785, 22552), (27679, 27676, 27662)])
def test_death_values_exact_sceptre_state_independently_of_cheaper_acquisition(
    charged, empty, alternate
):
    items = {
        i: EquipmentDefinition(id=i, slot="weapon", name="Sceptre", tradeable=i == empty)
        for i in (charged, empty)
    }
    records = {i: quote(i, gp, NOW) for i, gp in [(empty, 100), (alternate, 20), (21820, 10)]}
    facts = {i: {"price": {"amount_gp": 20}} for i in items}
    risk = WildernessRisk.build(WildernessPolicy(skulled=True), None, items, facts, records, NOW)
    assert risk.rules[charged].unprotected_loss_gp == 100
    assert risk.rules[empty].unprotected_loss_gp == 100
