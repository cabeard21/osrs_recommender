"""Execution-scoped immutable attack constants, separate from equipment totals.

Legality remains in combat. Keys combine numerical level values and strongly held
immutable records, so potion, target and prayer changes invalidate preparation.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from math import floor
from types import MappingProxyType
from typing import Any, NamedTuple, cast
from weakref import ReferenceType, ref

from tracker.gear.models import (
    CombatTarget,
    EquipmentBonuses,
    EquipmentDefinition,
    PlayerDefenceRolls,
)
from tracker.gear.powered import base_hit
from tracker.gear.prayers import PrayerEffects, effects
from tracker.gear.ranged_numerics import CacheInfo


class AttackKey(NamedTuple):
    style: str
    stance: str
    spell: str
    powered_attack: str | None
    powered_model: str | None
    powered_base: int | None
    speed: int
    pattern: str
    attack_level: int
    strength_level: int
    magic_level: int
    defence_level: int
    prayers: PrayerEffects
    target_level: int
    target_bonus: int
    weakness_element: str | None
    weakness_percent: int
    armour: int
    damage_cap: int | None


@dataclass(frozen=True, slots=True)
class DefensiveConstants:
    physical: int | None
    magical: int | None
    limitations: tuple[str, ...]

    def rolls(self, bonuses: EquipmentBonuses) -> Mapping[str, int | None]:
        return MappingProxyType(
            {
                style: None
                if level is None
                else max(0, level * (getattr(bonuses, "defence_" + style) + 64))
                for style, level in (
                    ("stab", self.physical),
                    ("slash", self.physical),
                    ("crush", self.physical),
                    ("ranged", self.physical),
                    ("magic", self.magical),
                )
            }
        )

    def report(self, bonuses: EquipmentBonuses) -> PlayerDefenceRolls:
        return PlayerDefenceRolls(**self.rolls(bonuses), limitations=self.limitations)


@dataclass(frozen=True, slots=True)
class PreparedAttack:
    style: str
    attack_level: int
    strength_level: int
    spell_base: int
    magic_damage: int
    shadow: bool
    weakness_applied: bool
    weakness_percent: int
    weakness_hit: int
    defence_roll: int
    speed: int
    pattern: str
    armour: int
    damage_cap: int | None
    sanguinesti: bool
    player_defence: DefensiveConstants
    prayers: PrayerEffects

    def rolls(self, bonuses: EquipmentBonuses) -> tuple[int, int, int]:
        """Return maximum, attack roll and separately truncated weakness roll."""
        if self.style == "magic":
            damage = min(100, bonuses.magic_damage * 3) if self.shadow else bonuses.magic_damage
            accuracy = bonuses.magic * 3 if self.shadow else bonuses.magic
            maximum = floor(self.spell_base * (100 + damage + self.magic_damage) / 100)
            attack = self.attack_level * (accuracy + 64)
            weakness_roll = attack * self.weakness_percent // 100 if self.weakness_applied else 0
            return maximum + self.weakness_hit, attack + weakness_roll, weakness_roll
        strength = bonuses.ranged_strength if self.style == "ranged" else bonuses.melee_strength
        maximum = floor(0.5 + self.strength_level * (strength + 64) / 640)
        return maximum, self.attack_level * (getattr(bonuses, self.style) + 64), 0


def _prepare(key: AttackKey) -> PreparedAttack:
    # Import lazily so combat keeps ownership of the reviewed spell definitions.
    from tracker.gear.combat import ANCIENT_SPELLS, ELEMENTAL_SPELLS, SPELLS

    magical = key.style == "magic"
    ranged = key.style == "ranged"
    base: int | None = 0
    element = None
    if magical:
        if key.powered_attack is not None:
            base = (
                base_hit(key.powered_model, key.magic_level)
                if key.powered_model
                else key.powered_base
            )
            assert base is not None
        elif key.spell == "iban_blast" or key.spell in ANCIENT_SPELLS:
            base = SPELLS[key.spell][1]
        else:
            tier = key.spell.split("_")[1]
            base = max(
                damage
                for name, (level, damage) in ELEMENTAL_SPELLS.items()
                if name.endswith("_" + tier) and level <= key.magic_level
            )
        if key.powered_attack is None and key.spell in ELEMENTAL_SPELLS:
            element = key.spell.split("_")[0]
            element = "air" if element == "wind" else element
    applied = element is not None and element == key.weakness_element and key.weakness_percent > 0
    assert base is not None
    attack_prayer = (
        key.prayers.magic_accuracy
        if magical
        else key.prayers.ranged_accuracy
        if ranged
        else key.prayers.attack
    )
    attack_stance = (
        (2 if key.stance == "accurate" else 0)
        if magical
        else (3 if key.stance == "accurate" else int(key.stance == "controlled"))
    )
    strength_stance = (
        (3 if key.stance == "accurate" else 0)
        if ranged
        else (3 if key.stance == "aggressive" else int(key.stance == "controlled"))
    )
    defence = key.defence_level * key.prayers.defence // 100
    magic = key.magic_level * key.prayers.magic_defence // 100
    defence_stance = (
        3 if key.stance in {"defensive", "longrange"} else int(key.stance == "controlled")
    )
    return PreparedAttack(
        style=key.style,
        attack_level=key.attack_level * attack_prayer // 100
        + (9 if magical else 8)
        + attack_stance,
        strength_level=key.strength_level
        * (key.prayers.ranged_strength if ranged else key.prayers.strength)
        // 100
        + 8
        + strength_stance,
        spell_base=base,
        magic_damage=key.prayers.magic_damage,
        shadow=key.powered_attack is not None and key.powered_model == "shadow",
        weakness_applied=applied,
        weakness_percent=key.weakness_percent,
        weakness_hit=base * key.weakness_percent // 100 if applied else 0,
        defence_roll=(key.target_level + 9) * (key.target_bonus + 64),
        speed=(key.speed if key.powered_attack is not None else 5)
        if magical
        else (max(1, key.speed - 1) if ranged and key.stance == "rapid" else key.speed),
        pattern="single" if magical else key.pattern,
        armour=0 if magical else key.armour,
        damage_cap=key.damage_cap,
        sanguinesti=key.powered_attack is not None and key.powered_model == "sanguinesti",
        player_defence=DefensiveConstants(
            defence + defence_stance + 8 if defence > 0 else None,
            magic * 7 // 10 + defence * 3 // 10 + defence_stance + 8
            if defence > 0 and magic > 0
            else None,
            tuple(
                f"Player {name} level is unknown."
                for name, level in (("Defence", key.defence_level), ("Magic", key.magic_level))
                if level < 1
            ),
        ),
        prayers=key.prayers,
    )


@dataclass(frozen=True, slots=True)
class _Entry:
    weapon: EquipmentDefinition | None
    target: CombatTarget
    prayers: PrayerEffects
    attack: PreparedAttack
    role_ref: ReferenceType[object] | None = None
    levels: Mapping[str, int] | None = None


def _discard_role(
    context_ref: ReferenceType[PreparedCombat],
    identity: tuple[object, ...],
    role_ref: ReferenceType[object],
) -> None:
    """Discard dead identity entries without retaining their execution context."""
    context = context_ref()
    if context is not None:
        entry = context._entries.get(identity)
        # An address can already have a replacement entry. Never delete that row.
        if entry is not None and entry.role_ref is role_ref:
            del context._entries[identity]


class PreparedCombat:
    def __init__(self, capacity: int) -> None:
        # This exact project type has frozen scalar attack fields and an immutable
        # target. Arbitrary caller objects use the value-based fallback instead.
        from tracker.gear.optimizer import RoleConfig

        self._role_type = RoleConfig
        self.capacity = capacity
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[tuple[object, ...], _Entry] = OrderedDict()
        self._levels: dict[int, Mapping[str, int]] = {}
        self._last_role: _Entry | None = None
        self._last_role_owner: object = None
        self.last_prepared: PreparedAttack | None = None

    def cache_info(self) -> CacheInfo:
        return CacheInfo(self.hits, self.misses, self.capacity, len(self._entries))

    def prepare_role(
        self,
        weapon: EquipmentDefinition | None,
        role: Any,
        levels: Mapping[str, int],
        target: CombatTarget,
    ) -> PreparedAttack | None:
        previous = self._last_role
        if (
            previous is not None
            and self._last_role_owner is role
            and previous.weapon is weapon
            and previous.levels is levels
            and previous.target is target
        ):
            self.hits += 1
            return previous.attack
        if type(role) is not self._role_type or id(levels) not in self._levels:
            return None
        identity = (id(weapon), id(role), id(levels), id(target))
        cached = self._entries.get(identity)
        if cached is not None and cached.role_ref is not None and cached.role_ref() is role:
            self.hits += 1
            self._last_role = cached
            self._last_role_owner = role
            return cached.attack
        self.misses += 1
        prayers = effects(role.active_prayer_ids)
        result = self._build(
            weapon,
            role.style,
            levels,
            target,
            role.stance,
            role.spell,
            role.powered_attack,
            prayers,
        )
        role_ref = ref(cast(object, role), partial(_discard_role, ref(self), identity))
        entry = _Entry(weapon, target, prayers, result, role_ref, levels)
        self._remember(identity, entry)
        if self.capacity:
            self._last_role = entry
            self._last_role_owner = role
        return result

    def _remember(self, identity: tuple[object, ...], entry: _Entry) -> None:
        # Any insertion can evict the shortcut's entry. Invalidate it even for
        # generic callers; prepare_role reinstates only its newly retained entry.
        self._last_role = None
        self._last_role_owner = None
        if self.capacity:
            self._entries[identity] = entry
            if len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
        self.last_prepared = entry.attack

    def prepare(
        self,
        weapon: EquipmentDefinition | None,
        style: str,
        levels: Mapping[str, int],
        target: CombatTarget,
        stance: str,
        spell: str,
        powered_attack: str | None,
        prayers: PrayerEffects,
    ) -> PreparedAttack:
        # These three records are deeply immutable. Holding strong references in
        # each entry prevents identity reuse until eviction; levels are mutable
        # mappings, so read their actual numerical dependencies on every call.
        attack_level = levels[style if style in {"magic", "ranged"} else "attack"]
        strength_level = levels.get("ranged" if style == "ranged" else "strength", 0)
        magic_level, defence_level = levels.get("magic", 0), levels.get("defence", 0)
        identity = (
            style,
            stance,
            spell,
            powered_attack,
            id(weapon),
            id(target),
            id(prayers),
            attack_level,
            strength_level,
            magic_level,
            defence_level,
        )
        cached = self._entries.get(identity)
        if cached is not None:
            self.hits += 1
            return cached.attack
        self.misses += 1
        result = self._build(weapon, style, levels, target, stance, spell, powered_attack, prayers)
        self._remember(identity, _Entry(weapon, target, prayers, result))
        return result

    def _build(
        self,
        weapon: EquipmentDefinition | None,
        style: str,
        levels: Mapping[str, int],
        target: CombatTarget,
        stance: str,
        spell: str,
        powered_attack: str | None,
        prayers: PrayerEffects,
    ) -> PreparedAttack:
        target_bonus = getattr(target.bonuses, style)
        if style == "ranged":
            kind = (
                "heavy"
                if weapon and weapon.ammo_for and weapon.ammo_for[0].startswith("bolt:")
                else "standard"
                if weapon and weapon.ammo_for
                else "light"
            )
            subtype = getattr(target, "ranged_" + kind)
            target_bonus = target_bonus if subtype is None else subtype
        key = AttackKey(
            style,
            stance,
            spell,
            powered_attack,
            weapon.powered_attack_model if weapon else None,
            weapon.powered_attack_base_max_hit if weapon else None,
            weapon.attack_speed if weapon else 4,
            weapon.attack_pattern if weapon else "single",
            levels[style if style in {"magic", "ranged"} else "attack"],
            levels.get("ranged" if style == "ranged" else "strength", 0),
            levels.get("magic", 0),
            levels.get("defence", 0),
            prayers,
            target.magic_level if style == "magic" else target.defence_level,
            target_bonus,
            target.weakness_element,
            target.weakness_percent,
            target.flat_armour,
            target.damage_cap,
        )
        return _prepare(key)


_ACTIVE: ContextVar[PreparedCombat | None] = ContextVar("prepared_combat", default=None)


def current() -> PreparedCombat | None:
    return _ACTIVE.get()


def active() -> bool:
    return current() is not None


def freeze_levels(levels: Mapping[str, int]) -> Mapping[str, int]:
    """Own a frozen copy inside this execution; never trust an external proxy."""
    context = current()
    if context is None:
        return levels
    frozen = MappingProxyType(dict(levels))
    context._levels[id(frozen)] = frozen
    return frozen


@contextmanager
def prepared_combat(capacity: int = 4096) -> Iterator[PreparedCombat]:
    if capacity < 0:
        raise ValueError("capacity must be nonnegative")
    context = PreparedCombat(capacity)
    token = _ACTIVE.set(context)
    try:
        yield context
    finally:
        _ACTIVE.reset(token)
