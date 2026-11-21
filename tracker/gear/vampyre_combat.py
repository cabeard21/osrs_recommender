"""Per-attack vampyre legality and exact per-hitsplat transforms.

The Wiki calculator's tested tier 2 silver cap differs from the summary on the
Silver weaponry page. See weirdgloop/osrs-dps-calc PRs 671 and 1012 and
PlayerVsNPCCalc.ts at 3da927f4280c73154fa59e4e90eb374af5123d32.
"""

from functools import lru_cache
from typing import Literal, NamedTuple

from tracker.gear.models import VampyreBonus
from tracker.gear.vampyres import BLISTERWOOD_STAKE, RODS, SILVER_WEAPONS, SPECIALISTS

AttackSource = Literal["ordinary", "silver", "ivandis_rod", "specialist"]


class VampyreRule(NamedTuple):
    tier: int
    attack_source: AttackSource
    legal: bool
    weapon_accuracy_percent: int
    ring_accuracy_percent: int
    weapon_damage_percent: int
    ring_damage_percent: int
    damage_divisor: int
    hit_cap: int | None
    ring_active: bool

    def scale(self, damage: int) -> int:
        damage = damage * (100 + self.ring_damage_percent) // 100
        return damage * (100 + self.weapon_damage_percent) // 100

    def limit(self, damage: int) -> int:
        return min(damage, self.hit_cap) if self.hit_cap else damage // self.damage_divisor

    def report(self, charge_probability: float) -> VampyreBonus:
        return VampyreBonus(
            tier=self.tier,
            attack_source=self.attack_source,
            weapon_accuracy_percent=self.weapon_accuracy_percent,
            ring_accuracy_percent=self.ring_accuracy_percent,
            weapon_damage_percent=self.weapon_damage_percent,
            ring_damage_percent=self.ring_damage_percent,
            damage_divisor=self.damage_divisor,
            hit_cap=self.hit_cap,
            ring_active=self.ring_active,
            ring_charge_probability=charge_probability,
        )


def target_tier(traits: tuple[str, ...]) -> int:
    if "vampyre3" in traits:
        return 3
    if "vampyre2" in traits:
        return 2
    return int("vampyre1" in traits)


@lru_cache(maxsize=2048)
def resolve(
    tier: int, style: str, weapon_id: int | None, silver_bolts: bool, ring: bool
) -> VampyreRule | None:
    if not tier:
        return None
    melee = style in {"stab", "slash", "crush"}
    specialist = weapon_id in SPECIALISTS and (
        (melee and weapon_id != BLISTERWOOD_STAKE)
        or (style == "ranged" and weapon_id == BLISTERWOOD_STAKE)
    )
    silver = (
        specialist
        or (melee and weapon_id in SILVER_WEAPONS)
        or (style == "ranged" and silver_bolts)
    )
    source: AttackSource = "ordinary"
    if specialist:
        source = "ivandis_rod" if weapon_id in RODS else "specialist"
    elif silver:
        source = "silver"
    legal = tier == 1 or (tier == 2 and (silver or ring)) or source == "specialist"
    full_damage = tier == 1 or specialist
    accuracy, damage = (
        SPECIALISTS[weapon_id]
        if specialist and weapon_id is not None
        else (0, 10 if tier == 1 and silver else 0)
    )
    return VampyreRule(
        tier,
        source,
        legal,
        accuracy,
        15 if ring and silver else 0,
        damage,
        10 if ring and full_damage else 0,
        2 if tier == 2 and ring and not specialist else 1,
        10 if tier == 2 and silver and not specialist and not ring else None,
        ring,
    )


class HitStats(NamedTuple):
    mean: float
    maximum: int
    positive_chance: float


@lru_cache(maxsize=8192)
def hits(
    rule: VampyreRule,
    maximum: int,
    armour: int,
    floor: int = 1,
    minimum: int = 0,
    bonus: int = 0,
    divisor: int = 1,
    replace_roll: bool = False,
    sang: bool = False,
    mark: int = 0,
    vulnerability: int = 100,
) -> HitStats:
    """Uniform landed roll, ordered attacker transforms, then target transforms."""
    total = positive = highest = 0
    for roll in range(minimum, maximum + 1):
        if sang:
            roll = max(1, roll) + 8
        if mark:
            roll += (roll * mark // 100) * vulnerability // 100
        damage = roll if replace_roll else rule.scale(roll)
        damage = max(floor, damage + bonus) // divisor
        highest = max(0, rule.limit(damage) - armour)
        total += highest
        positive += highest > 0
    count = maximum - minimum + 1
    return HitStats(total / count, highest, positive / count)


def charge_probability(
    accuracy: float, pattern: str, bypass: float, hopper_accuracy: float | None
) -> float:
    miss = (1 - accuracy) * (1 - bypass)
    if pattern == "independent_double":
        miss *= 1 - accuracy
    if hopper_accuracy is not None:
        from tracker.gear.hopper import PROC_CHANCE

        miss *= 1 - PROC_CHANCE * (hopper_accuracy + (1 - hopper_accuracy) * bypass / 3)
    return 1 - miss
