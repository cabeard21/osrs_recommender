"""Documented Aquanite hopper expectations with explicit approximation defaults.

https://oldschool.runescape.wiki/w/Aquanite_hopper
Damage rounding, ruby reduction, and extra ammunition consumption are assumptions,
not experimentally verified game mechanics. Accuracy is supplied after reducing
the attack roll to floor(2*roll/3), never by multiplying the hit chance.
"""

import json

from tracker.gear.bolts import _mean, expected_bolt_damage
from tracker.gear.bolts_catalog import CROSSBOWS
from tracker.gear.models import EquipmentDefinition

MODEL_VERSION = "aquanite-hopper-v1-approximate"
PROC_CHANCE = 0.11
ASSUMPTIONS = (
    "Aquanite hopper estimates use floor(damage/3) after bolt and minimum-hit "
    "adjustments, before flat armour; ruby proc damage is also reduced.",
    "Aquanite hopper extra shots are assumed to consume another bolt with normal "
    "Ava recovery: 1.11 expected bolts per attack.",
    "Aquanite hopper secondary ruby damage uses the same static target HP as the primary shot.",
)
REVISION = json.dumps(
    [MODEL_VERSION, 32879, PROC_CHANCE, 2, 3, ASSUMPTIONS, sorted(CROSSBOWS)], sort_keys=True
).encode()


def active(
    weapon: EquipmentDefinition | None,
    shield: EquipmentDefinition | None,
    ammunition: EquipmentDefinition | None,
) -> bool:
    """Recognize only reviewed crossbows with compatible physical ammunition."""
    return bool(
        weapon
        and weapon.id in CROSSBOWS
        and shield
        and shield.id == 32879
        and shield.slot == "shield"
        and ammunition
        and ammunition.ammo_type in weapon.ammo_for
    )


def expected_secondary_damage(
    family: str | None,
    ranged: int,
    maximum: int,
    accuracy: float,
    hp: int | None,
    diary: bool,
    zaryte: bool,
    traits: tuple[str, ...],
    armour: int = 0,
    primary_activation: float = 0,
) -> tuple[float, int, float]:
    """Expected damage, maximum and proc probability conditional on hopper firing.

    Suppress only secondary bolt effects when the primary actually activated;
    its ordinary damage is retained in all cases. Multiply expectation by
    PROC_CHANCE once at the caller to obtain damage added per ordinary attack.
    """
    if family is None:
        return (
            accuracy * _mean(maximum, armour, divisor=3),
            max(0, max(1, maximum) // 3 - armour),
            0,
        )
    return expected_bolt_damage(
        family,
        ranged,
        maximum,
        accuracy,
        hp,
        diary,
        zaryte,
        traits,
        armour,
        damage_divisor=3,
        chance_multiplier=(1 - primary_activation) / 3,
    )
