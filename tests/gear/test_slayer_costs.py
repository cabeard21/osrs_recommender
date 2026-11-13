from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container
from tracker.gear.compact_costs import CostEvaluator, compact_running_costs
from tracker.gear.facts import equipment_fact
from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import evaluate_running_cost, resource_item_ids

NOW = datetime(2026, 11, 13, tzinfo=UTC)
OPTION = {"attack_type": "magic", "spell": "magic_dart"}


def prices(values):
    return {
        i: SimpleNamespace(
            high_price_gp=v,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source="live",
        )
        for i, v in values.items()
    }


def equipment(enchanted=True):
    return {
        "weapon": EquipmentDefinition(
            id=21255 if enchanted else 4170, name="Slayer staff", slot="weapon"
        ).model_copy(update={"slayer_staff_enchanted": enchanted})
    }


@pytest.mark.parametrize("accuracy", [0, 0.25, 1])
def test_enchantment_expected_consumption_matches_compact(accuracy):
    records = prices({560: 100, 558: 2, 21257: 2500})
    performance = {"attack_interval": 3, "dps": 5, "accuracy": accuracy}
    result = evaluate_running_cost(
        equipment(), OPTION, performance, records, NOW, on_slayer_task=True
    )
    assert result["gp_per_attack"] == 108 + accuracy
    charge = next(r for r in result["resources"] if r["item_id"] == 21257)
    assert charge["consumed_quantity"] == accuracy / 2500
    with compact_running_costs():
        assert (
            evaluate_running_cost(
                equipment(), OPTION, performance, records, NOW, on_slayer_task=True
            )
            == result
        )


def test_only_enchanted_on_task_magic_dart_uses_enchantment():
    engine = CostEvaluator(prices({560: 100, 558: 2}), NOW)
    for equipped, on_task in [(equipment(), False), (equipment(False), True)]:
        prepared = engine.prepare(equipped, OPTION, on_slayer_task=on_task)
        assert prepared.score(3, 5, 0.5).gp_per_attack == 108
    prepared = engine.prepare(equipment(), OPTION, on_slayer_task=True)
    assert prepared.score(3, 5, 0.5).status == "unavailable"
    assert prepared.score(3, 5, 0.5).gp_per_attack is None
    assert 21257 in resource_item_ids()


def test_enchanting_preparation_preserves_observed_ownership_and_base_price():
    seen = ObservedItemFact(4170, Container.BANK, 1, "test", NOW)
    snapshot = AccountSnapshot(1, "test", observed_items={(4170, Container.BANK): seen})
    fact = equipment_fact(snapshot, equipment()["weapon"], Content(), prices({4170: 1000}), NOW)
    assert fact["ownership"]["status"] == "unknown"
    assert fact["planning_ownership"]["status"] == "owned"
    assert fact["preparation"]["source_item_id"] == 4170
    assert fact["preparation"]["market_item_id"] == 4170
    assert fact["preparation"]["charges"] == "unknown"
    assert fact["price"]["amount_gp"] == 1000


def test_task_context_is_retained_in_deferred_solution_costs():
    from tracker.gear.running_frontier import add_solution_costs
    from tracker.gear.variant_reporting import materialize

    class Search:
        pass

    search = Search()
    search.items = {21255: equipment()["weapon"]}
    search.request = SimpleNamespace(
        roles=tuple(
            SimpleNamespace(id=rid, style="magic", weight=1, on_slayer_task=task)
            for rid, task in [("on", True), ("off", False)]
        )
    )
    search.running_prices = prices({560: 100, 558: 2, 21257: 2500})
    search.running_at = NOW
    search.compact_cost_ranking = True
    loadout = {
        "equipment": {"weapon": 21255},
        "combat_option": OPTION,
        "performance": {"supported": True, "attack_interval": 3, "dps": 5, "accuracy": 0.25},
    }
    solution = {"loadouts": {"on": loadout, "off": loadout}}
    rich = add_solution_costs(solution, search)
    with compact_running_costs():
        assert materialize(add_solution_costs(solution, search)) == rich
    assert rich["loadouts"]["on"]["running_cost"]["gp_per_attack"] == 108.25
    assert rich["loadouts"]["off"]["running_cost"]["gp_per_attack"] == 108


def test_expected_enchantment_cost_requires_accuracy():
    result = evaluate_running_cost(
        equipment(),
        OPTION,
        {"attack_interval": 3, "dps": 5},
        prices({560: 100, 558: 2, 21257: 2500}),
        NOW,
        on_slayer_task=True,
    )
    assert result["status"] == "unavailable"
    assert result["gp_per_attack"] is None
    assert any("Accuracy" in reason for reason in result["reasons"])
