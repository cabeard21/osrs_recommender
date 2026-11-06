from datetime import UTC, datetime
from types import SimpleNamespace

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container
from tracker.gear.facts import equipment_fact, observed_ownership
from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import evaluate_running_cost, resource_item_ids

NOW = datetime(2026, 11, 5, tzinfo=UTC)


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


def test_uncharged_ownership_is_a_disclosed_preparation_not_an_observation():
    seen = ObservedItemFact(28583, Container.BANK, 1, "test", NOW)
    snapshot = AccountSnapshot(1, "test", observed_items={(28583, Container.BANK): seen})
    item = EquipmentDefinition(id=28585, name="Warped sceptre", slot="weapon")
    fact = equipment_fact(snapshot, item, Content(), {}, NOW)
    assert observed_ownership(snapshot, 28585)["status"] == "unknown"
    assert fact["ownership"]["status"] == "unknown"
    assert fact["planning_ownership"]["status"] == "owned"
    assert fact["preparation"]["source_item_id"] == 28583
    assert fact["preparation"]["charging_required"] is True
    assert fact["preparation"]["charges"] == "unknown"


def test_powered_market_route_prices_the_uncharged_weapon():
    item = EquipmentDefinition(id=27275, name="Tumeken's shadow", slot="weapon")
    fact = equipment_fact(AccountSnapshot(1, "test"), item, Content(), prices({27277: 123}), NOW)
    assert fact["price"]["amount_gp"] == 123
    assert fact["acquisition"] == "tradeable"
    assert fact["preparation"]["market_item_id"] == 27277


def test_physical_detail_quote_metadata_uses_prepared_market_form():
    from tracker.gear.service import GearService

    service = GearService(Content())
    result = service.physical_item(None, 27275, price_records=prices({27277: 123}), now=NOW)
    assert result["price"]["amount_gp"] == 123
    assert result["price"]["source"] == "live"
    assert result["price"]["high_price_gp"] == 123
    assert result["price"]["confidence"] is not None


def test_ayak_chooses_cheapest_fully_priced_recipe_and_names_resources():
    item = EquipmentDefinition(id=31113, name="Eye of Ayak", slot="weapon")
    result = evaluate_running_cost(
        {"weapon": item},
        {"powered_attack": "ayak"},
        {"attack_interval": 1.8, "dps": 10},
        prices({31111: 200, 560: 10, 562: 5}),
        NOW,
    )
    assert result["gp_per_attack"] == 25
    assert {r["name"] for r in result["resources"]} == {"Death rune", "Chaos rune"}
    assert len(result["charging_alternatives"]) == 2
    assert {21820, 31111} <= resource_item_ids()


def test_unknown_ayak_resource_prices_are_unavailable():
    item = EquipmentDefinition(id=31113, name="Eye of Ayak", slot="weapon")
    result = evaluate_running_cost(
        {"weapon": item}, {"powered_attack": "ayak"}, {"attack_interval": 1.8, "dps": 10}, {}, NOW
    )
    assert result["status"] == "unavailable"
    assert result["gp_per_attack"] is None


def test_ayak_purchase_uses_its_uncharged_market_id():
    item = EquipmentDefinition(id=31113, name="Eye of Ayak", slot="weapon")
    fact = equipment_fact(AccountSnapshot(1, "test"), item, Content(), prices({31115: 321}), NOW)
    assert fact["price"]["amount_gp"] == 321
    assert fact["preparation"]["market_item_id"] == 31115


def test_charged_full_trident_is_equivalent_without_requiring_charging():
    seen = ObservedItemFact(11905, Container.BANK, 1, "test", NOW)
    snapshot = AccountSnapshot(1, "test", observed_items={(11905, Container.BANK): seen})
    item = EquipmentDefinition(id=11907, name="Trident", slot="weapon")
    fact = equipment_fact(snapshot, item, Content(), {}, NOW)
    assert fact["planning_ownership"]["status"] == "owned"
    assert fact["preparation"]["source_item_id"] == 11905
    assert not fact["preparation"]["charging_required"]
    assert "Charging required" not in fact["preparation"]["message"]


def test_ordinary_staff_does_not_grant_enhanced_ownership_or_free_upgrade():
    seen = ObservedItemFact(11908, Container.BANK, 1, "test", NOW)
    snapshot = AccountSnapshot(1, "test", observed_items={(11908, Container.BANK): seen})
    item = EquipmentDefinition(id=22288, name="Trident enhanced", slot="weapon")
    fact = equipment_fact(snapshot, item, Content(), prices({11908: 100}), NOW)
    assert fact["planning_ownership"]["status"] != "owned"
    assert fact["preparation"]["market_item_id"] is None
    assert fact["price"]["amount_gp"] is None


def test_charged_autocast_sceptre_consumes_ether_but_uncharged_does_not():
    records = prices({556: 1, 558: 2, 21820: 10})
    results = []
    for item_id in (27788, 27785):
        item = EquipmentDefinition(id=item_id, name="Sceptre (a)", slot="weapon")
        results.append(
            evaluate_running_cost(
                {"weapon": item},
                {"attack_type": "magic", "spell": "wind_strike"},
                {"attack_interval": 3, "dps": 1},
                records,
                NOW,
            )
        )
    assert results[0]["gp_per_attack"] == results[1]["gp_per_attack"] + 10
