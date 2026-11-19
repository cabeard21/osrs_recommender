"""Potion decay uses discrete, clamped stat changes."""

import pytest

from tracker.gear.potion_timeline import decay_levels, event_times


def test_ordinary_boundaries_and_clamping():
    levels = {"strength": 99, "attack": 80}
    assert decay_levels(levels, ("super_strength",), 59)["strength"] == 118
    assert decay_levels(levels, ("super_strength",), 60)["strength"] == 117
    assert decay_levels(levels, ("super_strength",), 1140)["strength"] == 99
    assert decay_levels(levels, ("super_strength",), 1200) == levels
    assert levels == {"strength": 99, "attack": 80}
    assert event_times(levels, ("super_strength",))[-1] == 1200


def test_divine_expiry_and_overlap():
    levels = {"strength": 99, "attack": 99, "ranged": 99}
    ids = ("divine_super_strength", "super_combat", "ranging")
    assert decay_levels(levels, ids, 299) == {"strength": 118, "attack": 114, "ranged": 108}
    assert decay_levels(levels, ids, 300) == {"strength": 99, "attack": 113, "ranged": 107}
    assert event_times(levels, ("divine_super_strength",)) == (0, 300, 360)


def test_no_potions_and_unknown_ids():
    assert event_times({"attack": 99}, ()) == (0, 60)
    with pytest.raises(ValueError):
        decay_levels({"attack": 99}, ("unknown",), 0)


def test_unavailable_spell_does_not_renormalize_multi():
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.potion_timeline import measure
    from tracker.gear.scoring import prepare_equipment

    roles = (
        RoleConfig(id="low", style="magic", spell="fire_strike", weight=1),
        RoleConfig(id="high", style="magic", spell="fire_surge", weight=3),
    )
    prepared = {role.id: prepare_equipment({}) for role in roles}
    fresh = measure(0, {"magic": 95}, roles, prepared, "accuracy")
    decayed = measure(60, {"magic": 94}, roles, prepared, "accuracy")
    assert fresh["dps"] == pytest.approx(
        (fresh["roles"]["low"]["dps"] + 3 * fresh["roles"]["high"]["dps"]) / 4
    )
    assert decayed["dps"] is decayed["secondary_value"] is None
    assert decayed["roles"]["low"]["dps"] > 0
    assert decayed["roles"]["high"]["reasons"]


def test_equipment_metric_is_flat_and_zero_weight_role_does_not_block():
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.potion_timeline import measure
    from tracker.gear.scoring import prepare_equipment

    roles = (
        RoleConfig(id="active", style="magic", spell="fire_strike"),
        RoleConfig(id="inactive", style="magic", spell="fire_surge", weight=0),
    )
    prepared = {role.id: prepare_equipment({}) for role in roles}
    assert measure(60, {"magic": 80}, roles, prepared, "prayer_bonus")["secondary_value"] == 0
    assert measure(120, {"magic": 79}, roles, prepared, "prayer_bonus")["dps"] > 0


def test_cost_uses_weighted_spend_and_damage_and_preserves_unpriced_dps():
    from types import SimpleNamespace

    from tracker.gear.compact_costs import NumericCost
    from tracker.gear.objectives import ObjectiveDescriptor
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.potion_timeline import measure
    from tracker.gear.scoring import prepare_equipment

    roles = (
        RoleConfig(id="low", style="magic", spell="fire_strike"),
        RoleConfig(id="high", style="magic", spell="fire_surge", weight=3),
    )
    prepared = {role.id: prepare_equipment({}) for role in roles}
    objectives = (ObjectiveDescriptor(kind="gp_per_damage"), ObjectiveDescriptor(kind="accuracy"))

    def cost(per_second):
        def score(interval, dps, accuracy):
            return NumericCost("known", None, per_second, per_second * 3600, per_second / dps)

        return SimpleNamespace(score=score)

    costs = {"high": cost(2), "low": cost(1)}

    def sample(selected_costs):
        return measure(0, {"magic": 95}, roles, prepared, "default", objectives, selected_costs)

    row = sample(costs)
    by_role = row["roles"]
    assert row["objective_values"]["gp_per_damage"] == pytest.approx(
        7 / (by_role["low"]["dps"] + 3 * by_role["high"]["dps"])
    )
    missing = SimpleNamespace(
        score=lambda *args: NumericCost("unavailable", None, None, None, None)
    )
    unknown = sample({**costs, "high": missing})
    assert unknown["objective_values"]["gp_per_damage"] is None
    assert unknown["objective_values"]["accuracy"] == row["objective_values"]["accuracy"]
    assert unknown["dps"] == row["dps"]
