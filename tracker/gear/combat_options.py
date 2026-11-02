"""Legal ordinary weapon attacks and factual account eligibility.

The equipment catalog's reviewed attack profiles are authoritative. Missing
profiles and missing autocast metadata are unknown, never inferred as legal.
Consumable availability is reported separately from access eligibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tracker.accounts.requirements import evaluate_requirement
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.requirements import QuestLeaf, SkillLeaf, UnlockLeaf
from tracker.domain.types import Tri
from tracker.gear.combat import ANCIENT_SPELLS, IBAN_STAVES, SPELLS
from tracker.gear.facts import observed_ownership
from tracker.gear.models import EquipmentDefinition

MELEE_TYPES = frozenset({"stab", "slash", "crush"})
RANGED_TYPES = frozenset({"light", "standard", "heavy"})
MELEE_STANCES = frozenset({"accurate", "aggressive", "defensive", "controlled"})
RANGED_STANCES = frozenset({"accurate", "rapid", "longrange"})
MAGIC_STANCES = frozenset({"accurate", "defensive"})


class CombatOption(BaseModel):
    """One legal attack; availability is independent of consumable observations."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    attack_type: str
    stance: str
    spell: str | None = None
    powered_attack: str | None = None
    availability: Literal["satisfied", "unsatisfied", "unknown"] = "satisfied"
    reasons: tuple[str, ...] = ()
    runes: Literal["satisfied", "unsatisfied", "unknown", "not_applicable"] = "not_applicable"
    ammunition: Literal["satisfied", "unsatisfied", "unknown", "not_applicable"] = "not_applicable"
    charges: Literal["satisfied", "unsatisfied", "unknown", "not_applicable"] = "not_applicable"

    @property
    def available(self) -> bool:
        return self.availability == "satisfied"

    @property
    def reason(self) -> str | None:
        return "; ".join(self.reasons) if self.reasons else None

    @property
    def style(self) -> str:
        return "ranged" if self.attack_type in RANGED_TYPES else self.attack_type


def _skill_status(snapshot: AccountSnapshot, skill: str, level: int) -> Tri:
    return evaluate_requirement(snapshot, SkillLeaf(skill=skill, level=level)).status


def _standard_spellbook_status(snapshot: AccountSnapshot) -> Tri:
    # Standard magic is available by default. Sync clients may omit its
    # redundant unlock row; preserve an explicit locked/unknown observation.
    if "spellbook_standard" not in snapshot.unlocks:
        return Tri.SATISFIED
    return evaluate_requirement(snapshot, UnlockLeaf(key="spellbook_standard")).status


def _ranged_type(weapon: EquipmentDefinition) -> str:
    # Mirrors the target-defence category used by the shared combat scorer.
    if weapon.ammo_for and weapon.ammo_for[0].startswith("bolt:"):
        return "heavy"
    return "standard" if weapon.ammo_for else "light"


