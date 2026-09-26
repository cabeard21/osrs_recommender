"""§22.6's repository: ordinals, atomic turns, and pruning that keeps pairs.

The pairing tests carry most of the weight. A thread trimmed to an odd length still *reads*
fine — it has messages, they are in order, nothing raises — and the damage only appears one
turn later, when a history beginning with an answer is replayed into a prompt and the provider
rejects the transcript. That is a long way from the cause, so it is pinned here at the cause.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from tests.db.conftest import NOW
from tracker.db import advisor as repo
from tracker.db.enums import AdvisorRole
from tracker.db.models import AdvisorConversation
from tracker.integrations.llm.types import AdvisorTurn, ToolTraceEntry

SCHEMA_VERSION = 1


def _turn(answer: str = "an answer", **overrides: Any) -> AdvisorTurn:
    defaults: dict[str, Any] = {
        "answer": answer,
        "model": "claude-opus-5",
        "generated_at": NOW,
        "stop_reason": "end_turn",
    }
    defaults.update(overrides)
    return AdvisorTurn(**defaults)


def _start(
    session: Session, player_id: int, question: str = "first question"
) -> AdvisorConversation:
    return repo.start_conversation(
        session,
        player_id=player_id,
        question=question,
        digest_hash="hash-1",
        schema_version=SCHEMA_VERSION,
        model="claude-opus-5",
        now=NOW,
    )


def _append(
    session: Session,
    conversation: AdvisorConversation,
    question: str,
    *,
    turn: AdvisorTurn | None = None,
    digest_hash: str = "hash-1",
    keep_messages: int = 60,
    now: datetime = NOW,
) -> None:
    repo.append_turn(
        session,
        conversation,
        question=question,
        turn=turn or _turn(),
        digest_hash=digest_hash,
        keep_messages=keep_messages,
        now=now,
    )


class TestConversations:
    def test_get_conversation_is_scoped_to_its_owner(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """A conversation id from a URL must not address another player's thread."""
        mine = new_player(session, username="mine")
        theirs = new_player(session, username="theirs")
        conversation = _start(session, mine)
        assert repo.get_conversation(session, mine, conversation.id) is not None
        assert repo.get_conversation(session, theirs, conversation.id) is None


class TestAppendTurn:
    def test_it_writes_a_question_and_an_answer(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        _append(session, conversation, "a question")
        messages = repo.thread(session, conversation.id)
        assert [m.role for m in messages] == [AdvisorRole.USER, AdvisorRole.ASSISTANT]
        assert messages[0].content == "a question"
        assert messages[1].content == "an answer"


class TestD16:
    def test_the_trace_stores_no_tool_output(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """A stored result would grow unboundedly and invite a future edit to re-send it."""
        conversation = _start(session, new_player(session))
        trace = (ToolTraceEntry(name="get_skill_detail", arguments={}, result_chars=9000),)
        _append(session, conversation, "q", turn=_turn(tool_trace=trace))
        stored = repo.thread(session, conversation.id)[1].tool_trace
        assert stored is not None
        assert set(stored[0]) == {"name", "arguments", "result_chars", "is_error"}


class TestHistoryForPrompt:
    def test_it_returns_pairs_oldest_first(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        _append(session, conversation, "one")
        _append(session, conversation, "two")
        history = repo.history_for_prompt(session, conversation.id, max_turns=5)
        assert [turn.role for turn in history] == ["user", "assistant", "user", "assistant"]
        assert history[0].text == "one"


class TestPruning:
    def test_messages_are_trimmed_from_the_oldest_end_in_pairs(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        for index in range(5):
            _append(session, conversation, f"question {index}", keep_messages=4)
        messages = repo.thread(session, conversation.id)
        assert len(messages) == 4
        assert messages[0].role is AdvisorRole.USER
        assert messages[0].content == "question 3"

    def test_conversations_are_pruned_by_recency(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        player_id = new_player(session)
        for index in range(4):
            conversation = _start(session, player_id, f"thread {index}")
            _append(session, conversation, "q", now=NOW + timedelta(hours=index))
        repo.prune_conversations(session, player_id, keep=2)
        session.flush()
        surviving = {c.title for c in repo.list_conversations(session, player_id, limit=10)}
        assert surviving == {"thread 3", "thread 2"}


class TestAnswersSince:
    def test_it_counts_answers_not_questions(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """Counting both roles would halve the effective daily ceiling."""
        conversation = _start(session, new_player(session))
        _append(session, conversation, "one")
        _append(session, conversation, "two")
        assert repo.answers_since(session, NOW - timedelta(days=1)) == 2
