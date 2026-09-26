"""Shared factual account types and explicit unknown states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import NoReturn


class Tri(Enum):
    """Three-valued truth; missing observations cannot be coerced to false."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"

    def __bool__(self) -> NoReturn:
        raise TypeError(f"{self!r} has no truth value; compare all three members explicitly")

    @classmethod
    def from_bool(cls, value: bool) -> Tri:
        return cls.SATISFIED if value else cls.UNSATISFIED


class Confidence(IntEnum):
    """Confidence in a factual price derived from its trade timestamp."""

    LOW = 0
    MEDIUM = 1
    HIGH = 2


class UnlockState(Enum):
    UNLOCKED = "unlocked"
    AVAILABLE = "available"
    LOCKED = "locked"
    UNKNOWN = "unknown"


class QuestStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


class AccountType(Enum):
    MAIN = "main"
    IRONMAN = "ironman"
    HARDCORE = "hardcore"
    ULTIMATE = "ultimate"
    GROUP = "group"


class Source(Enum):
    """Observation provenance, ordered separately from source freshness."""

    RUNELITE = "runelite"
    WISE_OLD_MAN = "wise_old_man"
    HISCORES = "hiscores"
    OSRS_WIKI_PRICES = "osrs_wiki_prices"
    MANUAL = "manual"
    DERIVED = "derived"


SOURCE_PRECEDENCE: tuple[Source, ...] = (
    Source.RUNELITE,
    Source.WISE_OLD_MAN,
    Source.HISCORES,
)


class PriceSelectionPolicy(Enum):
    """Deterministic selection of an acquisition price from known facts."""

    ACQUISITION_COST = "acquisition_cost"


class PriceSourceLayer(Enum):
    """Provenance layer for an on-demand resolved price."""

    LIVE = "live"
    CACHED = "cached"
    STATIC_HINT = "static_hint"
    UNKNOWN = "unknown"


class Container(Enum):
    BANK = "bank"
    INVENTORY = "inventory"
    EQUIPMENT = "equipment"


class GpSensitivity(Enum):
    """Stored account preference retained pending a separate product decision.

    Current factual Gear and price operations do not read this preference.
    """

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class SkillState:
    """An observed skill. Missing XP remains unknown, rather than zero."""

    level: int
    xp: int | None
    source: Source
    observed_at: datetime
