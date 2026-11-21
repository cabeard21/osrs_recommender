"""Vampyre ordinary attacks, including per-hitsplat rounding and charge context."""

from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.prepared_combat import prepared_combat
from tracker.gear.ranged_numerics import ranged_experiment
from tracker.gear.ranged_score_finalization import ranged_score_finalization
from tracker.gear.scoring import prepare_equipment

LEVELS = dict.fromkeys(("attack", "strength", "ranged", "magic", "defence", "slayer"), 99)
RING = EquipmentDefinition(id=21140, name="Efaritay's aid", slot="ring")


def role(tier, style="crush", **kwargs):
    return SimpleNamespace(
        style=style,
        stance="accurate",
        spell="fire_wave",
        target=CombatTarget(traits=(f"vampyre{tier}",) if tier else (), hitpoints=500),
        **kwargs,
    )


def weapon(item_id, style="crush", **kwargs):
    return EquipmentDefinition(
        id=item_id,
        name=str(item_id),
        slot="weapon",
        attack_styles=(style,),
        bonuses=EquipmentBonuses(crush=71, ranged=70, melee_strength=70, ranged_strength=70),
        **kwargs,
    )


@pytest.mark.parametrize(
    "tier,item,ring,legal,w_acc,w_dmg,r_acc,r_dmg,divisor,cap",
    [
        (1, 4151, False, True, 0, 0, 0, 0, 1, None),
        (1, 4151, True, True, 0, 0, 0, 10, 1, None),
        (1, 2952, True, True, 0, 10, 15, 10, 1, None),
        (1, 24699, False, True, 5, 25, 0, 0, 1, None),
        (2, 4151, False, False, 0, 0, 0, 0, 1, None),
        (2, 4151, True, True, 0, 0, 0, 0, 2, None),
        (2, 2952, False, True, 0, 0, 0, 0, 1, 10),
        (2, 2952, True, True, 0, 0, 15, 0, 2, None),
        (2, 7648, True, True, 0, 10, 15, 10, 1, None),
        (3, 7648, True, False, 0, 0, 0, 0, 1, None),
        (3, 2952, True, False, 0, 0, 0, 0, 1, None),
        (3, 22398, True, True, 0, 20, 15, 10, 1, None),
        (3, 24697, True, True, 5, 15, 15, 10, 1, None),
        (3, 33722, True, True, 25, 50, 15, 10, 1, None),
        (3, 33716, True, True, 25, 25, 15, 10, 1, None),
    ],
)
def test_ordinary_tier_matrix(tier, item, ring, legal, w_acc, w_dmg, r_acc, r_dmg, divisor, cap):
    style = "ranged" if item == 33716 else "crush"
    items = [weapon(item, style)] + ([RING] if ring else [])
    configured = role(tier, style)
    actual = evaluate_loadout(items, configured, LEVELS)
    assert actual.supported is legal
    if not legal:
        assert any(f"tier {tier}" in reason.lower() for reason in actual.limitations)
        return
    base = evaluate_loadout(items, role(0, style), LEVELS)
    assert base.vampyre_bonus is None
    assert actual.attack_roll == base.attack_roll * (100 + w_acc) // 100 * (100 + r_acc) // 100
    hits = [
        min(max(1, (raw * (100 + r_dmg) // 100) * (100 + w_dmg) // 100) // divisor, cap or 999)
        for raw in range(base.max_hit + 1)
    ]
    assert actual.max_hit == max(hits)
    assert actual.dps == pytest.approx(
        actual.accuracy * sum(hits) / len(hits) / actual.attack_interval
    )
    assert actual.vampyre_bonus.ring_active == ring
    with prepared_combat(), ranged_experiment(8), ranged_score_finalization():
        assert (
            evaluate_prepared_score(prepare_equipment(items), configured, LEVELS).dps == actual.dps
        )


def test_magic_and_unfired_ammunition_do_not_inherit_weapon_silver():
    ammo = EquipmentDefinition(id=9145, name="Silver", slot="ammunition", ammo_type="bolt:9145")
    crossbow = weapon(9185, "ranged", ammo_for=("bolt:9145",))
    assert evaluate_loadout([crossbow, ammo], role(2, "ranged"), LEVELS).supported
    assert not evaluate_loadout(
        [weapon(25849, "ranged"), ammo], role(2, "ranged"), LEVELS
    ).supported
    assert not evaluate_loadout([weapon(22398), RING], role(3, "magic"), LEVELS).supported
    assert (
        evaluate_loadout(
            [weapon(22398), RING], role(2, "magic"), LEVELS
        ).vampyre_bonus.damage_divisor
        == 2
    )


def test_elite_void_applies_to_effective_levels_and_requires_complete_ranged_set():
    pieces = [
        EquipmentDefinition(id=i, slot=slot, name=str(i))
        for i, slot in [(11664, "head"), (13072, "body"), (13073, "legs"), (8842, "hands")]
    ]
    item = weapon(33716, "ranged")
    configured = role(0, "ranged")
    full = evaluate_loadout([item, *pieces], configured, LEVELS)
    assert full.elite_void_ranged_bonus.strength_percent == 12.5
    ranged_level = LEVELS["ranged"] + 3 + 8
    assert full.attack_roll == (ranged_level * 11 // 10) * (70 + 64)
    assert full.max_hit == (320 + (ranged_level * 9 // 8) * (70 + 64)) // 640
    baseline = evaluate_loadout([item], configured, LEVELS)
    for index in range(4):
        partial = evaluate_loadout(
            [item, *pieces[:index], *pieces[index + 1 :]], configured, LEVELS
        )
        assert partial.elite_void_ranged_bonus is None
        assert partial.dps == baseline.dps
    melee = evaluate_loadout([weapon(4151), *pieces], role(0), LEVELS)
    assert melee.elite_void_ranged_bonus is None
    with prepared_combat(), ranged_experiment(8), ranged_score_finalization():
        assert (
            evaluate_prepared_score(prepare_equipment([item, *pieces]), configured, LEVELS).dps
            == full.dps
        )


@pytest.mark.parametrize("kind", ["ruby", "diamond", "onyx", "opal", "pearl", "dragonstone"])
def test_enchanted_bolts_preserve_ring_and_replacement_order(kind):
    crossbow = weapon(9185, "ranged", ammo_for=("bolt:9000",))
    ammo = EquipmentDefinition(
        id=9000, name="Test bolt", slot="ammunition", ammo_type="bolt:9000", bolt_effect=kind
    )
    items = [crossbow, ammo, RING]
    base = evaluate_loadout(items, role(0, "ranged"), LEVELS)
    for tier in (1, 2):
        report = evaluate_loadout(items, role(tier, "ranged"), LEVELS)
        effect = report.bolt_effect
        assert effect is not None
        maximum, chance, accuracy = base.max_hit, effect.proc_chance, report.accuracy

        def reduce(d, divisor=tier):
            return d // divisor

        scaled = [x * 110 // 100 if tier == 1 else x for x in range(maximum + 1)]
        ordinary = sum(reduce(max(1, x)) for x in scaled) / len(scaled)
        if kind in {"ruby", "diamond", "onyx"}:
            if kind == "ruby":
                replacement = reduce(100)
            else:
                proc_max = maximum * (115 if kind == "diamond" else 120) // 100
                replacement = sum(reduce(max(1, x)) for x in range(proc_max + 1)) / (proc_max + 1)
            activation = chance * accuracy if kind == "onyx" else chance
            expected = (1 - chance) * accuracy * ordinary + activation * replacement
        else:
            bonus = {"opal": 9, "pearl": 4, "dragonstone": 19}[kind]
            added = sum(reduce(max(1, x + bonus)) for x in scaled) / len(scaled)
            expected = accuracy * ((1 - chance) * ordinary + chance * added)
            if kind != "dragonstone":
                expected += (1 - accuracy) * chance * reduce(bonus)
        assert effect.expected_damage_per_attack == pytest.approx(expected)
        bypass = chance if kind in {"ruby", "diamond", "opal", "pearl"} else 0
        assert report.vampyre_bonus.ring_charge_probability == pytest.approx(
            accuracy + (1 - accuracy) * bypass
        )


def test_silver_poison_requires_damage_and_uses_ammunition_severity():
    from tracker.gear.status_damage import expected_damage

    crossbow = weapon(9185, "ranged", ammo_for=("bolt:9292",))
    ammo = EquipmentDefinition(id=9292, name="Silver (p)", slot="ammunition", ammo_type="bolt:9292")
    configured = role(2, "ranged")
    configured.target = configured.target.model_copy(
        update={"poison_susceptibility": "susceptible"}
    )
    items = [crossbow, ammo, RING]
    result = evaluate_loadout(items, configured, LEVELS)
    base = evaluate_loadout(items, role(0, "ranged"), LEVELS)
    valid = (base.max_hit - 1) / (base.max_hit + 1)
    assert result.status_damage.expected_damage == pytest.approx(
        expected_damage(0.125 * result.accuracy * valid, 4, 60, "poison", 6)
    )
    with prepared_combat(), ranged_experiment(8), ranged_score_finalization():
        assert (
            evaluate_prepared_score(prepare_equipment(items), configured, LEVELS).dps == result.dps
        )


def test_task_and_double_hits_keep_each_hitsplat_and_one_charge_per_attack():
    item = weapon(4151, attack_pattern="independent_double")
    mask = EquipmentDefinition(id=11865, slot="head", name="Mask", slayer_bonus="all")
    items = [item, RING, mask]
    baseline = evaluate_loadout(items, role(0, on_slayer_task=True), LEVELS)
    actual = evaluate_loadout(items, role(2, on_slayer_task=True), LEVELS)
    assert actual.slayer_effects
    assert actual.attack_roll == baseline.attack_roll
    assert [h.max_hit for h in actual.hitsplats] == [h.max_hit // 2 for h in baseline.hitsplats]
    assert actual.vampyre_bonus.ring_charge_probability == pytest.approx(
        1 - (1 - actual.accuracy) ** 2
    )


def test_hopper_silver_shot_receives_its_own_reductions():
    ammo = EquipmentDefinition(id=9145, name="Silver", slot="ammunition", ammo_type="bolt:9145")
    crossbow = weapon(9185, "ranged", ammo_for=("bolt:9145",))
    shield = EquipmentDefinition(id=32879, name="Aquanite hopper", slot="shield")
    items = [crossbow, ammo, shield, RING]
    normal = evaluate_loadout(items, role(0, "ranged"), LEVELS)
    report = evaluate_loadout(items, role(2, "ranged"), LEVELS)
    extra = report.aquanite_hopper
    high = normal.max_hit
    assert extra.secondary_max_hit == high // 3 // 2
    mean = sum(max(1, roll) // 3 // 2 for roll in range(high + 1)) / (high + 1)
    assert extra.expected_damage_delta == pytest.approx(0.11 * extra.secondary_accuracy * mean)
    assert report.vampyre_bonus.ring_charge_probability == pytest.approx(
        1 - (1 - report.accuracy) * (1 - 0.11 * extra.secondary_accuracy)
    )


def test_spell_hit_transforms_apply_before_target_reduction():
    staff = EquipmentDefinition(
        id=29594, name="Purging staff", slot="weapon", spell_compatibility=("dark_demonbane",)
    )
    config = role(2, "magic", mark_of_darkness=True)
    config.spell = "dark_demonbane"
    config.target = CombatTarget(traits=("demon", "vampyre2"))
    marked = evaluate_loadout([staff, RING], config, LEVELS)
    damages = [max(1, raw + raw // 2) // 2 for raw in range(31)]
    assert marked.max_hit == max(damages)
    assert marked.dps == pytest.approx(marked.accuracy * sum(damages) / 31 / 3)

    from tracker.gear.powered import base_hit

    sang = EquipmentDefinition(
        id=22323,
        name="Sanguinesti staff",
        slot="weapon",
        powered_attack="sanguinesti",
        powered_attack_model="sanguinesti",
        powered_attack_stances=("accurate",),
    )
    report = evaluate_loadout([sang, RING], role(2, "magic", powered_attack="sanguinesti"), LEVELS)
    high = base_hit("sanguinesti", LEVELS["magic"])
    sums = sum(0.8 * (max(1, raw) // 2) + 0.2 * ((max(1, raw) + 8) // 2) for raw in range(high + 1))
    assert report.max_hit == (high + 8) // 2
    assert report.dps == pytest.approx(report.accuracy * sums / (high + 1) / report.attack_interval)


@pytest.mark.parametrize(
    "ranged,ring,expected",
    [(True, False, 26), (True, True, 28), (False, False, 47), (False, True, 51)],
)
def test_published_sentinel_loadouts(make_content, ranged, ring, expected):
    # Weird Gloop Vampyre.test.ts, upstream 3da927f4280c73154fa59e4e90eb374af5123d32.
    from tracker.gear.catalog import load_catalog
    from tracker.gear.npcs import npc_catalog

    catalog = load_catalog(make_content()).items
    ids = (
        [11664, 22109, 19547, 33716, 13072, 13073, 8842, 19933]
        if ranged
        else [29028, 21295, 19553, 33718, 29022, 12954, 29025, 7462, 11840]
    ) + ([21140] if ring else [])
    configured = role(
        3, "ranged" if ranged else "slash", active_prayer_ids=("deadeye" if ranged else "piety",)
    )
    configured.stance = "rapid" if ranged else "accurate"
    sentinel = next(e for e in npc_catalog().entries.values() if e["npc_id"] == 9756)
    configured.target = CombatTarget.model_validate(sentinel["target"])
    actual = evaluate_loadout(
        [catalog[i] for i in ids],
        configured,
        {**LEVELS, "ranged": 112, "attack": 105, "strength": 118},
    )
    assert actual.supported, actual.limitations
    assert actual.max_hit == expected
