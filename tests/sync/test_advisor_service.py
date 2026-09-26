"""§22.7's orchestration: the bounds, the two sessions, and the digest comparison.

Driven with a double rather than a transport, because what is under test here is *policy* —
which check runs in which order, what gets written and when — and a scripted HTTP layer would
add a second thing that could fail without adding a second thing worth asserting.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tracker.advisor.prompt import AdvisorPrompt
from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.validate import load_and_validate
from tracker.db import advisor as advisor_repo
from tracker.db.enums import RecommendationCandidateKind
from tracker.db.models import Base, Player, RecommendationEntry, RecommendationSnapshot
from tracker.db.models import Milestone as MilestoneRow
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Confidence, MilestoneClass, MilestoneKind, Source
from tracker.integrations.llm.types import (
    AdvisorTurn,
    LlmUnavailable,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolTraceEntry,
)
from tracker.sync.advisor import AdvisorNotFound, AdvisorService, AdvisorThrottled

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"


class _Double:
    """Records what it was asked and answers from a script."""

    def __init__(self, answers: list[Any] | None = None) -> None:
        self._answers = answers or []
        self.prompts: list[AdvisorPrompt] = []
        self.calls = 0

    @property
    def model(self) -> str:
        return "double-1"

    def converse(
        self,
        prompt: AdvisorPrompt,
        tools: Sequence[ToolSpec],
        execute: Callable[[ToolCall], ToolResult],
        *,
        max_iterations: int,
        max_tool_calls: int,
    ) -> AdvisorTurn:
        self.prompts.append(prompt)
        self.calls += 1
        answer = self._answers.pop(0) if self._answers else None
        if isinstance(answer, Exception):
            raise answer
        return answer or AdvisorTurn(
            answer=f"answer {self.calls}", model=self.model, generated_at=NOW
        )

    def close(self) -> None:
        return None


@pytest.fixture(scope="session")
def corpus() -> Content:
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'advisor.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def player_id(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        player = Player(username="zezima", display_name="Zezima", created_at=NOW, last_sync_at=NOW)
        session.add(player)
        session.commit()
        return player.id


def _service(
    factory: sessionmaker[Session],
    corpus: Content,
    *,
    provider: Any = None,
    clock: Callable[[], datetime] | None = None,
    **advisor: Any,
) -> AdvisorService:
    settings = Settings(
        bind_address="127.0.0.1",
        api_token="token",
        integrations={"llm": {"enabled": True, "advisor": {"enabled": True, **advisor}}},
    )
    return AdvisorService(
        factory,
        corpus,
        settings,
        provider=provider if provider is not None else _Double(),
        clock=clock or (lambda: NOW),
    )


class TestDisabled:
    def test_no_provider_means_not_enabled_and_a_refusal(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        """D14 — an unconfigured install is a supported state, not an error state."""
        settings = Settings(bind_address="127.0.0.1", api_token="token")
        service = AdvisorService(factory, corpus, settings, provider=None)
        assert service.enabled is False
        with pytest.raises(AdvisorThrottled, match="not configured"):
            service.ask(player_id, "anything")


class TestAsking:
    def test_a_first_question_starts_a_conversation(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        reply = _service(factory, corpus).ask(player_id, "what should I do next?")
        with factory() as session:
            conversation = advisor_repo.get_conversation(session, player_id, reply.conversation_id)
            assert conversation is not None
            assert conversation.title == "what should I do next?"
            assert [m.content for m in advisor_repo.thread(session, conversation.id)] == [
                "what should I do next?",
                "answer 1",
            ]

    def test_history_is_replayed_into_the_next_prompt(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        double = _Double()
        service = _service(factory, corpus, provider=double, min_interval_seconds=0)
        first = service.ask(player_id, "one")
        service.ask(player_id, "two", conversation_id=first.conversation_id)
        assert [turn.text for turn in double.prompts[1].history] == ["one", "answer 1"]

    def test_an_empty_question_is_rejected_without_paying(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        double = _Double()
        with pytest.raises(AdvisorNotFound):
            _service(factory, corpus, provider=double).ask(player_id, "   ")
        assert double.calls == 0


class TestBounds:
    def test_a_provider_failure_writes_nothing(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        """A question with no answer is not a turn (§22.6)."""
        double = _Double([LlmUnavailable("down")])
        with pytest.raises(LlmUnavailable):
            _service(factory, corpus, provider=double).ask(player_id, "anything")
        with factory() as session:
            assert advisor_repo.latest_conversation(session, player_id) is None

    def test_the_minimum_interval_refuses_a_rapid_second_question(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        service = _service(factory, corpus, min_interval_seconds=10)
        service.ask(player_id, "one")
        with pytest.raises(AdvisorThrottled, match="before asking again"):
            service.ask(player_id, "two")

    def test_the_daily_ceiling_is_counted_from_stored_answers(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        """Counted from the table so a restart does not hand out a fresh allowance."""
        service = _service(factory, corpus, min_interval_seconds=0, max_calls_per_day=2)
        service.ask(player_id, "one")
        service.ask(player_id, "two")
        with pytest.raises(AdvisorThrottled, match="daily limit of 2"):
            service.ask(player_id, "three")


class TestWhatTheGatherPutsInTheDigest:
    """The two fields §22.2 declared, defaulted, and then never filled.

    Both bugs were invisible: the renderers existed, the dataclass fields existed with empty
    defaults, and the only symptom was an advisor that never mentioned what a task would do or
    which practice had gone stale. Driven end-to-end through :meth:`AdvisorService.ask` rather
    than by calling ``_snapshot``, because the gather is exactly what regressed.
    """


def _seed_entry(session: Session, player_id: int, *, consequences: dict[str, Any]) -> None:
    """One ranked run holding a single entry, so the digest has something to describe."""
    snapshot = RecommendationSnapshot(
        player_id=player_id, run_at=NOW, roadmap_selection={}, scoring_profile_version=1
    )
    session.add(snapshot)
    session.flush()
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="train_magic_87_94",
            rank=1,
            candidate_kind=RecommendationCandidateKind.PROGRESSION,
            score=0.42,
            factors={},
            reason="unblocks Ice Barrage NH",
            estimate_confidence=Confidence.MEDIUM,
            consequences=consequences,
        )
    )
    session.commit()


def _seed_milestone(
    session: Session,
    player_id: int,
    *,
    key: str,
    class_: MilestoneClass,
    last_practiced_at: datetime | None,
) -> None:
    session.add(
        MilestoneRow(
            player_id=player_id,
            key=key,
            kind=MilestoneKind.SELF_ATTESTED,
            class_=class_,
            achieved=True,
            attested_at=NOW - timedelta(days=500),
            last_practiced_at=last_practiced_at,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
    )
    session.commit()


class TestDigestInvalidation:
    def test_a_moved_account_flags_the_change_and_updates_the_stored_hash(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        double = _Double()
        service = _service(factory, corpus, provider=double, min_interval_seconds=0)
        first = service.ask(player_id, "one")
        with factory() as session:
            before = advisor_repo.get_conversation(session, player_id, first.conversation_id)
            assert before is not None
            stored_before = before.digest_hash

        with factory() as session:
            player = session.get(Player, player_id)
            assert player is not None
            player.combat_level = 99
            session.commit()

        second = service.ask(player_id, "two", conversation_id=first.conversation_id)
        assert second.digest_changed is True
        assert double.prompts[-1].digest_changed is True
        with factory() as session:
            after = advisor_repo.get_conversation(session, player_id, first.conversation_id)
            assert after is not None
            assert after.digest_hash != stored_before


class TestPersistence:
    def test_the_tool_trace_is_stored_without_results(
        self, factory: sessionmaker[Session], corpus: Content, player_id: int
    ) -> None:
        trace = (ToolTraceEntry(name="get_skill_detail", arguments={}, result_chars=120),)
        double = _Double([AdvisorTurn(answer="hi", model="m", generated_at=NOW, tool_trace=trace)])
        reply = _service(factory, corpus, provider=double).ask(player_id, "one")
        with factory() as session:
            stored = advisor_repo.thread(session, reply.conversation_id)[1].tool_trace
            assert stored is not None
            assert stored[0]["name"] == "get_skill_detail"
            assert "content" not in stored[0]
