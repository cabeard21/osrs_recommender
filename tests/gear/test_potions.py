from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tracker.gear.potions import (
    PotionPolicy,
    boosted_levels,
    catalog,
    potion_setups,
    potion_summary,
    relevant_boost_skills,
    resource_item_ids,
)

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def price(value):
    return SimpleNamespace(
        high_price_gp=value,
        high_trade_at=NOW,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=NOW,
        source="live",
    )


def test_boosts_round_from_base_without_stacking_or_mutation():
    levels = {"attack": 99, "strength": 50, "magic": 99}
    assert boosted_levels(levels, ("attack", "super_attack", "combat", "magic")) == {
        "attack": 118,
        "strength": 58,
        "magic": 103,
    }
    assert levels == {"attack": 99, "strength": 50, "magic": 99}


def test_unknown_levels_remain_unknown():
    assert boosted_levels({}, ("super_combat",)) == {}


def test_divine_matches_ordinary_snapshot():
    assert boosted_levels({"ranged": 99}, ("ranging",)) == {"ranged": 112}
    assert boosted_levels({"ranged": 99}, ("divine_ranging",)) == {"ranged": 112}


def test_dose_forms_choose_cheapest_per_dose_with_provenance():
    summary = potion_summary(
        {"attack": 99}, ("super_attack",), {2436: price(400), 149: price(70)}, NOW
    )
    assert summary["cost_per_application_gp"] == 70
    assert summary["resources"][0]["item_id"] == 149
    assert summary["resources"][0]["price_layer"] == "live"


def test_unknown_prices_and_empty_setup():
    assert potion_summary({}, ("magic",), {}, NOW)["cost_per_application_gp"] is None
    assert potion_summary({}, (), {}, NOW)["cost_per_application_gp"] == 0


def test_setups_include_none_combinations_and_cheapest_equivalent():
    setups = potion_setups(
        {"attack": 99, "ranged": 99},
        ("super_attack", "divine_super_attack", "ranging"),
        {2436: price(400)},
        NOW,
    )
    assert () in setups
    assert ("ranging", "super_attack") in setups
    assert not any("divine_super_attack" in setup for setup in setups)
    assert len(setups) == 4


def test_catalog_and_policy_validate():
    assert len(catalog()) == 16
    assert {2436, 149, 23685, 23754} <= resource_item_ids()
    assert PotionPolicy().mode == "disabled"
    with pytest.raises(ValidationError):
        PotionPolicy(mode="optimize", allowed_ids=("fake",))
    with pytest.raises(ValidationError):
        PotionPolicy(selected_ids=("magic",))
    with pytest.raises(ValidationError):
        PotionPolicy(mode="fixed", selected_ids=("magic", "magic"))


def test_summary_discloses_divine_hp_and_snapshot_assumption():
    summary = potion_summary({"magic": 50}, ("divine_magic",), {}, NOW)
    assert summary["hp_cost"] == 10
    assert summary["boosted_levels"]["magic"] == 54
    assert summary["limitations"]


def test_relevant_vectors_remove_unscored_defence_and_other_disciplines():
    levels = dict.fromkeys(("attack", "strength", "defence", "ranged", "magic"), 99)
    allowed = tuple(p["id"] for p in catalog() if "magic" not in p["skills"])
    assert len(potion_setups(levels, allowed, {}, NOW)) == 54
    setups = potion_setups(levels, allowed, {}, NOW, relevant_skills=("attack", "strength"))
    assert len(setups) == 9
    assert not any("defence" in key or "ranging" in key for ids in setups for key in ids)


def test_relevant_vectors_keep_cheapest_combined_potion_with_incidental_boost():
    levels = {"attack": 99, "strength": 99, "defence": 99}
    setups = potion_setups(
        levels,
        ("super_attack", "super_strength", "super_combat"),
        {2436: price(400), 2440: price(400), 12695: price(40)},
        NOW,
        relevant_skills=("attack", "strength"),
    )
    assert ("super_combat",) in setups
    assert ("super_attack", "super_strength") not in setups
    assert boosted_levels(levels, ("super_combat",))["defence"] == 118


def test_relevant_skills_union_multi_roles_auto_disciplines_and_ignore_special():
    def role(style, allowed=None):
        return SimpleNamespace(style=style, allowed_disciplines=allowed)

    assert relevant_boost_skills(SimpleNamespace(roles=(role("slash"), role("ranged")))) == {
        "attack",
        "strength",
        "ranged",
    }
    assert relevant_boost_skills(SimpleNamespace(roles=(role("slash", ("ranged", "magic")),))) == {
        "ranged",
        "magic",
    }
    assert relevant_boost_skills(SimpleNamespace(roles=(role("special"), role("magic")))) == {
        "magic",
    }


def test_empty_relevant_skills_keep_only_no_potions():
    assert potion_setups({"defence": 99}, ("super_defence",), {}, NOW, relevant_skills=()) == [()]
