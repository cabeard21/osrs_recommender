from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tests.gear.test_slayer_costs import prices
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.facts import equipment_fact
from tracker.gear.halberd_charging import CrystalChargingPolicy, charge_cost
from tracker.gear.models import EquipmentDefinition

NOW = datetime(2026, 11, 14, tzinfo=UTC)


@pytest.mark.parametrize("usable,source", [(23987, 4207), (12931, 12929)])
def test_preparation_preserves_exact_observed_forms(usable, source):
    seen = ObservedItemFact(source, Container.BANK, 1, "test", NOW)
    snapshot = AccountSnapshot(1, "test", observed_items={(source, Container.BANK): seen})
    item = EquipmentDefinition(id=usable, name="Reviewed form", slot="weapon")
    fact = equipment_fact(snapshot, item, Content(), prices({source: 100}), NOW)
    assert fact["ownership"]["status"] == "unknown"
    assert fact["planning_ownership"]["status"] == "owned"
    assert fact["preparation"]["source_item_id"] == source
    assert fact["preparation"]["charges"] == "unknown"
    assert fact["preparation"]["charging_required"] is True


def test_cost_context_follows_selected_role_duration():
    from types import SimpleNamespace

    from tracker.gear.halberd_charging import cost_context

    role = SimpleNamespace(id="r", fight_duration_seconds=180)
    request = SimpleNamespace(roles=[role], crystal_halberd_charging=CrystalChargingPolicy())
    assert cost_context(request, "r")["fight_duration_seconds"] == 180
    assert cost_context(request, role)["fight_duration_seconds"] == 180


def test_crystal_routes_and_missing_shard_valuation():
    assert charge_cost(CrystalChargingPolicy()) == 300
    assert charge_cost(CrystalChargingPolicy(coin_recharge_cost_gp=150000)) == 60
    assert charge_cost(CrystalChargingPolicy(shard_value_gp=10000)) == 100
    assert charge_cost(CrystalChargingPolicy(method="shards")) is None
    assert charge_cost(CrystalChargingPolicy(method="coins", shard_value_gp=1)) == 300


@pytest.mark.parametrize("changes", [{"coin_recharge_cost_gp": 1}, {"shard_value_gp": -1}])
def test_invalid_charge_policy(changes):
    with pytest.raises(ValidationError):
        CrystalChargingPolicy(**changes)


def test_crystal_cost_is_per_attempt_not_successful_hit():
    weapon = EquipmentDefinition(id=23987, name="Crystal halberd", slot="weapon")
    prepared = CostEvaluator({}, NOW).prepare({"weapon": weapon}, {"attack_type": "slash"})
    assert prepared.score(4.2, 10, 0).gp_per_attack == 300
    assert prepared.score(4.2, 10, 1).gp_per_attack == 300
    assert prepared.score(4.2, 10, 1).gp_per_hour == pytest.approx(300 / 4.2 * 3600)


def test_serp_head_and_duration_have_separate_cached_recipes():
    engine = CostEvaluator(prices({12934: 100}), NOW)
    weapon = EquipmentDefinition(id=29796, name="Noxious halberd", slot="weapon", attack_speed=5)
    head = EquipmentDefinition(id=12931, name="Serpentine helm", slot="head")
    option = {"attack_type": "slash"}
    ordinary = engine.prepare({"weapon": weapon}, option)
    charged = engine.prepare({"weapon": weapon, "head": head}, option)
    assert ordinary.score(3, 10).gp_per_attack == 0
    assert charged.score(3, 10).gp_per_attack == 100
    shorter = engine.prepare({"weapon": weapon, "head": head}, option, fight_duration_seconds=30)
    assert shorter.score(3, 10).gp_per_attack == 100
    boundary = engine.prepare({"weapon": weapon, "head": head}, option, fight_duration_seconds=54)
    assert boundary.score(3, 10).gp_per_attack == pytest.approx(1000 / 54 * 3)


def test_missing_shard_and_scale_prices_remain_unavailable():
    engine = CostEvaluator({}, NOW)
    weapon = EquipmentDefinition(id=23987, name="Crystal halberd", slot="weapon")
    head = EquipmentDefinition(id=12931, name="Serpentine helm", slot="head")
    assert (
        engine.prepare(
            {"weapon": weapon},
            {"attack_type": "slash"},
            crystal_halberd_charging=CrystalChargingPolicy(method="shards"),
        )
        .score(4.2, 10)
        .status
        == "unavailable"
    )
    assert (
        engine.prepare({"weapon": weapon, "head": head}, {"attack_type": "slash"})
        .score(4.2, 10)
        .status
        == "unavailable"
    )
