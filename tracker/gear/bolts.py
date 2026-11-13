"""Reviewed PvM bolt expectations, without random simulation.

Mechanics reference: weirdgloop/osrs-dps-calc bolts.ts at
880ab3f324ebea2644681d835448ab9d45c04f5c. Ordinary accurate zeroes
become one; additive effects precede that adjustment, ruby follows it.
"""

from math import floor


def _floor_sum(maximum: int, divisor: int) -> int:
    """Sum floor(x/divisor) for x=0..maximum without enumerating outcomes."""
    if maximum < 0:
        return 0
    quotient, remainder = divmod(maximum, divisor)
    return divisor * quotient * (quotient - 1) // 2 + quotient * (remainder + 1)


def _mean(maximum: int, armour: int, bonus: int = 0, divisor: int = 1) -> float:
    if divisor == 1:
        # Keep the ordinary-bolt hot path and arithmetic unchanged.
        first = max(0, armour - bonus + 1)
        count = max(0, maximum - first + 1)
        ordinary_total = count * (first + maximum + 2 * (bonus - armour)) / 2
        if bonus == 0:
            ordinary_total += max(0, 1 - armour) - max(0, -armour)
        return ordinary_total / (maximum + 1)
    first = max(0, divisor * (armour + 1) - bonus)
    count = max(0, maximum - first + 1)
    total = (
        _floor_sum(maximum + bonus, divisor)
        - _floor_sum(first + bonus - 1, divisor)
        - count * armour
        if count
        else 0
    )
    if bonus == 0:
        total += max(0, 1 // divisor - armour) - max(0, -armour)
    return total / (maximum + 1)


def expected_bolt_damage(
    family: str,
    ranged: int,
    maximum: int,
    accuracy: float,
    hp: int | None,
    diary: bool,
    zaryte: bool,
    traits: tuple[str, ...],
    armour: int = 0,
    *,
    damage_divisor: int = 1,
    chance_multiplier: float = 1,
) -> tuple[float, int, float]:
    """Return expected damage, possible maximum and actual activation probability."""
    ordinary = _mean(maximum, armour, divisor=damage_divisor)
    normal_max = max(0, max(1, maximum) // damage_divisor - armour)
    base = accuracy * ordinary
    chance = (
        {
            "opal": 0.05,
            "pearl": 0.06,
            "ruby": 0.06,
            "diamond": 0.10,
            "dragonstone": 0.06,
            "onyx": 0.11,
        }[family]
        * (1.1 if diary else 1)
        * chance_multiplier
    )
    if (
        chance == 0
        or (family == "onyx" and "undead" in traits)
        or (family == "dragonstone" and {"dragon", "fiery"} & set(traits))
    ):
        return base, normal_max, 0
    if family == "ruby":
        if hp is None:
            raise ValueError("Ruby bolts require target current or base hitpoints.")
        damage = min(110 if zaryte else 100, hp * (22 if zaryte else 20) // 100)
        damage = max(0, damage // damage_divisor - armour)
        return (1 - chance) * base + chance * damage, max(normal_max, damage), chance
    if family in {"diamond", "onyx"}:
        multiplier = (126 if zaryte else 115) if family == "diamond" else (132 if zaryte else 120)
        effect_max = maximum * multiplier // 100
        effect_mean = _mean(effect_max, armour, divisor=damage_divisor)
        activation = chance if family == "diamond" else chance * accuracy
        mean = (
            (1 - chance) * base + chance * effect_mean
            if family == "diamond"
            else accuracy * ((1 - chance) * ordinary + chance * effect_mean)
        )
        return (
            mean,
            max(normal_max, max(0, max(1, effect_max) // damage_divisor - armour)),
            activation,
        )
    if family == "opal":
        bonus = ranged // (9 if zaryte else 10)
    elif family == "pearl":
        divisor = 15 if "fiery" in traits else 20
        bonus = ranged // (divisor - 2 if zaryte else divisor)
    else:
        bonus = floor(ranged * 2 / (9 if zaryte else 10))
    activation = chance * accuracy if family == "dragonstone" else chance
    # An accurate zero already contributes one ordinarily; replace that outcome
    # before adding the proc bonus. A proc on a miss adds only its bonus.
    increment = _mean(maximum, armour, bonus, damage_divisor) - ordinary
    mean = base + chance * accuracy * increment
    if family != "dragonstone":
        mean += chance * (1 - accuracy) * (bonus // damage_divisor)
    return (
        mean,
        max(
            normal_max,
            max(0, max(1, maximum + bonus) // damage_divisor - armour),
            bonus // damage_divisor if family != "dragonstone" else 0,
        ),
        activation,
    )
