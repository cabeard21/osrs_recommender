from tests.gear.test_combat_options import account
from tracker.gear.catalog import load_catalog
from tracker.gear.combat_options import eligible_combat_options


def test_reviewed_powered_forms_offer_real_attacks(make_content):
    catalog = load_catalog(make_content())
    for item_id in (28585, 11905, 11907, 12899, 22323, 27275, 31113, 28796, 22555, 27665):
        staff = catalog.items[item_id]
        assert staff.requirements_complete
        assert not staff.unsupported_effects
        assert staff.powered_attack_model
        options = eligible_combat_options(
            staff, account(), discipline="magic", levels={"magic": 99}
        )
        assert {o.stance for o in options} == {"accurate", "longrange"}
        assert all(o.charges == "unknown" for o in options)


def test_uncharged_and_autocasting_forms_do_not_gain_powered_attacks(make_content):
    catalog = load_catalog(make_content())
    for item_id in (28583, 11908, 27277, 22516):
        staff = catalog.items[item_id]
        assert not staff.powered_attack
        assert staff.unsupported_effects


def test_powered_unlock_requires_observed_magic_level(make_content):
    staff = load_catalog(make_content()).items[11907]
    assert not eligible_combat_options(
        staff, account(magic=74), discipline="magic", levels={"magic": 74}
    )


def test_autocasting_sceptres_support_existing_spells_without_powered_attack(make_content):
    from tracker.gear.combat import ANCIENT_SPELLS, ELEMENTAL_SPELLS

    catalog = load_catalog(make_content())
    for item_id in (27785, 27788, 27676, 27679):
        staff = catalog.items[item_id]
        assert not staff.powered_attack
        assert staff.requirements_complete
        assert not staff.unsupported_effects
        assert set(staff.spell_compatibility) == set(ANCIENT_SPELLS) | set(ELEMENTAL_SPELLS)
        assert staff.attack_speed == 5
    assert catalog.items[11905].tradeable
    assert not catalog.items[25733].tradeable
    assert not catalog.items[33328].tradeable
