"""Wise Old Man client — skills, total level, boss KC and LMS score (§7.2).

WOM already polls the official hiscores, stores history and exposes gains, covering
both the "official hiscores" and "XP history" roles from the original design with one
integration, one parser and one rate-limit budget (§7.2). Direct hiscores access
remains a documented contingency only — see ``tracker/integrations/hiscores/README.md``
— and is not built here.

Response shape verified against the live ``GET /players/{username}`` endpoint at
implementation time (2026-08-04). The relevant subset::

    {
        "latestSnapshot": {
            "createdAt": "2026-08-04T06:12:03.602Z",
            "data": {
                "skills": {
                    "overall": {"metric": "overall", "experience": ..., "rank": ..., "level": ...},
                    "magic": {
                        "metric": "magic",
                        "experience": 13034431,
                        "rank": 45213,
                        "level": 94,
                    },
                },
                "activities": {
                    "last_man_standing": {
                        "metric": "last_man_standing",
                        "score": 1204,
                        "rank": 8213,
                    }
                },
            },
        }
    }

Skill ``experience`` and ``rank``, and activity ``score`` and ``rank``, all use the
hiscores convention of ``-1`` for "unranked" (§6.2, §7.3) — this client is the adapter
boundary §6.2 requires: **-1 normalizes to `None` here, never `0` (G5).**
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from tracker.config.settings import WiseOldManSettings
from tracker.domain.types import Source
from tracker.integrations.http import CircuitBreaker, build_client, get_with_retry

#: The `overall` entry is total level/xp, not a trainable skill (§6.2 has no row for it).
_NON_SKILL_METRICS = frozenset({"overall"})

_UNRANKED_SENTINEL = -1


@dataclass(frozen=True, slots=True)
class SkillDTO:
    """§6.2's ``SkillSnapshot`` columns this client is responsible for.

    ``xp`` is nullable and ``None`` means unranked — never ``0`` (G5). ``level`` has no
    nullable counterpart in §6.2, and WOM computes it from experience rather than
    reporting a hiscores-style rank, so it is never a ``-1`` sentinel in practice.
    """

    skill: str
    level: int
    xp: int | None
    source: Source
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PlayerSnapshotDTO:
    """One WOM player fetch, decomposed into what the rest of the app needs.

    ``lms_score`` is G5-normalized the same way ``SkillDTO.xp`` is. It is kept
    alongside the skill list rather than folded into it because LMS is an
    ``activities`` entry in the WOM payload, not a ``skills`` entry — conflating the
    two would misrepresent the source data.
    """

    username: str
    observed_at: datetime
    skills: tuple[SkillDTO, ...]
    lms_score: int | None


class WiseOldManClient:
    """Player fetch for one WOM username (§7.2). Returns a DTO; persists nothing."""

    def __init__(
        self,
        settings: WiseOldManSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client = build_client(
            base_url=settings.base_url, user_agent=settings.user_agent, transport=transport
        )
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._clock = clock
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WiseOldManClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def player(self, username: str) -> PlayerSnapshotDTO:
        """Fetch the player's latest snapshot. Outbound request carries only the
        username (§11.6) — no practice or account data is ever sent WOM's way."""
        response = get_with_retry(
            self._client,
            f"/players/{quote(username, safe='')}",
            breaker=self._breaker,
            sleep=self._sleep,
        )
        payload: dict[str, Any] = response.json()
        snapshot = payload.get("latestSnapshot") or {}
        data = snapshot.get("data") or {}
        observed_at = _parse_timestamp(snapshot.get("createdAt")) or self._clock()

        skills = tuple(
            _parse_skill(metric, entry, observed_at)
            for metric, entry in (data.get("skills") or {}).items()
            if metric not in _NON_SKILL_METRICS and isinstance(entry, dict)
        )

        lms_entry = (data.get("activities") or {}).get("last_man_standing") or {}
        lms_score = _normalize_unranked(lms_entry.get("score"))

        return PlayerSnapshotDTO(
            username=username, observed_at=observed_at, skills=skills, lms_score=lms_score
        )


def _parse_skill(metric: str, entry: dict[str, Any], observed_at: datetime) -> SkillDTO:
    level = entry.get("level")
    return SkillDTO(
        skill=metric,
        level=level if isinstance(level, int) and level > 0 else 1,
        xp=_normalize_unranked(entry.get("experience")),
        source=Source.WISE_OLD_MAN,
        observed_at=observed_at,
    )


def _normalize_unranked(value: object) -> int | None:
    """G5: hiscores/WOM ``-1`` (unranked) normalizes to ``None``, never ``0``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value == _UNRANKED_SENTINEL:
        return None
    return value


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
