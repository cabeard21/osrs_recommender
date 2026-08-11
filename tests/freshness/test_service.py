"""§6.7 / §7.6 attribution, plus the two invariants this step owns: **G1** and **G7**."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.content.schema import KappaPresets, Milestone, ScoringProfile, ScoringWeights
from tracker.db.enums import PracticeEventConfidence
from tracker.db.models import Base, Player, PracticeEvent
from tracker.db.models import Milestone as MilestoneRow
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import (
    Freshness,
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    PracticeDomain,
    Source,
)
from tracker.freshness import service
from tracker.freshness.service import apply_practice_events, materialize_freshness

NOW = datetime(2026, 8, 4, 15, 18, 41, tzinfo=UTC)

_PROFILE = ScoringProfile(
    version=1,
    kappa_gp=KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
    weights=ScoringWeights(
        pvp_value=1.0,
        leverage=0.8,
        proximity=0.6,
        effort_decay=0.7,
        cost_decay=0.5,
        method_unlock=0.0,
    ),
)


def _content(*milestones: Milestone) -> Content:
    return Content(profile=_PROFILE, milestones={m.id: m for m in milestones})


def _execution(milestone_id: str, *domains: PracticeDomain) -> Milestone:
    return Milestone.model_validate(
        {
            "id": milestone_id,
            "name": milestone_id.replace("_", " ").title(),
            "class": "execution",
            "kind": "self_attested",
            "practiced_by": [domain.value for domain in domains],
        }
    )


def _knowledge(milestone_id: str) -> Milestone:
    return Milestone.model_validate(
        {
            "id": milestone_id,
            "name": milestone_id.replace("_", " ").title(),
            "class": "knowledge",
            "kind": "self_attested",
        }
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'freshness.db'}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def player_id(session: Session) -> int:
    player = Player(
        username="zezima",
        display_name="Zezima",
        created_at=NOW - timedelta(days=365),
        gp_sensitivity=GpSensitivity.NORMAL,
    )
    session.add(player)
    session.flush()
    return player.id


@pytest.fixture
def add_event(session: Session, player_id: int) -> Callable[..., PracticeEvent]:
    def _add(
        domain: PracticeDomain,
        ended_at: datetime,
        *,
        evidence_type: str = "lms_match_completed",
    ) -> PracticeEvent:
        event = PracticeEvent(
            player_id=player_id,
            domain=domain,
            started_at=ended_at - timedelta(minutes=7),
            ended_at=ended_at,
            source=Source.RUNELITE,
            confidence=PracticeEventConfidence.HIGH,
            evidence_type=evidence_type,
        )
        session.add(event)
        session.flush()
        return event

    return _add


@pytest.fixture
def add_milestone(session: Session, player_id: int) -> Callable[..., MilestoneRow]:
    def _add(
        key: str,
        *,
        class_: MilestoneClass = MilestoneClass.EXECUTION,
        achieved: bool = True,
        attested_at: datetime | None = NOW - timedelta(days=200),
        last_practiced_at: datetime | None = None,
    ) -> MilestoneRow:
        row = MilestoneRow(
            player_id=player_id,
            key=key,
            kind=MilestoneKind.SELF_ATTESTED,
            class_=class_,
            achieved=achieved,
            attested_at=attested_at,
            last_practiced_at=last_practiced_at,
            source=Source.MANUAL,
            observed_at=NOW - timedelta(days=200),
        )
        session.add(row)
        session.flush()
        return row

    return _add


# ---------------------------------------------------------------------------
# G7 — a proxy refreshes practice and claims nothing about competence
# ---------------------------------------------------------------------------


def test_g7_an_event_refreshes_practice_and_leaves_achieved_untouched(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """**G7.** §7.6's third and fourth conditions, on the ordinary path.

    ``achieved`` describes a skill the player established; ``last_practiced_at`` describes
    a domain they recently exercised. Playing an LMS match is evidence of the second and
    says nothing about the first — in either direction.
    """
    row = add_milestone("comfortable_4_way_switches", achieved=True)
    add_event(PracticeDomain.LMS, NOW)

    outcome = apply_practice_events(
        session, player_id, _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))
    )

    assert row.last_practiced_at == NOW
    assert row.achieved is True
    assert outcome.milestones_refreshed == 1


def test_g7_practice_on_an_unachieved_milestone_does_not_achieve_it(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """§7.6's fourth condition: *the proxy does not claim competence from mere
    participation*. Entering an LMS match is participation. It is not a 4-way switch.
    """
    row = add_milestone("comfortable_4_way_switches", achieved=False)
    add_event(PracticeDomain.LMS, NOW)

    apply_practice_events(
        session, player_id, _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))
    )

    assert row.achieved is False
    assert row.last_practiced_at == NOW


def test_g7_a_row_created_from_practice_evidence_stays_never_prompted(
    session: Session, player_id: int, add_event: Callable[..., PracticeEvent]
) -> None:
    """A7 meeting G7 — the subtle half.

    Practice evidence about a milestone the player has never been asked about still needs
    somewhere to live, so a row is created. It must carry ``attested_at = NULL``, or the
    act of recording an LMS match would silently answer a question nobody asked: the leaf
    would flip from **unknown** ("never prompted") to **unsatisfied** ("asked, said no").
    """
    add_event(PracticeDomain.LMS, NOW)

    outcome = apply_practice_events(
        session, player_id, _content(_execution("vengeance_timing", PracticeDomain.LMS))
    )

    row = session.get(MilestoneRow, (player_id, "vengeance_timing"))
    assert row is not None
    assert row.achieved is False
    assert row.attested_at is None
    assert row.last_practiced_at == NOW
    assert outcome.rows_created == 1


def test_g7_the_module_contains_no_assignment_to_achieved() -> None:
    """**G7**, structurally. The tests above prove the behaviour on the paths they walk;
    this one proves the property on every path, including ones not yet written.

    §7.6's conditions 3 and 4 are guarantees about what the freshness service *never does*,
    and an absence is best tested as an absence — the same reasoning as Step 4's AST
    import-boundary test.
    """
    tree = ast.parse(Path(inspect.getfile(service)).read_text(encoding="utf-8"))

    targets: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets.append(node.target)

    assert [
        target.attr
        for target in targets
        if isinstance(target, ast.Attribute) and target.attr == "achieved"
    ] == []


# ---------------------------------------------------------------------------
# G1 — achieved never transitions true -> false from the passage of time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("years", [1, 10, 1_000])
def test_g1_achieved_survives_an_arbitrary_amount_of_elapsed_time(
    session: Session,
    player_id: int,
    add_milestone: Callable[..., MilestoneRow],
    years: int,
) -> None:
    """**G1**, and this step owns it — §16.2's *"``achieved`` never transitions true →
    false from the passage of time alone"*.

    The recommendation engine is pure over ``PlayerState`` and cannot mutate a milestone;
    the merge layer never touches ``Milestone`` rows. This module is the only place where
    elapsed time and milestone rows meet, so it is the only place the invariant could
    break. A thousand years of decay produces ``very_stale`` — an input to
    ``readiness_confidence`` — and nothing else (D8).
    """
    row = add_milestone(
        "consistent_overhead_prayers", achieved=True, last_practiced_at=NOW - timedelta(days=5)
    )
    far_future = NOW + timedelta(days=365 * years)

    apply_practice_events(
        session,
        player_id,
        _content(_execution("consistent_overhead_prayers", PracticeDomain.NH_COMBAT)),
    )
    materialize_freshness(session, player_id, far_future)

    assert row.achieved is True
    assert row.freshness is Freshness.VERY_STALE


def test_g1_holds_for_a_milestone_that_was_never_practiced(
    session: Session, player_id: int, add_milestone: Callable[..., MilestoneRow]
) -> None:
    """G1 with G6's asymmetry. No practice evidence has ever been attributed, so
    ``last_practiced_at`` is ``NULL``. Absent evidence must not accelerate staleness, so
    the band stays ``None`` — and ``achieved`` stays true regardless.
    """
    row = add_milestone("consistent_overhead_prayers", achieved=True, last_practiced_at=None)

    materialize_freshness(session, player_id, NOW + timedelta(days=4_000))

    assert row.achieved is True
    assert row.freshness is None


# ---------------------------------------------------------------------------
# §7.6 attribution — practiced_by is the whole gate
# ---------------------------------------------------------------------------


def test_an_event_in_an_undeclared_domain_refreshes_nothing(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """§7.6's second condition: *the milestone explicitly declares that signal via
    ``practiced_by``*. Wilderness combat is real practice of something — just not of this.
    """
    row = add_milestone("comfortable_4_way_switches")
    add_event(PracticeDomain.WILDERNESS_PVP, NOW, evidence_type="wilderness_player_combat")

    outcome = apply_practice_events(
        session, player_id, _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))
    )

    assert row.last_practiced_at is None
    assert outcome.milestones_refreshed == 0
    assert outcome.events_unattributed == 1


def test_one_event_refreshes_every_milestone_declaring_its_domain(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """§7.6's signal table maps one signal onto several domains and several milestones —
    an LMS match is practice of switching *and* of prayer. The fan-out lives here rather
    than in the plugin, so the plugin never has to know what content declares.
    """
    switches = add_milestone("comfortable_4_way_switches")
    prayers = add_milestone("consistent_overhead_prayers")
    add_event(PracticeDomain.LMS, NOW)

    apply_practice_events(
        session,
        player_id,
        _content(
            _execution("comfortable_4_way_switches", PracticeDomain.LMS),
            _execution("consistent_overhead_prayers", PracticeDomain.LMS),
        ),
    )

    assert switches.last_practiced_at == NOW
    assert prayers.last_practiced_at == NOW


def test_a_knowledge_milestone_is_never_given_a_practice_timestamp(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """§6.6 — only ``class: execution`` ages. Understanding, once acquired, does not decay
    on a 30-day clock, and a knowledge milestone holding a practice timestamp would
    acquire a freshness band it is never allowed to have.
    """
    row = add_milestone("teleblock_understanding", class_=MilestoneClass.KNOWLEDGE)
    add_event(PracticeDomain.LMS, NOW)

    apply_practice_events(session, player_id, _content(_knowledge("teleblock_understanding")))
    materialize_freshness(session, player_id, NOW)

    assert row.last_practiced_at is None
    assert row.freshness is None


def test_the_latest_event_wins(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    row = add_milestone("comfortable_4_way_switches")
    add_event(PracticeDomain.LMS, NOW - timedelta(days=40))
    add_event(PracticeDomain.LMS, NOW)
    add_event(PracticeDomain.LMS, NOW - timedelta(days=2))

    apply_practice_events(
        session, player_id, _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))
    )

    assert row.last_practiced_at == NOW


def test_g6_last_practiced_at_never_moves_backwards(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """**G6**'s shape one layer in. A late-arriving older event is not evidence of decay —
    treating it as one would let a backfill make a freshly-practiced milestone look stale.
    """
    row = add_milestone("comfortable_4_way_switches", last_practiced_at=NOW)
    add_event(PracticeDomain.LMS, NOW - timedelta(days=60))

    outcome = apply_practice_events(
        session, player_id, _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))
    )

    assert row.last_practiced_at == NOW
    assert outcome.milestones_refreshed == 0


def test_the_pass_is_idempotent(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    """Re-running over the whole log must reach the same state — that is what makes
    ``since`` an optimization rather than a correctness requirement.
    """
    row = add_milestone("comfortable_4_way_switches")
    add_event(PracticeDomain.LMS, NOW)
    content = _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))

    apply_practice_events(session, player_id, content)
    second = apply_practice_events(session, player_id, content)

    assert row.last_practiced_at == NOW
    assert second.milestones_refreshed == 0


def test_since_bounds_the_scan(
    session: Session,
    player_id: int,
    add_event: Callable[..., PracticeEvent],
    add_milestone: Callable[..., MilestoneRow],
) -> None:
    row = add_milestone("comfortable_4_way_switches")
    add_event(PracticeDomain.LMS, NOW - timedelta(days=90))

    outcome = apply_practice_events(
        session,
        player_id,
        _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS)),
        since=NOW - timedelta(days=7),
    )

    assert outcome.events_considered == 0
    assert row.last_practiced_at is None


def test_practice_events_belonging_to_another_player_are_not_attributed(
    session: Session, player_id: int, add_milestone: Callable[..., MilestoneRow]
) -> None:
    """§6.1 supports multiple characters even though the UI exposes one, so a query missing
    its ``player_id`` predicate would stay invisible until someone added a second account
    and started refreshing milestones from the wrong one's matches.
    """
    other = Player(
        username="other", display_name="Other", created_at=NOW, gp_sensitivity=GpSensitivity.NORMAL
    )
    session.add(other)
    session.flush()
    session.add(
        PracticeEvent(
            player_id=other.id,
            domain=PracticeDomain.LMS,
            started_at=NOW - timedelta(minutes=7),
            ended_at=NOW,
            source=Source.RUNELITE,
            confidence=PracticeEventConfidence.HIGH,
            evidence_type="lms_match_completed",
        )
    )
    row = add_milestone("comfortable_4_way_switches")

    outcome = apply_practice_events(
        session, player_id, _content(_execution("comfortable_4_way_switches", PracticeDomain.LMS))
    )

    assert row.last_practiced_at is None
    assert outcome.events_considered == 0


# ---------------------------------------------------------------------------
# A18 — the materialized column
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days_ago", "expected"),
    [
        (1, Freshness.CURRENT),
        (29, Freshness.CURRENT),
        (30, Freshness.STALE),
        (90, Freshness.STALE),
        (91, Freshness.VERY_STALE),
    ],
)
def test_materialize_freshness_writes_the_policy_bands(
    session: Session,
    player_id: int,
    add_milestone: Callable[..., MilestoneRow],
    days_ago: int,
    expected: Freshness,
) -> None:
    """A18 gave the column a writer. The bands come from the one policy function, so the
    stored value cannot drift from what the engine computes.
    """
    row = add_milestone(
        "comfortable_4_way_switches", last_practiced_at=NOW - timedelta(days=days_ago)
    )

    materialize_freshness(session, player_id, NOW)

    assert row.freshness is expected


def test_materialize_freshness_is_a_pure_rebuild(
    session: Session, player_id: int, add_milestone: Callable[..., MilestoneRow]
) -> None:
    """§6.6 calls the column *"materialized for query convenience"*. A wrong stored value
    must therefore be repaired by a rebuild, not preserved — which is the property that
    makes it safe for nothing in the engine to read it.
    """
    row = add_milestone("comfortable_4_way_switches", last_practiced_at=NOW - timedelta(days=1))
    row.freshness = Freshness.VERY_STALE
    session.flush()

    written = materialize_freshness(session, player_id, NOW)

    assert row.freshness is Freshness.CURRENT
    assert written == 1
