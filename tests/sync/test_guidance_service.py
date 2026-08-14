"""§21.5 and §21.6 — the cache is a cache, and the bounds are in the right order.

A real SQLite file and a hand-written stub provider with a call counter. The counter is the
point of most of these tests: every assertion about caching or throttling is ultimately an
assertion about *how many times money was spent*, and only a counter can make that claim.

No mocking library, matching the rest of this tree.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.validate import load_and_validate
from tracker.db.enums import RecommendationCandidateKind
from tracker.db.models import (
    Base,
    GuidanceNote,
    Player,
    RecommendationEntry,
    RecommendationSnapshot,
    SkillSnapshot,
)
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Confidence, Source
from tracker.guidance.prompt import GUIDANCE_SCHEMA_VERSION
from tracker.integrations.llm.types import (
    GuidanceDTO,
    GuidanceProvider,
    GuidanceStep,
    LlmUnavailable,
)
from tracker.sync.guidance import GuidanceNotFound, GuidanceService, GuidanceThrottled

NOW = datetime(2026, 8, 4, 15, 18, 41, tzinfo=UTC)

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: A real candidate from the shipped corpus, so the context assembly has trees to walk.
CANDIDATE_ID = "train_slayer_1_to_10"


class StubProvider:
    """A provider that counts, so a test can assert what a click cost.

    Satisfies :class:`~tracker.integrations.llm.types.GuidanceProvider` structurally; the
    protocol is ``runtime_checkable`` and one test asserts exactly that.
    """

    def __init__(self, *, summary: str = "Do the thing.", fails: bool = False) -> None:
        self.calls = 0
        self.closed = False
        self._summary = summary
        self._fails = fails

    @property
    def model(self) -> str:
        return "stub-model-1"

    def generate(self, prompt: Any) -> GuidanceDTO:
        self.calls += 1
        if self._fails:
            raise LlmUnavailable("stub provider is down")
        return GuidanceDTO(
            summary=self._summary,
            prerequisites=("a weapon",),
            steps=(GuidanceStep(order=1, title="Go", detail="Walk to Burthorpe."),),
            warnings=(),
            estimated_session_minutes=25,
            uncertain=(),
            model=self.model,
            generated_at=NOW,
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=80,
        )

    def close(self) -> None:
        self.closed = True


@pytest.fixture(scope="session")
def guidance_content() -> Content:
    """The shipped corpus. §21.2 walks requirement trees, so a real one earns its keep."""
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture
def guidance_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'guidance.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


@pytest.fixture
def guidance_settings() -> Callable[..., Settings]:
    def build(**llm: Any) -> Settings:
        defaults: dict[str, Any] = {
            "enabled": True,
            "min_interval_seconds": 0,
            "max_calls_per_day": 50,
            "guidance_ttl_hours": 168,
            "keep_notes_per_candidate": 3,
        }
        return Settings(
            bind_address="127.0.0.1",
            api_token="token",
            integrations={"llm": {**defaults, **llm}},
        )

    return build


@pytest.fixture
def seed(guidance_session_factory: sessionmaker[Session]) -> Callable[..., int]:
    """A player with one recommendation run naming ``CANDIDATE_ID``."""

    def build(*, slayer_level: int = 4, candidate_id: str = CANDIDATE_ID) -> int:
        with guidance_session_factory() as session:
            player = Player(username="zezima", display_name="Zezima", created_at=NOW)
            session.add(player)
            session.flush()
            session.add(
                SkillSnapshot(
                    player_id=player.id,
                    skill="slayer",
                    level=slayer_level,
                    xp=slayer_level * 100,
                    source=Source.RUNELITE,
                    observed_at=NOW,
                )
            )
            snapshot = RecommendationSnapshot(
                player_id=player.id,
                run_at=NOW,
                scoring_profile_version=1,
                roadmap_selection={},
            )
            session.add(snapshot)
            session.flush()
            session.add(
                RecommendationEntry(
                    snapshot_id=snapshot.id,
                    candidate_id=candidate_id,
                    rank=1,
                    candidate_kind=RecommendationCandidateKind.PROGRESSION,
                    score=0.5,
                    factors={"proximity": {"value": 0.9, "weight": 0.6, "log_contribution": 0.1}},
                    reason="quick to finish",
                    estimated_hours=2.0,
                    estimated_gp=0,
                    estimate_confidence=Confidence.MEDIUM,
                    bands=[
                        {
                            "from_level": 1,
                            "to_level": 10,
                            "method_id": None,
                            "hours": 2.0,
                            "gp": 0,
                            "fallback": True,
                        }
                    ],
                    blockers=[],
                    consequences={},
                )
            )
            session.commit()
            return int(player.id)

    return build


class Clock:
    """A movable clock, so a test can pass time without rebuilding the service."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock(NOW)


