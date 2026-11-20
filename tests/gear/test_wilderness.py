from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tracker.gear.models import EquipmentDefinition
from tracker.gear.wilderness import DeathItem, WildernessPolicy, WildernessRisk
from tracker.integrations.prices.client import PriceDTO, PriceSource


@pytest.mark.parametrize("cap", [None, 0, 2**31 - 1])
def test_explicit_wilderness_loss_cap_accepts_the_browser_gp_range(cap):
    assert WildernessPolicy(max_loss_gp=cap).max_loss_gp == cap


def test_omitted_wilderness_cap_preserves_the_legacy_serialized_policy():
    legacy = {"depth": "level_21_plus", "skulled": False, "protect_item": False}
    assert WildernessPolicy.model_validate(legacy).model_dump(mode="json") == legacy
    assert (
        WildernessPolicy.model_validate(legacy | {"max_loss_gp": None}).model_dump(mode="json")
        == legacy
    )
    assert WildernessPolicy(max_loss_gp=0).model_dump(mode="json") == legacy | {"max_loss_gp": 0}


@pytest.mark.parametrize(
    ("cap", "error"),
    [
        (-1, "greater_than_equal"),
        (2**31, "less_than_equal"),
        (True, "int_type"),
        ("1000", "int_type"),
        (1000.0, "int_type"),
    ],
)
def test_explicit_wilderness_loss_cap_rejects_invalid_gp(cap, error):
    with pytest.raises(ValidationError, match="max_loss_gp") as raised:
        WildernessPolicy.model_validate({"max_loss_gp": cap})
    assert raised.value.errors()[0]["type"] == error


@pytest.mark.parametrize(
    ("skulled", "protect_item", "expected"),
    [(False, False, 10), (False, True, 0), (True, False, 100), (True, True, 60)],
)
def test_skull_and_prayer_change_protected_item_count(skulled, protect_item, expected):
    rules = {
        item: DeathItem(priority=item * 10, unprotected_loss_gp=item * 10) for item in range(1, 5)
    }
    policy = WildernessPolicy(skulled=skulled, protect_item=protect_item)
    risk = WildernessRisk(policy, expected, rules)
    loadouts = {"base": {"weapon": 1, "body": 2}, "swap": {"body": 3, "legs": 4, "weapon": 1}}
    report = risk.report(loadouts, base_role="base")
    assert risk.feasible(set(rules))
    assert report["loss_gp"] == expected
    assert len(report["items"]) == 4
    if protect_item:
        assert report["without_protect_item_gp"] == (100 if skulled else 10)


def test_tied_death_priorities_use_higher_player_loss():
    policy = WildernessPolicy(skulled=True, protect_item=True)
    risk = WildernessRisk(policy, 1000, {1: DeathItem(50, 1000), 2: DeathItem(50, 100)})
    report = risk.report({"base": {"weapon": 1, "body": 2}})
    assert report["loss_gp"] == 1000
    assert risk.lower_bound({1, 2}) == 100
    assert {row["item_id"]: row["outcome"] for row in report["items"]} == {1: "dropped", 2: "kept"}


def test_unknown_loss_is_allowed_only_when_definitely_protected():
    rules = {1: DeathItem(900, None, unprotected_outcome="destroyed"), 2: DeathItem(900, 100)}
    policy = WildernessPolicy(skulled=True, protect_item=True)
    risk = WildernessRisk(policy, 100, rules)
    assert risk.feasible({1})
    assert not risk.feasible({1, 2})
    assert risk.report({"base": {"cape": 1, "body": 2}})["loss_gp"] is None


