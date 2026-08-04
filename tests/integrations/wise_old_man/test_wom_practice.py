"""The WOM LMS practice proxy (§7.6, D6) — G6's home.

"WOM evidence is positive-only. An LMS score increase proves recent activity; a
*lack* of movement proves nothing." — §7.6
"""

from __future__ import annotations

from datetime import UTC, datetime

from tracker.domain.types import Confidence, PracticeDomain, Source
from tracker.integrations.wise_old_man.practice import derive_lms_practice_events

_START = datetime(2026, 8, 1, tzinfo=UTC)
_END = datetime(2026, 8, 4, tzinfo=UTC)


class TestG6AbsentEvidenceNeverAcceleratesStaleness:
    """G6: absent WOM evidence must never accelerate a milestone's freshness.

    Every case here is "no positive signal was present" in one shape or another, and
    every one of them must return no events. There is exactly one branch in
    `derive_lms_practice_events` that can produce events — this class tries every way
    of *not* taking it.
    """

    def test_a_score_decrease_emits_nothing(self) -> None:
        events = derive_lms_practice_events(
            previous_score=1500, current_score=1400, period_start=_START, period_end=_END
        )
        assert events == ()

    def test_a_plateau_emits_nothing(self) -> None:
        events = derive_lms_practice_events(
            previous_score=1500, current_score=1500, period_start=_START, period_end=_END
        )
        assert events == ()

    def test_both_scores_unranked_emits_nothing(self) -> None:
        events = derive_lms_practice_events(
            previous_score=None, current_score=None, period_start=_START, period_end=_END
        )
        assert events == ()

    def test_current_score_unranked_emits_nothing_even_if_previous_was_ranked(self) -> None:
        """A player dropping off the leaderboard is not evidence of a decrease in
        skill, but it is also not positive evidence of anything — G6 says absence
        must never move freshness, in either direction."""
        events = derive_lms_practice_events(
            previous_score=1500, current_score=None, period_start=_START, period_end=_END
        )
        assert events == ()

    def test_previous_score_unranked_emits_nothing(self) -> None:
        """A newly-ranked score is plausibly real activity, but §7.6 only ever
        describes comparing two known scores as the positive signal — this proxy
        declines to invent a stronger reading of "previously unranked" than the SDD
        states, keeping the one true branch the only source of events."""
        events = derive_lms_practice_events(
            previous_score=None, current_score=1500, period_start=_START, period_end=_END
        )
        assert events == ()


class TestPositiveEvidence:
    def test_a_genuine_increase_emits_medium_confidence_events_for_lms_and_general_pvp(
        self,
    ) -> None:
        events = derive_lms_practice_events(
            previous_score=1400, current_score=1500, period_start=_START, period_end=_END
        )

        assert {event.domain for event in events} == {
            PracticeDomain.LMS,
            PracticeDomain.GENERAL_PVP,
        }
        for event in events:
            assert event.confidence is Confidence.MEDIUM
            assert event.source is Source.WISE_OLD_MAN
            assert event.evidence_type == "lms_score_increased"
            assert event.started_at == _START
            assert event.ended_at == _END
            assert event.metadata == {"lms_score_delta": 100}

    def test_metadata_carries_only_a_summarized_delta(self) -> None:
        """§7.6's collection boundary: summarized evidence only, never raw telemetry."""
        events = derive_lms_practice_events(
            previous_score=1000, current_score=1050, period_start=_START, period_end=_END
        )
        for event in events:
            assert set(event.metadata) == {"lms_score_delta"}
