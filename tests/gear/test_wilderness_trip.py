from tracker.gear.models import EquipmentDefinition
from tracker.gear.wilderness import Charge, DeathItem, WildernessPolicy, WildernessRisk


def test_shared_trip_rounds_once_and_can_displace_protected_gear():
    bow = EquipmentDefinition(id=1, name="Bow", slot="weapon", ammo_for=("arrow:1",))
    arrow = EquipmentDefinition(
        id=2, name="Arrow", slot="ammunition", ammo_type="arrow:1", stackable=True
    )
    cape = EquipmentDefinition(id=22109, name="Assembler", slot="cape")
    gear = {"weapon": 1, "ammunition": 2, "cape": cape.id}
    risk = WildernessRisk(
        WildernessPolicy(attacks_per_setup=7, skulled=True, protect_item=True),
        None,
        {1: DeathItem(10, 100), 2: DeathItem(4, 2, ammo=True), cape.id: DeathItem(1, 1)},
    )
    report = risk.trip_report(
        {"a": gear, "b": gear},
        {},
        {i.id: i for i in (bow, arrow, cape)},
        styles={"a": "ranged", "b": "ranged"},
    )
    assert report["quantities"] == [{"item_id": 2, "resource_id": 2, "kind": "ammo", "quantity": 3}]
    assert report["loss_gp"] == 101
    assert report["without_protect_item_gp"] == 107


def test_shared_trip_charge_capacity_and_activation():
    risk = WildernessRisk(
        WildernessPolicy(attacks_per_setup=4, skulled=True),
        0,
        {22542: DeathItem(10, 12, charge=Charge(((21820, 1, 2),), 1001, 1006))},
    )
    gear = {"weapon": 22542}
    single = risk.trip_report({"a": gear}, {}, {}, styles={"a": "crush"})
    assert single["loss_gp"] == 12 + 2 * 1004
    assert (
        risk.trip_report({"a": gear, "b": gear}, {}, {}, styles={"a": "crush", "b": "crush"})[
            "loss_gp"
        ]
        is None
    )


def test_unpriced_and_unknown_recovery_are_unavailable_but_protected_items_can_be_known():
    arrow = EquipmentDefinition(
        id=882, name="Bronze arrow", slot="ammunition", ammo_type="arrow:882"
    )
    bow = EquipmentDefinition(id=861, name="Bow", slot="weapon", ammo_for=("arrow:882",))
    gear = {"weapon": bow.id, "cape": 9756, "ammunition": arrow.id}
    rules = {
        bow.id: DeathItem(100, None),
        arrow.id: DeathItem(1, 10, ammo=True),
        9756: DeathItem(6, 1),
    }
    risk = WildernessRisk(
        WildernessPolicy(attacks_per_setup=2, skulled=True, protect_item=True), None, rules
    )
    items = {i.id: i for i in (bow, arrow)}
    assert risk.trip_report({"a": gear}, {}, items, styles={"a": "ranged"})["loss_gp"] is None
    known = risk.trip_report(
        {"a": {"weapon": bow.id, "ammunition": arrow.id}}, {}, items, styles={"a": "ranged"}
    )
    assert known["loss_gp"] == 20
    assert known["without_protect_item_gp"] is None


def test_runes_and_special_switches_count_once():
    risk = WildernessRisk(
        WildernessPolicy(attacks_per_setup=2, skulled=True),
        None,
        {1383: DeathItem(100, 20), 4151: DeathItem(150, 40)},
        {556: DeathItem(1, 1, ammo=True), 558: DeathItem(2, 2, ammo=True)},
    )
    gear = {"a": {"weapon": 1383}, "b": {"weapon": 1383}, "spec": {"weapon": 4151}}
    options = {key: {"attack_type": "magic", "spell": "water_strike"} for key in ("a", "b")}
    items = {i: EquipmentDefinition(id=i, slot="weapon", name="weapon") for i in (1383, 4151)}
    report = risk.trip_report(
        gear, options, items, styles={"a": "magic", "b": "magic", "spec": "special"}
    )
    assert report["loss_gp"] == 72
    assert {row["resource_id"]: row["quantity"] for row in report["quantities"]} == {556: 4, 558: 4}


def test_staff_charges_follow_exact_attack():
    rule = DeathItem(10, 10, charge=Charge(((21820, 1, 1),), 1001, 17000))
    trident = DeathItem(10, 10, charge=Charge(((562, 1, 1),), 1, 2500, always_lost=False))
    risk = WildernessRisk(
        WildernessPolicy(attacks_per_setup=8, skulled=True),
        None,
        {27788: rule, 22555: rule, 11907: trident},
        {556: DeathItem(1, 1, ammo=True), 558: DeathItem(1, 1, ammo=True)},
    )
    spell = {"attack_type": "magic", "spell": "wind_strike"}
    powered = {"attack_type": "magic", "powered_attack": "staff"}

    def packed(item, option):
        report = risk.trip_report(
            {"a": {"weapon": item}}, {"a": option}, {}, styles={"a": option["attack_type"]}
        )
        assert report["loss_gp"] is not None
        return next(q["quantity"] for q in report["quantities"] if q["kind"] == "charge")

    assert packed(11907, spell) == 1
    assert packed(11907, {"attack_type": "crush"}) == 1
    assert packed(11907, powered) == 8
    assert packed(22555, spell) == 1001
    assert packed(27788, spell) == 1008
    assert packed(27788, {"attack_type": "crush"}) == 1001


def test_special_bow_needs_compatible_ammo_even_with_parent_stance():
    bow = EquipmentDefinition(id=861, name="Bow", slot="weapon", ammo_for=("arrow:882",))
    arrow = EquipmentDefinition(id=882, name="Arrow", slot="ammunition", ammo_type="arrow:882")
    bolt = EquipmentDefinition(id=877, name="Bolt", slot="ammunition", ammo_type="bolt:877")
    risk = WildernessRisk(
        WildernessPolicy(attacks_per_setup=100, skulled=True),
        None,
        {861: DeathItem(10, 10), 882: DeathItem(5, 5, ammo=True), 877: DeathItem(2, 2, ammo=True)},
    )

    def packed(gear):
        return risk.trip_report(
            {"special": gear},
            {"special": {"attack_type": "slash"}},
            {i.id: i for i in (bow, arrow, bolt)},
            styles={"special": "special"},
        )

    assert packed({"weapon": 861})["loss_gp"] is None
    assert packed({"weapon": 861, "ammunition": 877})["loss_gp"] is None
    assert packed({"weapon": 861, "ammunition": 882})["loss_gp"] == 15