@pytest.mark.parametrize("amulet_id", [4081, 10588, 12017, 25250, 26763, 12018, 25278, 26782])
@pytest.mark.parametrize("depth", ["level_1_20", "level_21_plus"])
@pytest.mark.parametrize(("protect_item", "outcome"), [(False, "gravestone"), (True, "kept")])
def test_salve_survives_pvp_death_with_its_imbue_and_zero_loss(
    amulet_id, depth, protect_item, outcome
):
    item = EquipmentDefinition(id=amulet_id, name="Salve amulet", slot="neck", tradeable=False)
    risk = WildernessRisk.build(
        WildernessPolicy(depth=depth, skulled=True, protect_item=protect_item),
        0,
        {amulet_id: item},
        {},
        {},
        datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert risk.feasible({amulet_id})
    result = risk.report({"base": {"neck": amulet_id}})
    assert result["loss_gp"] == 0
    assert result["items"] == [
        {"item_id": amulet_id, "quantity": 1, "loss_gp": 0, "outcome": outcome}
    ]


def test_unverified_salve_priority_preserves_the_loss_bound_for_other_gear():
    items = {
        12018: EquipmentDefinition(id=12018, name="Salve amulet(ei)", slot="neck", tradeable=False),
        4151: EquipmentDefinition(id=4151, name="Abyssal whip", slot="weapon", tradeable=True),
    }
    risk = WildernessRisk.build(
        WildernessPolicy(skulled=True, protect_item=True),
        0,
        items,
        {4151: {"price": {"amount_gp": 700_000}}},
        {},
        datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert not risk.feasible(set(items))
    report = risk.report({"base": {"neck": 12018, "weapon": 4151}})
    assert report["loss_gp"] == 700_000
    assert report["without_protect_item_gp"] == 700_000


def test_ammo_quantity_leaves_protected_durable_gear_ahead_and_fits_the_cap():
    rules = {1: DeathItem(100, 500), 2: DeathItem(10, 5, ammo=True)}
    policy = WildernessPolicy(skulled=True, protect_item=True)
    loadouts = {"base": {"weapon": 1, "ammunition": 2}}
    result = WildernessRisk(policy, 100, rules).report(loadouts)
    assert result["loss_gp"] == 45
    assert result["quantities"] == [{"item_id": 2, "resource_id": 2, "kind": "ammo", "quantity": 9}]
    assert result["without_protect_item_gp"] == 545
    assert WildernessRisk(policy, 39, rules).report(loadouts)["quantities"][0]["quantity"] == 7


def test_ammo_can_use_a_spare_slot_but_larger_stacks_must_be_covered():
    rules = {1: DeathItem(100, 500), 2: DeathItem(10, 5, ammo=True)}
    risk = WildernessRisk(WildernessPolicy(), 20, rules)
    result = risk.report({"base": {"weapon": 1, "ammunition": 2}})
    assert result["quantities"][0]["quantity"] == 6
    assert result["loss_gp"] == 20


def test_shared_minimum_ammo_does_not_starve_a_lower_priority_role():
    rules = {1: DeathItem(30, 3, ammo=True), 2: DeathItem(20, 2, ammo=True)}
    risk = WildernessRisk(WildernessPolicy(skulled=True), 10, rules)
    result = risk.report({"other": {"ammunition": 1}, "base": {"ammunition": 2}}, base_role="base")
    assert result["quantities"] == [
        {"item_id": 2, "resource_id": 2, "kind": "ammo", "quantity": 3},
        {"item_id": 1, "resource_id": 1, "kind": "ammo", "quantity": 1},
    ]


def test_exact_catalog_uses_guide_priority_and_reviewed_perdu_fees():
    items = {
        6570: EquipmentDefinition(id=6570, name="Fire cape", slot="cape", tradeable=False),
        24224: EquipmentDefinition(
            id=24224, name="Infernal cape (l)", slot="cape", tradeable=False
        ),
        21295: EquipmentDefinition(id=21295, name="Infernal cape", slot="cape", tradeable=False),
        4151: EquipmentDefinition(id=4151, name="Abyssal whip", slot="weapon", tradeable=True),
    }
    facts = {4151: {"price": {"amount_gp": 700_000}}}
    risk = WildernessRisk.build(
        WildernessPolicy(skulled=True),
        500_000,
        items,
        facts,
        {},
        datetime(2026, 11, 18, tzinfo=UTC),
    )
    assert risk.rank_key(4151) == (False, 700_000)
    assert risk.report({"base": {"cape": 6570}})["loss_gp"] == 150_000
    assert risk.report({"base": {"cape": 24224}})["items"] == [
        {"item_id": 24224, "outcome": "mangled", "loss_gp": 500_000, "quantity": 1}
    ]
    assert not risk.feasible({21295})
    assert not risk.feasible({4151})
    assert risk.feasible({24224})


def quote(item_id: int, gp: int, now: datetime) -> PriceDTO:
    return PriceDTO(
        item_id=item_id,
        high_price_gp=gp,
        high_trade_at=now,
        low_price_gp=None,
        low_trade_at=None,
        provider="osrs_wiki",
        fetched_at=now,
        source=PriceSource.LIVE,
    )


def test_revenant_ether_includes_activation_and_is_lost_even_if_the_weapon_is_kept():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    items = {27655: EquipmentDefinition(id=27655, name="Webweaver bow", slot="weapon")}
    prices = {27652: quote(27652, 10_000_000, now), 21820: quote(21820, 100, now)}
    policy = WildernessPolicy(skulled=True, protect_item=True)
    risk = WildernessRisk.build(policy, 150_010, items, {}, prices, now)
    assert risk.feasible({27655})
    assert risk.lower_bound({27655}) == 100_100
    report = risk.report({"base": {"weapon": 27655}})
    assert report["loss_gp"] == 150_000
    assert report["without_protect_item_gp"] == 10_150_000
    assert report["quantities"] == [
        {"item_id": 27655, "resource_id": 21820, "kind": "charge", "quantity": 1500}
    ]


def test_trident_recommends_each_charge_ingredient_and_loses_charges_with_the_staff():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    items = {11907: EquipmentDefinition(id=11907, name="Trident of the seas", slot="weapon")}
    prices = {item_id: quote(item_id, 10, now) for item_id in (554, 560, 562)}
    prices[11908] = quote(11908, 50_000, now)
    policy = WildernessPolicy(skulled=True)
    risk = WildernessRisk.build(policy, 50_165, items, {}, prices, now)
    assert risk.feasible({11907})
    report = risk.report({"base": {"weapon": 11907}})
    assert report["loss_gp"] == 50_160
    assert {row["resource_id"]: row["quantity"] for row in report["quantities"]} == {
        554: 10,
        560: 2,
        562: 2,
        995: 20,
    }


def test_same_role_resource_priority_does_not_depend_on_slot_insertion_order():
    rules = {1: DeathItem(30, 3, ammo=True), 2: DeathItem(20, 2, ammo=True)}
    risk = WildernessRisk(WildernessPolicy(skulled=True), 11, rules)
    result = risk.report({"base": {"ammunition": 2, "weapon": 1}})
    assert [row["quantity"] for row in result["quantities"]] == [3, 1]


def test_idle_ammo_remains_at_one_and_leaves_budget_for_used_equipment():
    rules = {1: DeathItem(70, 7, ammo=True), 2: DeathItem(10, 11, ammo=True)}
    risk = WildernessRisk(WildernessPolicy(skulled=True), 40, rules)
    result = risk.report({"base": {"ammunition": 1, "weapon": 2}}, idle_ammunition={1})
    assert result["loss_gp"] == 40
    assert result["quantities"] == [{"item_id": 2, "resource_id": 2, "kind": "ammo", "quantity": 3}]
    assert result["items"][0] == {"item_id": 1, "outcome": "dropped", "loss_gp": 7, "quantity": 1}


def test_partial_bound_only_prunes_unpriced_losses_when_protection_cannot_be_guaranteed():
    rules = {
        1: DeathItem(100, None),
        2: DeathItem(80, 30),
        3: DeathItem(100, 30),
        4: DeathItem(None, 20),
        5: DeathItem(None, 0, "kept", protection_slot=False),
        6: DeathItem(None, None, "unknown", None),
    }
    risk = WildernessRisk(WildernessPolicy(skulled=True, protect_item=True), 50, rules)
    assert risk.partial_feasible({1, 2, 5})
    assert not risk.partial_feasible({1, 3})
    assert not risk.partial_feasible({1, 4})
    assert not risk.partial_feasible({6})
    assert not WildernessRisk(WildernessPolicy(skulled=True), 50, rules).partial_feasible({1})


def test_partial_pruning_allows_a_new_item_to_displace_unaffordable_ammo():
    rules = {1: DeathItem(100, 300), 2: DeathItem(200, 10, ammo=True), 3: DeathItem(500, 500)}
    risk = WildernessRisk(WildernessPolicy(skulled=True, protect_item=True), 310, rules)
    assert risk.partial_feasible({1, 2})
    assert not risk.feasible({1, 2})
    assert risk.feasible({1, 2, 3})
