"""Immutable observations, with explicit absence and a stable content fingerprint."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from tracker.domain.skills import canonical_skill_states
from tracker.domain.types import QuestStatus, SkillState, UnlockState


@dataclass(frozen=True, slots=True)
class Observation:
    source: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    player_id: int
    username: str
    skills: Mapping[str, SkillState] = field(default_factory=dict)
    quests: Mapping[str, QuestStatus] = field(default_factory=dict)
    quest_observations: Mapping[str, Observation] = field(default_factory=dict)
    unlocks: Mapping[str, UnlockState] = field(default_factory=dict)
    quest_points: int | None = None
    combat_level: int | None = None
    members: bool | None = None
    last_sync_at: datetime | None = None

    def __post_init__(self) -> None:
        # Frozen dataclasses alone do not freeze dictionaries or detach caller-owned data.
        object.__setattr__(self, "skills", MappingProxyType(canonical_skill_states(self.skills)))
        for name in ("quests", "quest_observations", "unlocks"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def summary(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "username": self.username,
            "skills": {
                key: {
                    "level": value.level,
                    "xp": value.xp,
                    "source": value.source.value,
                    "observed_at": value.observed_at.isoformat(),
                }
                for key, value in sorted(self.skills.items())
            },
            "quests": {key: value.value for key, value in sorted(self.quests.items())},
            "quest_observations": {
                key: {"source": value.source, "observed_at": value.observed_at.isoformat()}
                for key, value in sorted(self.quest_observations.items())
            },
            "unlocks": {key: value.value for key, value in sorted(self.unlocks.items())},
            "quest_points": self.quest_points,
            "combat_level": self.combat_level,
            "members": self.members,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "missing_data_policy": "Absent observations are unknown, not negative facts.",
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.summary(), sort_keys=True).encode()).hexdigest()
