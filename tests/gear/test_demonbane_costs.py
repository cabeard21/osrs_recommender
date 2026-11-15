from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import evaluate_running_cost

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def prices():
    return {
        i: SimpleNamespace(
            high_price_gp=p,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source="live",
        )
        for i, p in {554: 2, 562: 10, 566: 100, 564: 50, 732: 12}.items()
    }


@pytest.mark.parametrize("weapon, multiplier", [(29594, 5), (4170, 1)])
def test_mark_upkeep_is_time_based_and_resources_match(weapon, multiplier):
    equipment = {"weapon": EquipmentDefinition(id=weapon, name="Staff", slot="weapon")}
    option = {"attack_type": "magic", "spell": "dark_demonbane"}
    prepared = CostEvaluator(prices(), NOW).prepare(
        equipment, option, mark_of_darkness=True, base_magic=90
    )
    for interval in (2.4, 3):
        result = evaluate_running_cost(
            equipment,
            option,
            {"attack_interval": interval, "dps": 5, "accuracy": 0.8},
            prices(),
            NOW,
            mark_of_darkness=True,
            base_magic=90,
        )
        expected = 214 / interval + 150 / (162 * multiplier)
        assert result["gp_per_second"] == pytest.approx(expected)
        assert prepared.score(interval, 5, 0.8).gp_per_second == result["gp_per_second"]
        assert sum(
            r["consumed_quantity"] * r["unit_price_gp"] for r in result["resources"]
        ) == pytest.approx(result["gp_per_attack"])


def test_mark_does_not_apply_to_other_attacks():
    evaluator = CostEvaluator(prices(), NOW)
    option = {"attack_type": "magic", "spell": "fire_strike"}
    assert evaluator.prepare({}, option, mark_of_darkness=True, base_magic=90) == evaluator.prepare(
        {}, option
    )


def test_arclight_charge_cost_is_unavailable_but_consumption_is_reported():
    equipment = {"weapon": EquipmentDefinition(id=19675, name="Arclight", slot="weapon")}
    result = evaluate_running_cost(
        equipment,
        {"attack_type": "slash"},
        {"attack_interval": 2.4, "dps": 5, "accuracy": 0.8},
        {},
        NOW,
    )
    assert result["status"] == "unavailable"
    assert result["gp_per_attack"] is None
    shard = result["resources"][0]
    assert shard["item_id"] == 19677
    assert shard["consumed_quantity"] == pytest.approx(0.8 * 3 / 1000)
    assert "actual charges unknown" in result["charging_assumption"]


def test_holy_water_is_destroyed_even_with_unknown_ava_body():
    equipment = {
        "weapon": EquipmentDefinition(id=732, name="Holy water", slot="weapon"),
        "cape": EquipmentDefinition(id=22109, name="Ava's assembler", slot="cape"),
        "body": EquipmentDefinition(id=999999, name="Unreviewed", slot="body"),
    }
    result = evaluate_running_cost(
        equipment, {"attack_type": "light"}, {"attack_interval": 1.8, "dps": 2}, prices(), NOW
    )
    assert result["status"] == "known"
    assert result["gp_per_attack"] == 12
    assert result["resources"][0]["consumed_quantity"] == 1


def test_mark_missing_price_and_base_magic_are_not_free():
    option = {"attack_type": "magic", "spell": "inferior_demonbane"}
    missing = {i: row for i, row in prices().items() if i != 564}
    evaluator = CostEvaluator(missing, NOW)
    assert (
        evaluator.prepare({}, option, mark_of_darkness=True, base_magic=90).score(3, 5).status
        == "unavailable"
    )
    assert evaluator.prepare({}, option, mark_of_darkness=True).score(3, 5).status == "unavailable"
    assert evaluator.prepare({}, option).score(3, 5).status == "known"


def test_mark_cache_identity_includes_base_magic_and_preference():
    evaluator = CostEvaluator(prices(), NOW)
    option = {"attack_type": "magic", "spell": "superior_demonbane"}
    off = evaluator.prepare({}, option)
    first = evaluator.prepare({}, option, mark_of_darkness=True, base_magic=90)
    second = evaluator.prepare({}, option, mark_of_darkness=True, base_magic=45)
    assert first.per_second_cost * 2 == second.per_second_cost
    assert off.per_second_cost == 0
    assert evaluator.prepare({}, option, mark_of_darkness=True, base_magic=90) is first


def test_native_cost_packing_includes_mark_rate_and_holy_water_destruction():
    from tracker.gear.combat_options import CombatOption
    from tracker.gear.native.cost_context import pack_costs

    items = {i: EquipmentDefinition(id=i, name=str(i), slot="weapon") for i in (29594, 732)}
    search = SimpleNamespace(
        items=items,
        running_prices=prices(),
        running_at=NOW,
        snapshot=SimpleNamespace(skills={"magic": SimpleNamespace(level=90)}),
    )
    scoring = SimpleNamespace(
        dense_ids=(0, 29594, 732),
        option_weapons=(29594,),
        option_records=(
            (
                SimpleNamespace(mark_of_darkness=True),
                CombatOption(attack_type="magic", stance="accurate", spell="dark_demonbane"),
            ),
        ),
    )
    packed = pack_costs(search, scoring)
    assert packed.option_per_second_cost[0] == pytest.approx(150 / 810)
    assert packed.option_cost[0] == 214
    assert packed.ranged_kind[2] == 3
