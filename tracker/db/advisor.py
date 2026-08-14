"""§22.6's persistence, in the shape :mod:`tracker.db.guidance` established.

**The caller commits.** Every function here writes into a session it was handed and leaves the
transaction open, so a turn's two rows and the pruning that follows land together or not at all.
That is not a stylistic echo of the guidance repository — it is what makes "a question and its
answer are written together or not at all" enforceable rather than aspirational.

Serialization is field by field rather than via ``asdict``. A DTO gaining a field would then
silently start being persisted, and in this table that is precisely the failure D16 exists to
prevent: :class:`~tracker.integrations.llm.types.ToolTraceEntry` is one field away from
carrying the tool's output, and an ``asdict`` would store it the moment somebody added it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from tracker.advisor.prompt import ConversationTurn
from tracker.db.enums import AdvisorRole
from tracker.db.models import AdvisorConversation, AdvisorMessage
from tracker.integrations.llm.types import AdvisorTurn, ToolTraceEntry

#: How much of the first question becomes the thread's name. Long enough to tell two
#: conversations apart in a list, short enough not to wrap.
TITLE_LENGTH = 60


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def latest_conversation(session: Session, player_id: int) -> AdvisorConversation | None:
    """The thread this player was most recently answered in, if any."""
    return session.scalar(
        sa.select(AdvisorConversation)
        .where(AdvisorConversation.player_id == player_id)
        .order_by(AdvisorConversation.updated_at.desc(), AdvisorConversation.id.desc())
        .limit(1)
    )


def get_conversation(
    session: Session, player_id: int, conversation_id: int
) -> AdvisorConversation | None:
    """One thread, scoped to its owner.

    ``player_id`` is in the predicate rather than checked afterwards so that a conversation id
    from a URL cannot address another player's thread. §5 is a single-user install, which makes
    this defence in depth rather than access control — but a lookup that ignores ownership is
    the kind of thing that stops being harmless when an assumption changes.
    """
    return session.scalar(
        sa.select(AdvisorConversation).where(
            AdvisorConversation.id == conversation_id,
            AdvisorConversation.player_id == player_id,
        )
    )


def list_conversations(
    session: Session, player_id: int, *, limit: int
) -> Sequence[AdvisorConversation]:
    """Recent threads, newest first."""
    return list(
        session.scalars(
            sa.select(AdvisorConversation)
            .where(AdvisorConversation.player_id == player_id)
            .order_by(AdvisorConversation.updated_at.desc(), AdvisorConversation.id.desc())
            .limit(limit)
        )
    )


def thread(session: Session, conversation_id: int) -> Sequence[AdvisorMessage]:
    """Every stored message, in ordinal order."""
    return list(
        session.scalars(
            sa.select(AdvisorMessage)
            .where(AdvisorMessage.conversation_id == conversation_id)
            .order_by(AdvisorMessage.ordinal)
        )
    )


def history_for_prompt(
    session: Session, conversation_id: int, *, max_turns: int
) -> tuple[ConversationTurn, ...]:
    """The last ``max_turns`` question/answer pairs, oldest first.

    Trimmed **in pairs from the oldest end**, and the pairing is load-bearing: a history that
    began with an assistant message would replay as an answer to nothing, and a provider will
    reject a transcript that does not alternate from a user turn.
    """
    messages = thread(session, conversation_id)
    kept = list(messages[-(max_turns * 2) :]) if max_turns > 0 else []
    while kept and kept[0].role is not AdvisorRole.USER:
        kept = kept[1:]
    return tuple(
        ConversationTurn(role=message.role.value, text=message.content) for message in kept
    )


def answers_since(session: Session, since: datetime) -> int:
    """How many answers have been generated since ``since`` — §22.7's daily ceiling.

    Counts **assistant** rows only. A question with no answer never reaches the database, but
    counting both roles would still halve the effective ceiling, and a user told they had spent
    sixty calls after thirty questions would be right to call it a bug.
    """
    return (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(AdvisorMessage)
            .where(
                AdvisorMessage.role == AdvisorRole.ASSISTANT,
                AdvisorMessage.created_at >= since,
            )
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def start_conversation(
    session: Session,
    *,
    player_id: int,
    question: str,
    digest_hash: str,
    schema_version: int,
    model: str,
    now: datetime,
) -> AdvisorConversation:
    """Open a thread. The caller commits."""
    conversation = AdvisorConversation(
        player_id=player_id,
        title=_title(question),
        schema_version=schema_version,
        digest_hash=digest_hash,
        model=model,
        created_at=now,
        updated_at=now,
    )
    session.add(conversation)
    session.flush()
    return conversation


def append_turn(
    session: Session,
    conversation: AdvisorConversation,
    *,
    question: str,
    turn: AdvisorTurn,
    digest_hash: str,
    keep_messages: int,
    now: datetime,
) -> tuple[AdvisorMessage, AdvisorMessage]:
    """Write one question and its answer, then prune the thread.

    Both rows in one flush. A stored question with no answer is not a turn — it would replay
    into the next prompt as an unanswered user message and quietly change what the model was
    asked, which is a subtler failure than simply losing it.
    """
    next_ordinal = _next_ordinal(session, conversation.id)
    asked = AdvisorMessage(
        conversation_id=conversation.id,
        ordinal=next_ordinal,
        role=AdvisorRole.USER,
        content=question,
        created_at=now,
    )
    answered = AdvisorMessage(
        conversation_id=conversation.id,
        ordinal=next_ordinal + 1,
        role=AdvisorRole.ASSISTANT,
        content=turn.answer,
        uncertain=list(turn.uncertain),
        tool_trace=[_trace_to_row(entry) for entry in turn.tool_trace],
        model=turn.model,
        stop_reason=turn.stop_reason or None,
        digest_hash=digest_hash,
        created_at=turn.generated_at or now,
        input_tokens=turn.input_tokens,
        output_tokens=turn.output_tokens,
        cache_read_input_tokens=turn.cache_read_input_tokens,
        cache_creation_input_tokens=turn.cache_creation_input_tokens,
    )
    session.add_all([asked, answered])

    conversation.digest_hash = digest_hash
    conversation.updated_at = now
    if turn.model:
        conversation.model = turn.model
    session.flush()

    _prune_messages(session, conversation.id, keep=keep_messages)
    return asked, answered


def prune_conversations(session: Session, player_id: int, *, keep: int) -> None:
    """Drop all but the ``keep`` most recently updated threads.

    §6.10's shape: pruned on write, no background job.
    """
    doomed = list(
        session.scalars(
            sa.select(AdvisorConversation.id)
            .where(AdvisorConversation.player_id == player_id)
            .order_by(AdvisorConversation.updated_at.desc(), AdvisorConversation.id.desc())
            .offset(keep)
        )
    )
    if not doomed:
        return
    session.execute(sa.delete(AdvisorMessage).where(AdvisorMessage.conversation_id.in_(doomed)))
    session.execute(sa.delete(AdvisorConversation).where(AdvisorConversation.id.in_(doomed)))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _title(question: str) -> str:
    collapsed = " ".join(question.split())
    if len(collapsed) <= TITLE_LENGTH:
        return collapsed
    return collapsed[: TITLE_LENGTH - 1].rstrip() + "…"


def _next_ordinal(session: Session, conversation_id: int) -> int:
    highest = session.scalar(
        sa.select(sa.func.max(AdvisorMessage.ordinal)).where(
            AdvisorMessage.conversation_id == conversation_id
        )
    )
    return 0 if highest is None else int(highest) + 1


def _prune_messages(session: Session, conversation_id: int, *, keep: int) -> None:
    """Trim from the oldest end, **always in pairs**.

    An odd trim would leave a thread beginning with an assistant message, which
    :func:`history_for_prompt` would then have to discard anyway — so the pairing is enforced
    here, once, rather than compensated for on every read.
    """
    ordinals = list(
        session.scalars(
            sa.select(AdvisorMessage.ordinal)
            .where(AdvisorMessage.conversation_id == conversation_id)
            .order_by(AdvisorMessage.ordinal)
        )
    )
    excess = len(ordinals) - keep
    if excess <= 0:
        return
    # Round up to an even count so the survivors still start on a question.
    excess += excess % 2
    session.execute(
        sa.delete(AdvisorMessage).where(
            AdvisorMessage.conversation_id == conversation_id,
            AdvisorMessage.ordinal.in_(ordinals[:excess]),
        )
    )


def _trace_to_row(entry: ToolTraceEntry) -> dict[str, Any]:
    """One trace entry, field by field.

    Note what is *not* here: the tool's output. :class:`ToolTraceEntry` does not carry it, and
    this function names its fields explicitly so that a future edit which adds one has to come
    here and decide — rather than having ``asdict`` decide silently (D16).
    """
    return {
        "name": entry.name,
        "arguments": dict(entry.arguments),
        "result_chars": entry.result_chars,
        "is_error": entry.is_error,
    }
