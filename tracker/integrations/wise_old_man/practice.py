"""The WOM LMS-score practice proxy (§7.6, D6) — G6's home.

§7.6's evidence-asymmetry rule, verbatim:

    WOM evidence is positive-only. An LMS score increase proves recent activity; a
    *lack* of movement proves nothing.

    * Positive WOM evidence may refresh practice.
    * Absent WOM evidence must never accelerate staleness.
    * RuneLite session evidence takes precedence when available.

This module is a pure comparison: it takes two already-fetched, already
G5-normalized LMS scores and decides whether that pair constitutes positive evidence.
It does not fetch anything and does not know what the *previous* score was — that is
state Step 9's pipeline owns (most recently persisted score), which is what keeps this
module decoupled from the database, same as every other client in this package.

Per §7.6's accepted-signals table, a WOM LMS score increase refreshes two practice
domains at once — ``lms`` and ``general_pvp`` — each as its own event, because
:class:`PracticeEventDTO.domain` is single-valued (§6.7) and the freshness service
matches one event to one milestone's ``practiced_by`` list at a time.

**G6, stated as code:** no branch of :func:`derive_lms_practice_events` may return a
non-empty tuple unless ``current_score`` is a real (non-``None``) value strictly
greater than a real (non-``None``) ``previous_score``. A decrease, a plateau, or either
score being unranked (``None``, per G5) all fall out of the same one guard clause below
— there is no second code path that could accelerate freshness by a different route.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tracker.domain.types import Confidence, PracticeDomain, Source

#: §7.6's accepted-signals table: "WOM LMS score increases -> lms, general_pvp -> medium".
_LMS_SCORE_INCREASE_DOMAINS: tuple[PracticeDomain, ...] = (
    PracticeDomain.LMS,
    PracticeDomain.GENERAL_PVP,
)

_LMS_SCORE_INCREASED_EVIDENCE = "lms_score_increased"


@dataclass(frozen=True, slots=True)
class PracticeEventDTO:
    """§6.7's ``PracticeEvent`` columns. No ``id``/``player_id`` — Step 9 assigns both
    when it persists this; the DTO does not know which player it is for.

    ``metadata`` is summarized only, per §7.6's collection boundary — a delta, not a
    replay of the underlying activity.
    """

    domain: PracticeDomain
    started_at: datetime
    ended_at: datetime
    source: Source
    confidence: Confidence
    evidence_type: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


def derive_lms_practice_events(
    *,
    previous_score: int | None,
    current_score: int | None,
    period_start: datetime,
    period_end: datetime,
) -> tuple[PracticeEventDTO, ...]:
    """Emit medium-confidence practice events for a genuine LMS score increase.

    Returns an empty tuple for a decrease, a plateau, or either score being unranked
    (``None``) — G6's "absent evidence must never accelerate staleness" applies as much
    to "we don't know" as it does to "no change occurred." Emits exactly one event per
    domain in ``_LMS_SCORE_INCREASE_DOMAINS`` when — and only when — the score
    strictly increased.
    """
    if previous_score is None or current_score is None or current_score <= previous_score:
        return ()

    delta = current_score - previous_score
    return tuple(
        PracticeEventDTO(
            domain=domain,
            started_at=period_start,
            ended_at=period_end,
            source=Source.WISE_OLD_MAN,
            confidence=Confidence.MEDIUM,
            evidence_type=_LMS_SCORE_INCREASED_EVIDENCE,
            metadata={"lms_score_delta": delta},
        )
        for domain in _LMS_SCORE_INCREASE_DOMAINS
    )
