"""Reviewed sustained-active stat prayers; no drain, protection or endurance model.

References reviewed 2026-11-04: OSRS Wiki Prayer and prayer pages; formula
reference weirdgloop/osrs-dps-calc src/enums/Prayer.ts at
19a8e0b7dad50c136837a92c29ac2c1a5abce4b9 and NPCVsPlayerCalc.ts.
Zeal requirements: abextm/cs2-scripts scripts 10193/10194 at
d022d6f70b76e3890cab1287a7f45e905c2848d8 (including Knight Waves and Defence).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import combinations
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tracker.accounts.requirements import evaluate_requirement
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.requirements import UnlockLeaf
from tracker.domain.types import Tri

MODEL_VERSION = "active-stat-prayers-v1"
CATALOG_REVISION = "stat-prayers-2026-11-04"


@dataclass(frozen=True)
class PrayerEffects:
    attack: int = 100
    strength: int = 100
    ranged_accuracy: int = 100
    ranged_strength: int = 100
    magic_accuracy: int = 100
    defence: int = 100
    magic_defence: int = 100
    magic_damage: int = 0


NO_PRAYERS = PrayerEffects()


@dataclass(frozen=True)
class Prayer:
    id: str
    name: str
    level: int
    group: str
    modifiers: PrayerEffects
    unlock: str | None = None
    defence_level: int = 1
    attack_level: int = 1
    strength_level: int = 1
    replaces: str | None = None


_PRAYERS = (
    Prayer("thick_skin", "Thick Skin", 1, "defence", PrayerEffects(defence=105)),
    Prayer("burst_of_strength", "Burst of Strength", 4, "strength", PrayerEffects(strength=105)),
    Prayer("clarity_of_thought", "Clarity of Thought", 7, "attack", PrayerEffects(attack=105)),
    Prayer(
        "sharp_eye",
        "Sharp Eye",
        8,
        "ranged",
        PrayerEffects(ranged_accuracy=105, ranged_strength=105),
    ),
    Prayer(
        "mystic_will",
        "Mystic Will",
        9,
        "magic",
        PrayerEffects(magic_accuracy=105, magic_defence=105),
    ),
    Prayer("rock_skin", "Rock Skin", 10, "defence", PrayerEffects(defence=110)),
    Prayer(
        "superhuman_strength", "Superhuman Strength", 13, "strength", PrayerEffects(strength=110)
    ),
    Prayer("improved_reflexes", "Improved Reflexes", 16, "attack", PrayerEffects(attack=110)),
    Prayer(
        "hawk_eye",
        "Hawk Eye",
        26,
        "ranged",
        PrayerEffects(ranged_accuracy=110, ranged_strength=110),
    ),
    Prayer(
        "mystic_lore",
        "Mystic Lore",
        27,
        "magic",
        PrayerEffects(magic_accuracy=110, magic_defence=110, magic_damage=1),
    ),
    Prayer("steel_skin", "Steel Skin", 28, "defence", PrayerEffects(defence=115)),
    Prayer("ultimate_strength", "Ultimate Strength", 31, "strength", PrayerEffects(strength=115)),
    Prayer("incredible_reflexes", "Incredible Reflexes", 34, "attack", PrayerEffects(attack=115)),
    Prayer(
        "eagle_eye",
        "Eagle Eye",
        44,
        "ranged",
        PrayerEffects(ranged_accuracy=115, ranged_strength=115),
    ),
    Prayer(
        "mystic_might",
        "Mystic Might",
        45,
        "magic",
        PrayerEffects(magic_accuracy=115, magic_defence=115, magic_damage=2),
    ),
    Prayer(
        "chivalry",
        "Chivalry",
        60,
        "combined",
        PrayerEffects(attack=115, strength=118, defence=120),
        "knight_waves",
        65,
    ),
    Prayer(
        "deadeye",
        "Deadeye",
        62,
        "ranged",
        PrayerEffects(ranged_accuracy=118, ranged_strength=118, defence=105),
        "deadeye",
        replaces="eagle_eye",
    ),
    Prayer(
        "mystic_vigour",
        "Mystic Vigour",
        63,
        "magic",
        PrayerEffects(magic_accuracy=118, magic_defence=118, magic_damage=3, defence=105),
        "mystic_vigour",
        replaces="mystic_might",
    ),
    Prayer(
        "piety",
        "Piety",
        70,
        "combined",
        PrayerEffects(attack=120, strength=123, defence=125),
        "knight_waves",
        70,
    ),
    Prayer(
        "rigour",
        "Rigour",
        74,
        "combined",
        PrayerEffects(ranged_accuracy=120, ranged_strength=123, defence=125),
        "rigour",
        70,
    ),
    Prayer(
        "augury",
        "Augury",
        77,
        "combined",
        PrayerEffects(magic_accuracy=125, magic_defence=125, magic_damage=4, defence=125),
        "augury",
        70,
    ),
    Prayer(
        "zeal",
        "Zeal",
        84,
        "combined",
        PrayerEffects(attack=125, strength=128, defence=125),
        "zeal",
        defence_level=70,
        attack_level=75,
        strength_level=75,
        replaces="piety",
    ),
)
_BY_ID = {p.id: p for p in _PRAYERS}


def legal(ids: Sequence[str]) -> bool:
    if len(set(ids)) != len(ids) or any(key not in _BY_ID for key in ids):
        return False
    groups = [_BY_ID[key].group for key in ids]
    if len(groups) != len(set(groups)):
        return False
    if "combined" in groups:
        return len(groups) == 1
    offensive = set(groups) - {"defence"}
    return offensive <= {"attack", "strength"} or len(offensive) <= 1


class PrayerPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["disabled", "fixed", "optimize"] = "disabled"
    selected_ids: tuple[str, ...] = Field(default=(), max_length=3)
    allowed_ids: tuple[str, ...] = Field(default=(), max_length=len(_PRAYERS))

    @model_validator(mode="after")
    def validate_selection(self) -> PrayerPolicy:
        for ids in (self.selected_ids, self.allowed_ids):
            if len(set(ids)) != len(ids) or any(key not in _BY_ID for key in ids):
                raise ValueError("Prayer IDs must be unique reviewed catalog IDs")
        if self.mode != "fixed" and self.selected_ids:
            raise ValueError("Selected prayers require fixed mode")
        if self.mode != "optimize" and self.allowed_ids:
            raise ValueError("Allowed prayers require optimize mode")
        if not legal(self.selected_ids):
            raise ValueError("Selected prayers conflict")
        return self


def availability(
    prayer: Prayer, snapshot: AccountSnapshot, levels: Mapping[str, int]
) -> tuple[str, tuple[str, ...]]:
    checks = [(levels.get("prayer", 0), prayer.level, "Prayer")]
    checks += [
        (levels.get(skill, 0), required, skill.title())
        for skill, required in (
            ("defence", prayer.defence_level),
            ("attack", prayer.attack_level),
            ("strength", prayer.strength_level),
        )
        if required > 1
    ]
    reasons = tuple(
        f"{name} level {required} required"
        for current, required, name in checks
        if current < required
    )
    statuses = [
        Tri.UNKNOWN if current < 1 else Tri.UNSATISFIED
        for current, required, _ in checks
        if current < required
    ]
    unlocks = ((prayer.unlock,) if prayer.unlock else ()) + (
        ("knight_waves",) if prayer.id == "zeal" else ()
    )
    for unlock in unlocks:
        result = evaluate_requirement(snapshot, UnlockLeaf(key=unlock))
        if result.status is not Tri.SATISFIED:
            reasons += (f"{unlock} unlock is {result.status.value}",)
            statuses.append(result.status)
    for upgrade in _PRAYERS:
        if (
            upgrade.replaces == prayer.id
            and evaluate_requirement(snapshot, UnlockLeaf(key=upgrade.unlock or "")).status
            is Tri.SATISFIED
        ):
            reasons += (f"Replaced by {upgrade.name}",)
            statuses.append(Tri.UNSATISFIED)
    return (
        "unsatisfied" if Tri.UNSATISFIED in statuses else "unknown" if statuses else "satisfied",
        reasons,
    )


def catalog(
    snapshot: AccountSnapshot | None = None, levels: Mapping[str, int] | None = None
) -> list[dict[str, Any]]:
    current = (
        levels
        if levels is not None
        else ({key: value.level for key, value in snapshot.skills.items()} if snapshot else {})
    )
    rows = []
    for prayer in _PRAYERS:
        row = {
            **asdict(prayer),
            "conflicts": [
                p.id for p in _PRAYERS if p.id != prayer.id and not legal((p.id, prayer.id))
            ],
            "availability": "unknown",
            "access_availability": "unknown",
            "access_reasons": ["Account observations are unavailable"],
            "reasons": ["Account observations are unavailable"],
        }
        if snapshot is not None:
            status, reasons = availability(prayer, snapshot, current)
            access, access_reasons = availability(
                prayer,
                snapshot,
                dict.fromkeys(("prayer", "defence", "attack", "strength"), 99),
            )
            row = {
                **row,
                "availability": status,
                "reasons": list(reasons),
                "access_availability": access,
                "access_reasons": list(access_reasons),
            }
        rows.append(row)
    return rows


def setups(
    policy: PrayerPolicy, snapshot: AccountSnapshot, levels: Mapping[str, int]
) -> tuple[tuple[str, ...], ...]:
    if policy.mode == "disabled":
        return ((),)
    if policy.mode == "fixed":
        for key in policy.selected_ids:
            status, reasons = availability(_BY_ID[key], snapshot, levels)
            if status != "satisfied":
                raise ValueError(f"Prayer {key} unavailable: {'; '.join(reasons)}")
        return (tuple(sorted(policy.selected_ids)),)
    available = tuple(
        sorted(
            key
            for key in policy.allowed_ids
            if availability(_BY_ID[key], snapshot, levels)[0] == "satisfied"
        )
    )
    return tuple(ids for count in range(4) for ids in combinations(available, count) if legal(ids))


def effects(ids: Sequence[str]) -> PrayerEffects:
    """Reuse immutable modifiers regardless of the caller's prayer selection order."""
    if not ids:
        return NO_PRAYERS
    return _cached_effects(tuple(sorted(ids)))


@lru_cache(maxsize=2048)
def _cached_effects(ids: tuple[str, ...]) -> PrayerEffects:
    if not legal(ids):
        raise ValueError("Selected prayers conflict or are unknown")
    return PrayerEffects(
        **{
            name: (0 if name == "magic_damage" else 100)
            + sum(
                getattr(_BY_ID[key].modifiers, name) - (0 if name == "magic_damage" else 100)
                for key in ids
            )
            for name in PrayerEffects.__dataclass_fields__
        }
    )
