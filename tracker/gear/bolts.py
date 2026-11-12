"""Reviewed PvM bolt expectations, without random simulation.

Mechanics reference: weirdgloop/osrs-dps-calc bolts.ts at
880ab3f324ebea2644681d835448ab9d45c04f5c. Ordinary accurate zeroes
become one; additive effects precede that adjustment, ruby follows it.
"""

from math import floor


def _mean(maximum: int, armour: int, bonus: int = 0) -> float:
    first = max(0, armour - bonus + 1)
    count = max(0, maximum - first + 1)
    total = count * (first + maximum + 2 * (bonus - armour)) / 2
    if bonus == 0:
        total += max(0, 1 - armour) - max(0, -armour)
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
) -> tuple[float, int, float]:
    """Return expected damage, possible maximum and actual activation probability."""
    ordinary = _mean(maximum, armour)
    normal_max = max(0, max(1, maximum) - armour)
    base = accuracy * ordinary
    chance = {
        "opal": 0.05,
        "pearl": 0.06,
        "ruby": 0.06,
        "diamond": 0.10,
        "dragonstone": 0.06,
        "onyx": 0.11,
    }[family] * (1.1 if diary else 1)
    if (family == "onyx" and "undead" in traits) or (
        family == "dragonstone" and {"dragon", "fiery"} & set(traits)
    ):
        return base, normal_max, 0
    if family == "ruby":
        if hp is None:
            raise ValueError("Ruby bolts require target current or base hitpoints.")
        damage = min(110 if zaryte else 100, hp * (22 if zaryte else 20) // 100)
        damage = max(0, damage - armour)
        return (1 - chance) * base + chance * damage, max(normal_max, damage), chance
    if family in {"diamond", "onyx"}:
        multiplier = (126 if zaryte else 115) if family == "diamond" else (132 if zaryte else 120)
        effect_max = maximum * multiplier // 100
        effect_mean = _mean(effect_max, armour)
        activation = chance if family == "diamond" else chance * accuracy
        mean = (
            (1 - chance) * base + chance * effect_mean
            if family == "diamond"
            else accuracy * ((1 - chance) * ordinary + chance * effect_mean)
        )
        return mean, max(normal_max, max(1, effect_max) - armour), activation
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
    increment = _mean(maximum, armour, bonus) - ordinary
    mean = base + chance * accuracy * increment
    if family != "dragonstone":
        mean += chance * (1 - accuracy) * bonus
    return (
        mean,
        max(normal_max, max(1, maximum + bonus) - armour, bonus if family != "dragonstone" else 0),
        activation,
    )
