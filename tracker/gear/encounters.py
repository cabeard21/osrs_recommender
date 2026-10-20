"""Small source-pinned encounter templates for the supported ordinary-attack subset.

These are custom-request conveniences, not a universal encounter simulation or a
claim that one rotation/kill order describes every fight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tracker.gear.models import CombatTarget, TargetDefenceBonuses
from tracker.gear.optimizer import OptimizationRequest, RoleConfig

SOURCE_REVISION = "89c3e25b344aea90d0189746e4b5f73dde0f0383"
SOURCE_URL = (
    f"https://github.com/weirdgloop/osrs-dps-calc/blob/{SOURCE_REVISION}/cdn/json/monsters.json"
)


@dataclass(frozen=True)
class EncounterPreset:
    id: str
    name: str
    roles: tuple[RoleConfig, ...]
    ordered_roles: tuple[str, ...]
    loop: bool
    limitations: tuple[str, ...]
    version: int = 1
    source_url: str = SOURCE_URL

    @property
    def scoring_supported(self) -> bool:
        """Whether target metadata permits scoring; individual attacks may remain unsupported."""
        return all(
            role.target is not None and not role.target.unsupported_mechanics for role in self.roles
        )

    def to_request(
        self,
        *,
        budget_gp: int = 0,
        max_swaps: int = 8,
        reserved_supply_slots: int = 12,
        mode: Literal["usable", "owned", "future"] = "usable",
    ) -> OptimizationRequest:
        """Use the ordinary request path without removing target capability gates."""
        return OptimizationRequest(
            roles=self.roles,
            ordered_roles=self.ordered_roles,
            loop=self.loop,
            base_role=self.ordered_roles[0],
            budget_gp=budget_gp,
            max_swaps=max_swaps,
            reserved_supply_slots=reserved_supply_slots,
            mode=mode,
        )


def _king(
    role_id: str,
    style: str,
    name: str,
    defence: int,
    magic: int,
    melee_bonus: int,
    ranged_bonus: int,
    magic_bonus: int,
) -> RoleConfig:
    return RoleConfig(
        id=role_id,
        style=style,
        spell="earth_strike" if style == "magic" else "fire_strike",
        target=CombatTarget(
            name=name,
            defence_level=defence,
            magic_level=magic,
            bonuses=TargetDefenceBonuses(
                stab=melee_bonus,
                slash=melee_bonus,
                crush=melee_bonus,
                ranged=ranged_bonus,
                magic=magic_bonus,
            ),
            weakness_element="earth",
            weakness_percent=35,
        ),
    )


def _zulrah(role_id: str, style: str, magic_bonus: int, ranged_bonus: int) -> RoleConfig:
    return RoleConfig(
        id=role_id,
        style=style,
        target=CombatTarget(
            name=f"Zulrah ({role_id})",
            defence_level=300,
            magic_level=300,
            bonuses=TargetDefenceBonuses(magic=magic_bonus, ranged=ranged_bonus),
            weakness_element="fire",
            weakness_percent=50,
            damage_cap=50,
        ),
    )


def encounter_presets() -> tuple[EncounterPreset, ...]:
    """Return fresh immutable templates, in the intended implementation order."""
    return (
        EncounterPreset(
            id="dagannoth_kings",
            name="Dagannoth Kings — illustrative kill cycle",
            roles=(
                _king("supreme", "slash", "Dagannoth Supreme", 128, 255, 10, 550, 255),
                _king("prime", "ranged", "Dagannoth Prime", 255, 255, 255, 10, 255),
                _king("rex", "magic", "Dagannoth Rex", 255, 0, 255, 255, 10),
            ),
            ordered_roles=("supreme", "prime", "rex"),
            loop=True,
            limitations=(
                "This selected kill cycle does not require every pairwise transition.",
                "Equal active-time weights are assumptions, not measured kill durations.",
                "Respawns, travel, survival, Slayer bonuses and downtime are not simulated.",
                "Ordinary attacks only; elemental weakness applies to matching standard spells.",
            ),
        ),
        EncounterPreset(
            id="zulrah_forms",
            name="Zulrah — form comparison template (not a rotation)",
            roles=(
                _zulrah("serpentine", "magic", -45, 50),
                _zulrah("magma", "magic", 0, 300),
                _zulrah("tanzanite", "ranged", 300, 0),
            ),
            ordered_roles=("serpentine", "magma", "tanzanite"),
            loop=False,
            limitations=(
                "Form order is illustrative, not one of Zulrah's timed rotations.",
                "Equal active-time weights do not represent published phase durations.",
                "Jad phases, submerging, movement, venom and snakelings are not simulated.",
                "Attacks with maximum hit above 50 are blocked; the reroll is not approximated.",
            ),
        ),
    )


def get_encounter_preset(preset_id: str) -> EncounterPreset:
    for preset in encounter_presets():
        if preset.id == preset_id:
            return preset
    raise ValueError(f"Unknown encounter preset: {preset_id}")
