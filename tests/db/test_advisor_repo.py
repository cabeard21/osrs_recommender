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

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.db.conftest import NOW
from tracker.db import advisor as repo
from tracker.db.enums import AdvisorRole
from tracker.db.models import AdvisorConversation, AdvisorMessage
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
    def test_the_title_is_the_first_question_collapsed(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session), "  what   should\nI do next? ")
        assert conversation.title == "what should I do next?"

    def test_a_long_question_is_truncated_with_an_ellipsis(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session), "x" * 200)
        assert len(conversation.title) == repo.TITLE_LENGTH
        assert conversation.title.endswith("…")

    def test_get_conversation_is_scoped_to_its_owner(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """A conversation id from a URL must not address another player's thread."""
        mine = new_player(session, username="mine")
        theirs = new_player(session, username="theirs")
        conversation = _start(session, mine)
        assert repo.get_conversation(session, mine, conversation.id) is not None
        assert repo.get_conversation(session, theirs, conversation.id) is None

    def test_latest_conversation_follows_updated_at(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        player_id = new_player(session)
        older = _start(session, player_id, "older")
        _start(session, player_id, "newer")
        _append(session, older, "revived", now=NOW + timedelta(hours=1))
        latest = repo.latest_conversation(session, player_id)
        assert latest is not None
        assert latest.id == older.id


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

    def test_ordinals_are_monotonic_across_turns(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        _append(session, conversation, "one")
        _append(session, conversation, "two")
        assert [m.ordinal for m in repo.thread(session, conversation.id)] == [0, 1, 2, 3]

    def test_a_duplicate_ordinal_is_rejected_by_the_schema(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """Ordering is data; two rows sharing an ordinal would replay ambiguously."""
        conversation = _start(session, new_player(session))
        _append(session, conversation, "one")
        session.add(
            AdvisorMessage(
                conversation_id=conversation.id,
                ordinal=0,
                role=AdvisorRole.USER,
                content="collides",
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_the_conversation_hash_and_timestamp_follow_the_turn(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        later = NOW + timedelta(hours=2)
        _append(session, conversation, "q", digest_hash="hash-2", now=later)
        assert conversation.digest_hash == "hash-2"
        assert conversation.updated_at == later

    def test_the_answer_records_the_digest_it_was_written_against(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """Per-message, so the UI can mark one answer stale rather than the whole thread."""
        conversation = _start(session, new_player(session))
        _append(session, conversation, "q", digest_hash="hash-7")
        assert repo.thread(session, conversation.id)[1].digest_hash == "hash-7"

    def test_token_counts_and_hedges_are_stored(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        _append(
            session,
            conversation,
            "q",
            turn=_turn(
                uncertain=("spawn locations are from my own knowledge",),
                input_tokens=1000,
                cache_read_input_tokens=800,
            ),
        )
        answer = repo.thread(session, conversation.id)[1]
        assert answer.uncertain == ["spawn locations are from my own knowledge"]
        assert answer.input_tokens == 1000
        assert answer.cache_read_input_tokens == 800


class TestD16:
    def test_the_trace_stores_names_arguments_and_sizes(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        trace = (
            ToolTraceEntry(name="get_item_price", arguments={"item_ids": [4151]}, result_chars=142),
        )
        _append(session, conversation, "q", turn=_turn(tool_trace=trace))
        assert repo.thread(session, conversation.id)[1].tool_trace == [
            {
                "name": "get_item_price",
                "arguments": {"item_ids": [4151]},
                "result_chars": 142,
                "is_error": False,
            }
        ]

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

    def test_no_role_exists_for_a_tool_message(self) -> None:
        """The enum's two members are the schema-level statement of D16."""
        assert {role.value for role in AdvisorRole} == {"user", "assistant"}


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

    def test_it_is_bounded_to_the_requested_turns(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        for index in range(5):
            _append(session, conversation, f"question {index}")
        history = repo.history_for_prompt(session, conversation.id, max_turns=2)
        assert len(history) == 4
        assert history[0].text == "question 3"

    def test_it_never_begins_on_an_assistant_turn(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """A provider rejects a transcript that does not alternate from a user message."""
        conversation = _start(session, new_player(session))
        for index in range(3):
            _append(session, conversation, f"question {index}")
        session.execute(sa.delete(AdvisorMessage).where(AdvisorMessage.ordinal == 0))
        history = repo.history_for_prompt(session, conversation.id, max_turns=10)
        assert history[0].role == "user"


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

    def test_an_odd_keep_still_leaves_a_thread_starting_on_a_question(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """Rounding up the trim is what stops an orphaned answer surviving."""
        conversation = _start(session, new_player(session))
        for index in range(4):
            _append(session, conversation, f"question {index}", keep_messages=3)
        assert repo.thread(session, conversation.id)[0].role is AdvisorRole.USER

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

    def test_pruning_a_conversation_removes_its_messages(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        player_id = new_player(session)
        doomed = _start(session, player_id, "doomed")
        _append(session, doomed, "q", now=NOW)
        kept = _start(session, player_id, "kept")
        _append(session, kept, "q", now=NOW + timedelta(hours=1))
        repo.prune_conversations(session, player_id, keep=1)
        session.flush()
        assert repo.thread(session, doomed.id) == []


class TestAnswersSince:
    def test_it_counts_answers_not_questions(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        """Counting both roles would halve the effective daily ceiling."""
        conversation = _start(session, new_player(session))
        _append(session, conversation, "one")
        _append(session, conversation, "two")
        assert repo.answers_since(session, NOW - timedelta(days=1)) == 2

    def test_it_ignores_answers_before_the_boundary(
        self, session: Session, new_player: Callable[..., int]
    ) -> None:
        conversation = _start(session, new_player(session))
        _append(session, conversation, "old", turn=_turn(generated_at=NOW - timedelta(days=2)))
        assert repo.answers_since(session, NOW - timedelta(days=1)) == 0