@pytest.fixture
def make_service(
    guidance_session_factory: sessionmaker[Session],
    guidance_content: Content,
    guidance_settings: Callable[..., Settings],
    clock: Clock,
) -> Callable[..., GuidanceService]:
    def build(provider: GuidanceProvider | None, **llm: Any) -> GuidanceService:
        return GuidanceService(
            guidance_session_factory,
            guidance_content,
            guidance_settings(**llm),
            provider=provider,
            clock=clock,
        )

    return build


class TestCaching:
    def test_the_first_ask_reaches_the_provider(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider)

        stored = service.guidance_for(player_id, CANDIDATE_ID)

        assert provider.calls == 1
        assert stored.cached is False
        assert stored.dto.summary == "Do the thing."

    def test_the_second_identical_ask_does_not(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        """The cache is the feature. Without this, a page reload is a paid call."""
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider)

        service.guidance_for(player_id, CANDIDATE_ID)
        second = service.guidance_for(player_id, CANDIDATE_ID)

        assert provider.calls == 1
        assert second.cached is True
        assert second.dto.summary == "Do the thing."

    def test_a_relevant_change_busts_the_cache(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        guidance_session_factory: sessionmaker[Session],
    ) -> None:
        """§21.5's claim: advice goes stale when the account moves, not when a clock says so."""
        player_id = seed(slayer_level=4)
        provider = StubProvider()
        service = make_service(provider)
        service.guidance_for(player_id, CANDIDATE_ID)

        with guidance_session_factory() as session:
            session.add(
                SkillSnapshot(
                    player_id=player_id,
                    skill="slayer",
                    level=9,
                    xp=900,
                    source=Source.RUNELITE,
                    observed_at=NOW + timedelta(minutes=1),
                )
            )
            session.commit()

        service.guidance_for(player_id, CANDIDATE_ID)

        assert provider.calls == 2

    def test_an_expired_note_is_regenerated(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        clock: Clock,
    ) -> None:
        """The TTL backstop, for the corpus edit the hash cannot see."""
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider, guidance_ttl_hours=1)
        service.guidance_for(player_id, CANDIDATE_ID)

        clock.value = NOW + timedelta(hours=2)
        service.guidance_for(player_id, CANDIDATE_ID)

        assert provider.calls == 2

    def test_force_bypasses_the_cache(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider)
        service.guidance_for(player_id, CANDIDATE_ID)

        stored = service.guidance_for(player_id, CANDIDATE_ID, force=True)

        assert provider.calls == 2
        assert stored.cached is False

    def test_force_does_not_bypass_the_throttle(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        """A second opinion is allowed. Forty in a minute are not."""
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider, min_interval_seconds=30)
        service.guidance_for(player_id, CANDIDATE_ID)

        with pytest.raises(GuidanceThrottled):
            service.guidance_for(player_id, CANDIDATE_ID, force=True)

        assert provider.calls == 1


class TestBoundsAndTheirOrder:
    def test_a_cache_hit_is_never_rate_limited(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        """§21.6's ordering, and the one that matters most: a reload is not a new request."""
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider, min_interval_seconds=3600)
        service.guidance_for(player_id, CANDIDATE_ID)

        second = service.guidance_for(player_id, CANDIDATE_ID)

        assert second.cached is True
        assert provider.calls == 1

    def test_the_minimum_interval_is_enforced_between_generations(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider, min_interval_seconds=30)
        service.guidance_for(player_id, CANDIDATE_ID)

        with pytest.raises(GuidanceThrottled, match="wait"):
            service.guidance_for(player_id, CANDIDATE_ID, force=True)

    def test_the_interval_expires(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        clock: Clock,
    ) -> None:
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider, min_interval_seconds=30)
        service.guidance_for(player_id, CANDIDATE_ID)

        clock.value = NOW + timedelta(seconds=31)
        service.guidance_for(player_id, CANDIDATE_ID, force=True)

        assert provider.calls == 2

    def test_the_daily_cap_is_counted_from_stored_notes(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        guidance_session_factory: sessionmaker[Session],
    ) -> None:
        """Counted from rows, not from a process counter, so a restart does not reset it."""
        player_id = seed()
        with guidance_session_factory() as session:
            for index in range(2):
                session.add(
                    GuidanceNote(
                        player_id=player_id,
                        candidate_id=f"other_task_{index}",
                        context_hash=f"{index:064d}",
                        schema_version=GUIDANCE_SCHEMA_VERSION,
                        model="stub-model-1",
                        generated_at=NOW,
                        body={},
                    )
                )
            session.commit()

        provider = StubProvider()
        service = make_service(provider, max_calls_per_day=2)

        with pytest.raises(GuidanceThrottled, match="daily"):
            service.guidance_for(player_id, CANDIDATE_ID)

        assert provider.calls == 0

    def test_a_single_flight_lock_refuses_rather_than_queues(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        """Queueing a double-click would buy the same answer twice."""
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider)

        service._lock.acquire()
        try:
            with pytest.raises(GuidanceThrottled, match="already being generated"):
                service.guidance_for(player_id, CANDIDATE_ID)
        finally:
            service._lock.release()

        assert provider.calls == 0


