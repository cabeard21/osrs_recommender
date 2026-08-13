"""§8.2's bands survive the round trip, and the method survives with them (Step 8).

``BandEstimate.method_id`` has always been computed by §8.2 step 3 and always been thrown
away at persistence, so §15's "How" line had nothing to render. These tests cover the
column that closes that, and the two ways it can go wrong afterwards:

* the method is *lost* — the number reaches the page with no account of where it came from;
* the method is *re-derived* — the page names a method the quoted hours did not come from,
  because §8.2 selects among what the account satisfied at run time and that changes.

The second is the subtler failure and is the reason ``_band_rows`` reads the stored id.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.content.validate import load_and_validate
from tracker.db.models import RecommendationEntry
from tracker.db.persist_engine_output import persist_recommendation_run
from tracker.domain.types import (
    BandEstimate,
    CandidateKind,
    Confidence,
    Estimate,
    Recommendation,
    RoadmapSelection,
)
from tracker.ui.read_model import _band_rows
from tracker.ui.view_model import FALLBACK_METHOD_LABEL

NOW = datetime(2026, 8, 4, tzinfo=UTC)


@pytest.fixture(scope="module")
def corpus() -> Content:
    return load_and_validate()


def _recommendation(*bands: BandEstimate, candidate_id: str = "train_magic") -> Recommendation:
    return Recommendation(
        candidate_id=candidate_id,
        name="Train Magic",
        kind=CandidateKind.SKILL_TRAINING,
        score=0.5,
        factors={},
        reason="because",
        estimate=Estimate(
            hours=sum(band.hours for band in bands),
            gp=sum(band.gp for band in bands),
            confidence=Confidence.HIGH,
            bands=bands,
        ),
    )


def _persist(session: Session, player_id: int, recommendation: Recommendation) -> list[dict]:
    persist_recommendation_run(
        session,
        player_id,
        [recommendation],
        selection=RoadmapSelection(weights={"main_nh": 1.0}),
        scoring_profile_version=2,
        run_at=NOW,
    )
    entry = session.scalars(
        RecommendationEntry.__table__.select().with_only_columns(RecommendationEntry.bands)
    ).all()
    return list(entry)


def test_the_selected_method_survives_the_round_trip(session: Session, new_player) -> None:
    """The whole point of the column: ``method_id`` used to be discarded here."""
    player_id = new_player(session)
    band = BandEstimate(
        from_level=87, to_level=94, method_id="magic_bursting", hours=16.0, gp=6_400_000
    )

    stored = _persist(session, player_id, _recommendation(band))

    assert stored == [
        [
            {
                "from_level": 87,
                "to_level": 94,
                "method_id": "magic_bursting",
                "hours": 16.0,
                "gp": 6_400_000,
                "fallback": False,
            }
        ]
    ]


def test_every_band_is_kept_not_just_the_first(session: Session, new_player) -> None:
    """Why this is one JSON column and not five scalars.

    A 70→99 span crosses method boundaries and produces several bands; a scalar column
    would have had to pick one, and "the first" would quietly become "the slowest".
    """
    player_id = new_player(session)
    bands = (
        BandEstimate(from_level=70, to_level=82, method_id="magic_conservative", hours=40.0, gp=1),
        BandEstimate(from_level=82, to_level=99, method_id="magic_bursting", hours=30.0, gp=2),
    )

    stored = _persist(session, player_id, _recommendation(*bands))

    assert [band["from_level"] for band in stored[0]] == [70, 82]
    assert [band["method_id"] for band in stored[0]] == ["magic_conservative", "magic_bursting"]


def test_an_entry_with_no_estimate_stores_an_empty_list_not_null(
    session: Session, new_player
) -> None:
    """An entry with no bands has *no* bands — that is not the same as "unknown"."""
    player_id = new_player(session)
    recommendation = Recommendation(
        candidate_id="complete_quest",
        name="A quest",
        kind=CandidateKind.QUEST,
        score=0.1,
        factors={},
        reason="because",
        estimate=None,
    )

    stored = _persist(session, player_id, recommendation)

    assert stored == [[]]


# ---------------------------------------------------------------------------
# Reading them back (tracker.ui.read_model._band_rows)
# ---------------------------------------------------------------------------


def test_the_method_name_and_description_are_joined_from_content(corpus: Content) -> None:
    """The stored id is the key; content supplies the prose §15 shows."""
    stored = [
        {
            "from_level": 87,
            "to_level": 94,
            "method_id": "magic_bursting",
            "hours": 16.0,
            "gp": 1,
            "fallback": False,
        }
    ]

    (row,) = _band_rows(stored, corpus)

    assert row.method_name == "Magic bursting"
    assert row.method_label == "Magic bursting"
    assert row.level_label == "87→94"
    assert row.location and row.target
    assert row.gear and row.inventory


def test_a_method_content_no_longer_declares_degrades_to_its_id(corpus: Content) -> None:
    """Content changes between runs; a History page must not become a stack trace.

    The raw id is still the most truthful thing available about what the number was
    computed from, which is why it degrades to that rather than to "unknown" or to blank.
    """
    stored = [
        {
            "from_level": 1,
            "to_level": 50,
            "method_id": "magic_deleted_method",
            "hours": 2.0,
            "gp": 0,
            "fallback": False,
        }
    ]

    (row,) = _band_rows(stored, corpus)

    assert row.method_name == "magic_deleted_method"
    assert row.method_label == "magic_deleted_method"
    assert row.location is None


def test_a_fallback_band_says_so_rather_than_rendering_blank(corpus: Content) -> None:
    """§8.4 requires the conservative default to be qualified, not merely omitted.

    A blank cell reads as "no information"; the truth is "a number we invented", and those
    are different claims.
    """
    stored = [
        {
            "from_level": 26,
            "to_level": 53,
            "method_id": None,
            "hours": 8.5,
            "gp": 0,
            "fallback": True,
        }
    ]

    (row,) = _band_rows(stored, corpus)

    assert row.method_label == FALLBACK_METHOD_LABEL
    assert "upper bound" in row.method_label


def test_no_bands_reads_back_as_no_bands(corpus: Content) -> None:
    assert _band_rows([], corpus) == ()
    assert _band_rows(None, corpus) == ()


# ---------------------------------------------------------------------------
# Blockers (§15) — same persistence rule as bands
# ---------------------------------------------------------------------------


def test_a_blocked_entrys_blockers_survive_the_round_trip(session: Session, new_player) -> None:
    """Persisted rather than re-derived, for the reason ``bands`` is.

    A gate's unsatisfied leaves are a function of the account's facts *at run time*, and a
    snapshot accumulates (§6.10) — re-evaluating on read would relabel a historical entry
    with today's facts.
    """
    from tracker.domain.types import LeafRef

    player_id = new_player(session)
    recommendation = Recommendation(
        candidate_id="complete_lunar_diplomacy",
        name="Complete Lunar Diplomacy",
        kind=CandidateKind.QUEST,
        score=0.0,
        blocked=True,
        blockers=(
            LeafRef("skill", "crafting", "Crafting 61", 61),
            LeafRef("quest", "lost_city", "Lost City", None),
        ),
    )

    persist_recommendation_run(
        session,
        player_id,
        [],
        selection=RoadmapSelection(weights={"main_nh": 1.0}),
        scoring_profile_version=2,
        run_at=NOW,
        blocked=[recommendation],
    )
    stored = session.scalars(
        RecommendationEntry.__table__.select().with_only_columns(RecommendationEntry.blockers)
    ).all()

    assert stored == [
        [
            {"leaf_type": "skill", "key": "crafting", "description": "Crafting 61", "target": 61},
            {"leaf_type": "quest", "key": "lost_city", "description": "Lost City", "target": None},
        ]
    ]


def test_an_actionable_entry_stores_no_blockers(session: Session, new_player) -> None:
    """Only a blocked entry has any — an empty list is the honest value, not ``NULL``."""
    player_id = new_player(session)
    band = BandEstimate(from_level=87, to_level=94, method_id="magic_bursting", hours=1.0, gp=0)

    _persist(session, player_id, _recommendation(band))

    rows = session.scalars(
        RecommendationEntry.__table__.select().with_only_columns(RecommendationEntry.blockers)
    ).all()

    assert rows == [[]]
