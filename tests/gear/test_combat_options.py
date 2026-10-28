from dataclasses import replace
from datetime import UTC, datetime

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.domain.types import Container, SkillState, Source, UnlockState
from tracker.gear.combat_options import (
    eligible_combat_options,
    enumerate_combat_options,
)
from tracker.gear.models import EquipmentDefinition

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def account(*, magic: int = 99, standard: UnlockState = UnlockState.UNLOCKED) -> AccountSnapshot:
    return AccountSnapshot(
        1,
        "test",
        skills={
            name: SkillState(level, None, Source.RUNELITE, NOW)
            for name, level in {"attack": 50, "strength": 50, "ranged": 50, "magic": magic}.items()
        },
        unlocks={"spellbook_standard": standard},
    )


def weapon(*, profiles=(), ammo_for=(), spells=(), powered=None, base=None, powered_stances=()):
    return EquipmentDefinition(
        id=100,
        name="Fixture weapon",
        slot="weapon",
        attack_profiles=profiles,
        attack_styles=tuple(dict.fromkeys(style for style, _ in profiles)),
        ammo_for=ammo_for,
        spell_compatibility=spells,
        powered_attack=powered,
        powered_attack_base_max_hit=base,
        powered_attack_stances=powered_stances,
    )


def test_melee_uses_explicit_pairs_and_all_supported_stances():
    item = weapon(
        profiles=(
            ("stab", "accurate"),
            ("slash", "aggressive"),
            ("crush", "defensive"),
            ("stab", "controlled"),
            ("slash", "rapid"),
        )
    )
    options = eligible_combat_options(item, account(), discipline="melee", levels={})
    assert {(o.attack_type, o.stance) for o in options} == {
        ("stab", "accurate"),
        ("slash", "aggressive"),
        ("crush", "defensive"),
        ("stab", "controlled"),
    }


def test_ranged_categories_and_stance_legality():
    for ammo, kind in (((), "light"), (("arrow",), "standard"), (("bolt:1",), "heavy")):
        item = weapon(
            profiles=(
                ("ranged", "accurate"),
                ("ranged", "rapid"),
                ("ranged", "longrange"),
                ("ranged", "controlled"),
            ),
            ammo_for=ammo,
        )
        options = eligible_combat_options(item, account(), discipline="ranged", levels={})
        assert {(o.attack_type, o.stance) for o in options} == {
            (kind, "accurate"),
            (kind, "rapid"),
            (kind, "longrange"),
        }
        assert all(o.style == "ranged" for o in options)


def test_magic_requires_level_spellbook_and_reviewed_weapon_compatibility():
    item = weapon(spells=("wind_strike", "fire_strike"))
    unlocked = eligible_combat_options(item, account(magic=1), discipline="magic", levels={})
    assert {(o.spell, o.stance) for o in unlocked} == {
        ("wind_strike", "accurate"),
        ("wind_strike", "defensive"),
    }
    assert (
        eligible_combat_options(
            item, account(standard=UnlockState.LOCKED), discipline="magic", levels={}
        )
        == ()
    )
    assert eligible_combat_options(weapon(), account(), discipline="magic", levels={}) == ()


def test_powered_staff_requires_authored_damage_and_reports_unknown_charges():
    incomplete = weapon(powered="fixture", powered_stances=("accurate",))
    assert eligible_combat_options(incomplete, account(), discipline="magic", levels={}) == ()
    item = weapon(
        powered="fixture",
        base=10,
        powered_stances=("accurate", "longrange", "defensive"),
    )
    options = eligible_combat_options(item, account(), discipline="magic", levels={})
    assert {(o.powered_attack, o.stance, o.charges) for o in options} == {
        ("fixture", "accurate", "unknown"),
        ("fixture", "longrange", "unknown"),
    }


def test_missing_account_fact_is_unknown_and_sync_reconciles_eligibility():
    item = weapon(spells=("fire_strike",))
    before = enumerate_combat_options(
        item, account(magic=12, standard=UnlockState.UNKNOWN), discipline="magic", levels={}
    )
    assert all(o.availability == "unsatisfied" for o in before)
    after = eligible_combat_options(item, account(magic=13), discipline="magic", levels={})
    assert {o.spell for o in after} == {"fire_strike"}
    assert all(o.runes == "unknown" for o in after)


def test_standard_spells_remain_selectable_when_sync_omits_innate_spellbook_unlock():
    no_unlock_row = replace(account(magic=13), unlocks={})
    options = eligible_combat_options(None, no_unlock_row, discipline="magic", levels={})
    assert {o.spell for o in options} >= {"wind_strike", "fire_strike"}
    explicit_unknown = eligible_combat_options(
        None, account(magic=13, standard=UnlockState.UNKNOWN), discipline="magic", levels={}
    )
    assert explicit_unknown == ()


def test_unknown_profiles_are_not_inferred():
    assert eligible_combat_options(weapon(), account(), discipline="melee", levels={}) == ()
    assert eligible_combat_options(weapon(), account(), discipline="ranged", levels={}) == ()


def test_ammunition_fact_is_separate_from_attack_eligibility():
    from dataclasses import replace

    bow = weapon(profiles=(("ranged", "rapid"),), ammo_for=("arrow:884",))
    unknown = eligible_combat_options(bow, account(), discipline="ranged", levels={})
    assert unknown[0].available and unknown[0].ammunition == "unknown"
    owned = replace(
        account(),
        observed_items={
            (884, Container.BANK): ObservedItemFact(884, Container.BANK, 20, "test", NOW)
        },
    )
    known = eligible_combat_options(bow, owned, discipline="ranged", levels={})
    assert known[0].available and known[0].ammunition == "satisfied"