class TestRetention:
    def test_history_is_bounded_per_task(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        guidance_session_factory: sessionmaker[Session],
        clock: Clock,
    ) -> None:
        """§6.10's snapshot-retention shape: pruned on write, no background job."""
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider, keep_notes_per_candidate=2)

        # Four *distinct* contexts, because that is the axis history accumulates along:
        # asking the same question again replaces its answer rather than stacking a second.
        for index, level in enumerate((1, 2, 3, 4)):
            clock.value = NOW + timedelta(minutes=index)
            with guidance_session_factory() as session:
                session.add(
                    SkillSnapshot(
                        player_id=player_id,
                        skill="slayer",
                        level=level,
                        xp=level * 100,
                        source=Source.RUNELITE,
                        observed_at=NOW + timedelta(minutes=index),
                    )
                )
                session.commit()
            service.guidance_for(player_id, CANDIDATE_ID)

        with guidance_session_factory() as session:
            notes = session.query(GuidanceNote).all()

        assert provider.calls == 4
        assert len(notes) == 2

    def test_asking_the_same_question_again_replaces_its_answer(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        guidance_session_factory: sessionmaker[Session],
    ) -> None:
        """Two answers to one question are an ambiguity, not a history."""
        player_id = seed()
        service = make_service(StubProvider())
        service.guidance_for(player_id, CANDIDATE_ID)
        service.guidance_for(player_id, CANDIDATE_ID, force=True)

        with guidance_session_factory() as session:
            assert session.query(GuidanceNote).count() == 1


class TestFailures:
    def test_a_missing_run_is_not_found_rather_than_a_provider_error(
        self,
        make_service: Callable[..., GuidanceService],
        guidance_session_factory: sessionmaker[Session],
    ) -> None:
        """Nothing was asked, and the remedy is a sync rather than a retry."""
        with guidance_session_factory() as session:
            player = Player(username="zezima", display_name="Zezima", created_at=NOW)
            session.add(player)
            session.commit()
            player_id = int(player.id)

        provider = StubProvider()
        service = make_service(provider)

        with pytest.raises(GuidanceNotFound):
            service.guidance_for(player_id, CANDIDATE_ID)

        assert provider.calls == 0

    def test_a_task_outside_the_latest_run_is_not_found(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        player_id = seed()
        provider = StubProvider()
        service = make_service(provider)

        with pytest.raises(GuidanceNotFound):
            service.guidance_for(player_id, "some_other_task")

    def test_a_provider_failure_stores_nothing(
        self,
        make_service: Callable[..., GuidanceService],
        seed: Callable[..., int],
        guidance_session_factory: sessionmaker[Session],
    ) -> None:
        """A failed call must not leave a note that caches the failure for a week."""
        player_id = seed()
        service = make_service(StubProvider(fails=True))

        with pytest.raises(LlmUnavailable):
            service.guidance_for(player_id, CANDIDATE_ID)

        with guidance_session_factory() as session:
            assert session.query(GuidanceNote).count() == 0

    def test_an_unconfigured_install_reports_itself_rather_than_crashing(
        self, make_service: Callable[..., GuidanceService], seed: Callable[..., int]
    ) -> None:
        """D14 — no provider is a supported configuration, not an error state."""
        player_id = seed()
        service = make_service(None)

        assert service.enabled is False
        with pytest.raises(GuidanceThrottled, match="not configured"):
            service.guidance_for(player_id, CANDIDATE_ID)


class TestStubSatisfiesTheProtocol:
    def test_the_stub_is_a_guidance_provider(self) -> None:
        """If this drifts, every test above is exercising a shape nothing else has."""
        assert isinstance(StubProvider(), GuidanceProvider)
