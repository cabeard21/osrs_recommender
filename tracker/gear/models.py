"""Immutable equipment metadata and transparent combat calculation results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class ElementalSpellBonus(GearModel):
    elements: tuple[Literal["air", "water", "earth", "fire"], ...]
    base_max_hit_bonus: int = Field(default=2, ge=0)


class ElementalAmuletBonus(GearModel):
    item_id: int
    element: Literal["air", "water", "earth", "fire"]
    base_max_hit_bonus: int


class TomeEffect(GearModel):
    element: Literal["fire", "water", "earth"]
    rune_id: int = Field(gt=0)


class TomeBonus(GearModel):
    item_id: int
    element: Literal["fire", "water", "earth"]
    damage_percent: int
    accuracy_percent: int
    fire_pages: Literal["burnt", "searing"] | None = None
    minimum_hit: int = Field(ge=0)


class EquipmentDefinition(GearModel):
    slayer_bonus: Literal["melee", "all"] | None = None
    slayer_staff_enchanted: bool = False
    tome_effect: TomeEffect | None = None
    elemental_spell_bonus: ElementalSpellBonus | None = None
    bolt_effect: Literal["opal", "pearl", "ruby", "diamond", "dragonstone", "onyx"] | None = None
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
    powered_attack_model: (
        Literal[
            "warped",
            "bone",
            "seas",
            "swamp",
            "sanguinesti",
            "shadow",
            "ayak",
            "thammaron",
            "accursed",
        ]
        | None
    ) = None
    powered_attack_base_max_hit: int | None = Field(default=None, ge=1)
    powered_attack_stances: tuple[str, ...] = ()
    two_handed: bool = False
    ammo_type: str | None = None
    ammo_for: tuple[str, ...] = ()
    stackable: bool = False
    requires: Requirement | None = None
    requirements_complete: bool = False
    unsupported_effects: tuple[str, ...] = ()
    # Reviewed base stats remain usable while these bonuses are explicitly omitted.
    omitted_set_effects: tuple[str, ...] = ()
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
    poison_susceptibility: Literal["susceptible", "immune", "unknown"] = "unknown"
    venom_susceptibility: Literal["susceptible", "immune", "unknown"] = "unknown"
    hitpoints: int | None = Field(default=None, ge=1, le=1000000, strict=True)
    current_hitpoints: int | None = Field(default=None, ge=1, le=1000000, strict=True)

    @model_validator(mode="after")
    def validate_hitpoints(self) -> CombatTarget:
        if (
            self.hitpoints is not None
            and self.current_hitpoints is not None
            and self.current_hitpoints > self.hitpoints
        ):
            raise ValueError("Current hitpoints cannot exceed base hitpoints.")
        return self

    traits: tuple[str, ...] = ()
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


class BoltPerformance(GearModel):
    family: str
    proc_chance: float
    activation_probability: float
    expected_damage_per_attack: float
    expected_damage_delta: float
    total_max_hit: int
    normal_max_hit: int
    target_hitpoints: int | None = None
    diary_boosted: bool


class HopperPerformance(GearModel):
    proc_chance: float
    secondary_accuracy: float
    secondary_max_hit: int
    expected_damage_delta: float
    expected_ammunition_per_attack: float
    approximate: bool = True
    assumptions: tuple[str, ...]


class SlayerEffect(GearModel):
    item_id: int
    kind: Literal["mask", "magic_dart"]
    accuracy_numerator: int = 1
    damage_numerator: int = 1
    denominator: int = 1
    base_max_hit: int | None = None


class LeafyBonus(GearModel):
    item_id: int
    damage_numerator: int = 47
    denominator: int = 40


class SeekingArrowBonus(GearModel):
    item_id: int
    minimum_hit: int = 3


class StatusDamage(GearModel):
    kind: Literal["venom", "poison", "unknown"]
    duration_seconds: int
    expected_damage: float
    dps: float
    application_chance: float
    limitations: tuple[str, ...] = ()


class CombatPerformance(GearModel):
    direct_dps: float | None = None
    status_damage: StatusDamage | None = None
    leafy_bonus: LeafyBonus | None = None
    seeking_arrow_bonus: SeekingArrowBonus | None = None
    slayer_effects: tuple[SlayerEffect, ...] = ()
    tome_bonus: TomeBonus | None = None
    aquanite_hopper: HopperPerformance | None = None
    elemental_amulet_bonus: ElementalAmuletBonus | None = None
    bolt_effect: BoltPerformance | None = None
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
