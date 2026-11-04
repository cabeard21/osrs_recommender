"""Immutable equipment metadata and transparent combat calculation results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tracker.content.requirements import Requirement
from tracker.content.schema import ItemSlot


class GearModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EquipmentBonuses(GearModel):
    stab: int = 0
    slash: int = 0
    crush: int = 0
    ranged: int = 0
    magic: int = 0
    melee_strength: int = 0
    ranged_strength: int = 0
    magic_damage: float = 0
    defence_stab: int = 0
    defence_slash: int = 0
    defence_crush: int = 0
    defence_ranged: int = 0
    defence_magic: int = 0
    prayer: int = 0


class EquipmentDefinition(GearModel):
    id: int = Field(gt=0)
    name: str
    slot: ItemSlot
    bonuses: EquipmentBonuses = EquipmentBonuses()
    attack_speed: int = Field(default=4, ge=1)
    attack_pattern: Literal["single", "independent_double", "conditional_double"] = "single"
    attack_styles: tuple[str, ...] = ()
    attack_profiles: tuple[tuple[str, str], ...] = ()
    # Reviewed autocast spell IDs only. An empty tuple makes compatibility unknown.
    spell_compatibility: tuple[str, ...] = ()
    powered_attack: str | None = None
    powered_attack_base_max_hit: int | None = Field(default=None, ge=1)
    powered_attack_stances: tuple[str, ...] = ()
    two_handed: bool = False
    ammo_type: str | None = None
    ammo_for: tuple[str, ...] = ()
    stackable: bool = False
    requires: Requirement | None = None
    requirements_complete: bool = False
    unsupported_effects: tuple[str, ...] = ()
    tradeable: bool | None = None
    content_ids: tuple[str, ...] = ()


class TargetDefenceBonuses(GearModel):
    """NPC defence rolls only; no equipment offensive/defensive ambiguity."""

    stab: int = 0
    slash: int = 0
    crush: int = 0
    ranged: int = 0
    magic: int = 0


class TargetSelection(GearModel):
    key: str = Field(min_length=1, max_length=64)
    catalog_revision: str = Field(min_length=1, max_length=128)


class CombatTarget(GearModel):
    name: str = "Generic target (Defence 1, zero bonuses)"
    defence_level: int = Field(default=1, ge=0, le=10000)
    magic_level: int = Field(default=1, ge=0, le=10000)
    bonuses: TargetDefenceBonuses = TargetDefenceBonuses()
    ranged_light: int | None = None
    ranged_standard: int | None = None
    ranged_heavy: int | None = None
    weakness_element: Literal["air", "water", "earth", "fire"] | None = None
    weakness_percent: int = Field(default=0, ge=0, le=1000)
    damage_cap: int | None = Field(default=None, ge=1)
    flat_armour: int = Field(default=0, ge=-10000, le=10000, strict=True)
    unsupported_mechanics: tuple[str, ...] = ()


class ElementalWeakness(GearModel):
    element: Literal["air", "water", "earth", "fire"] | None
    percent: int
    applied: bool
    reason: str | None = None
    max_hit_bonus: int = 0
    attack_roll_bonus: int = 0


class HitsplatPerformance(GearModel):
    accuracy: float
    max_hit: int


class PlayerDefenceRolls(GearModel):
    stab: int | None = Field(default=None, ge=0)
    slash: int | None = Field(default=None, ge=0)
    crush: int | None = Field(default=None, ge=0)
    ranged: int | None = Field(default=None, ge=0)
    magic: int | None = Field(default=None, ge=0)
    limitations: tuple[str, ...] = ()


class CombatPerformance(GearModel):
    player_defence_rolls: PlayerDefenceRolls | None = None
    elemental_weakness: ElementalWeakness | None = None
    supported: bool
    limitations: tuple[str, ...] = ()
    accuracy: float | None = None
    hitsplats: tuple[HitsplatPerformance, ...] = ()
    max_hit: int | None = None
    attack_interval: float | None = None
    dps: float | None = None
    attack_roll: int | None = None
    defence_roll: int | None = None
    bonuses: EquipmentBonuses = EquipmentBonuses()