def _ammunition_status(
    snapshot: AccountSnapshot, weapon: EquipmentDefinition
) -> Literal["satisfied", "unsatisfied", "unknown", "not_applicable"]:
    if not weapon.ammo_for:
        return "not_applicable"
    ids = []
    for ammo in weapon.ammo_for:
        parts = ammo.split(":", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            return "unknown"
        ids.append(int(parts[1]))
    statuses = {observed_ownership(snapshot, item_id)["status"] for item_id in ids}
    if "owned" in statuses:
        return "satisfied"
    return "unsatisfied" if statuses == {"unowned"} else "unknown"


def _account_status(*checks: tuple[Tri, str]) -> tuple[str, tuple[str, ...]]:
    reasons = tuple(reason for status, reason in checks if status is not Tri.SATISFIED)
    if any(status is Tri.UNSATISFIED for status, _ in checks):
        return "unsatisfied", reasons
    if any(status is Tri.UNKNOWN for status, _ in checks):
        return "unknown", reasons
    return "satisfied", ()


def enumerate_combat_options(
    weapon: EquipmentDefinition | None,
    snapshot: AccountSnapshot,
    *,
    discipline: str,
    levels: Mapping[str, int],
    include_weapon_restricted: bool = False,
) -> tuple[CombatOption, ...]:
    """Return legal profiles including locked and unknown account options.

    `levels` is accepted for the optimizer's existing call contract. Factual
    eligibility comes from AccountSnapshot via the shared requirement evaluator.
    `include_weapon_restricted` exposes staff-specific spells for account-facing
    filters; actual attack enumeration leaves it false to enforce weapon pairing.
    """
    _ = levels
    if discipline == "melee":
        profiles: tuple[tuple[str, str], ...]
        if weapon is None:
            profiles = (("crush", "accurate"), ("crush", "aggressive"), ("crush", "defensive"))
        else:
            profiles = weapon.attack_profiles
        account = _account_status(
            (_skill_status(snapshot, "attack", 1), "Attack level is unknown"),
            (_skill_status(snapshot, "strength", 1), "Strength level is unknown"),
        )
        return tuple(
            CombatOption(
                attack_type=attack,
                stance=stance,
                availability=account[0],
                reasons=account[1],
            )
            for attack, stance in profiles
            if attack in MELEE_TYPES and stance in MELEE_STANCES
        )
    if discipline == "ranged":
        if weapon is None:
            return ()
        kind = _ranged_type(weapon)
        status, reasons = _account_status(
            (_skill_status(snapshot, "ranged", 1), "Ranged level is unknown"),
        )
        return tuple(
            CombatOption(
                attack_type=kind,
                stance=stance,
                availability=status,
                reasons=reasons,
                ammunition=_ammunition_status(snapshot, weapon),
            )
            for attack, stance in weapon.attack_profiles
            if attack == "ranged" and stance in RANGED_STANCES
        )
    if discipline != "magic":
        return ()

    options: list[CombatOption] = []
    book = _standard_spellbook_status(snapshot)
    for spell, (level, _) in SPELLS.items():
        ancient = spell in ANCIENT_SPELLS
        if ancient and weapon is None and not include_weapon_restricted:
            continue
        if (
            spell == "iban_blast"
            and not include_weapon_restricted
            and (weapon is None or weapon.id not in IBAN_STAVES)
        ):
            continue
        if weapon is not None and spell not in weapon.spell_compatibility:
            continue
        extra_checks = (
            (
                (
                    evaluate_requirement(snapshot, QuestLeaf(quest_id="desert_treasure_i")).status,
                    "Desert Treasure I completion is not confirmed",
                ),
                *(
                    (
                        evaluate_requirement(snapshot, UnlockLeaf(key=key)).status,
                        "Ancient Magicks unlock is not confirmed",
                    )
                    for key in ("spellbook_ancient", "ancient_magicks")
                    if key in snapshot.unlocks
                ),
            )
            if ancient
            else (
                (_skill_status(snapshot, "attack", 50), "Attack level 50 required"),
                (
                    evaluate_requirement(snapshot, QuestLeaf(quest_id="underground_pass")).status,
                    "Underground Pass completion is not confirmed",
                ),
            )
            if spell == "iban_blast"
            else ()
        )
        status, reasons = _account_status(
            (_skill_status(snapshot, "magic", level), f"Magic level {level} required"),
            *(((book, "Standard spellbook unlock is not confirmed"),) if not ancient else ()),
            *extra_checks,
        )
        stances = MAGIC_STANCES if weapon is not None else frozenset({"accurate"})
        options.extend(
            CombatOption(
                attack_type="magic",
                stance=stance,
                spell=spell,
                availability=status,
                reasons=reasons,
                runes="unknown",
                charges="unknown" if spell == "iban_blast" else "not_applicable",
            )
            for stance in sorted(stances)
        )
    if (
        weapon is not None
        and weapon.powered_attack
        and weapon.powered_attack_base_max_hit
        and weapon.powered_attack_stances
    ):
        status, reasons = _account_status(
            (_skill_status(snapshot, "magic", 1), "Magic level is unknown"),
        )
        options.extend(
            CombatOption(
                attack_type="magic",
                stance=stance,
                powered_attack=weapon.powered_attack,
                availability=status,
                reasons=reasons,
                charges="unknown",
            )
            for stance in weapon.powered_attack_stances
            if stance in {"accurate", "longrange"}
        )
    return tuple(options)


def eligible_combat_options(
    weapon: EquipmentDefinition | None,
    snapshot: AccountSnapshot,
    *,
    discipline: str,
    levels: Mapping[str, int],
) -> tuple[CombatOption, ...]:
    """Legal attacks whose account requirements have been observed satisfied."""
    return tuple(
        option
        for option in enumerate_combat_options(
            weapon, snapshot, discipline=discipline, levels=levels
        )
        if option.available
    )


def ancient_spell_problem(
    weapon: EquipmentDefinition | None,
    snapshot: AccountSnapshot,
    spell: str,
    stance: str,
) -> str | None:
    """Apply the same Ancient access gates to fixed and automatic roles."""
    if spell not in ANCIENT_SPELLS:
        return None
    matches = tuple(
        option
        for option in enumerate_combat_options(weapon, snapshot, discipline="magic", levels={})
        if option.spell == spell and option.stance == stance
    )
    if any(option.available for option in matches):
        return None
    return next(
        (option.reason for option in matches if option.reason),
        "Ancient Magicks requires a reviewed compatible autocast weapon and casting stance.",
    )
