"""§22.7's orchestration: gather, ask, store.

Lives beside :mod:`tracker.sync.guidance` because it is the same kind of thing — the layer that
owns a session *and* an integration — and it mirrors that module's shape deliberately. Two
differences are worth stating up front, because both are departures rather than omissions.

**There is no cache step.** §21.6's first rule is *cache first, before any throttle*, and it has
no analogue here: every question is new, so there is nothing to re-read. The property that rule
protected still holds by other means — re-reading an existing thread is a read-model query that
never reaches this class, so a page reload is never rate-limited. The rule is absent because it
does not apply, and this paragraph exists so a later reader can tell that from an oversight.

**The provider call happens with no session held.** Session A gathers the snapshot and the
history and closes; the turn runs; session B writes. A tool-using turn is several sequential
round trips and can run for a minute, and :mod:`tracker.ui.pages` already documents what a
transaction held that long does to a process that is also serving ``/api/sync`` (§5).

The three remaining bounds run in §21.6's order: single-flight, minimum interval, daily ceiling.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from tracker.advisor.digest import build_digest, render_digest
from tracker.advisor.dispatch import execute_tool
from tracker.advisor.prompt import (
    ADVISOR_SCHEMA_VERSION,
    ADVISOR_SYSTEM_PROMPT,
    build_prompt,
    digest_hash,
)
from tracker.advisor.snapshot import (
    AdvisorSnapshot,
    PriceFact,
    RankedTask,
    build_advisor_snapshot,
)
from tracker.advisor.tools import TOOLS, tools_fingerprint
from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.db import advisor as advisor_repo
from tracker.db import entry_decode
from tracker.db.models import (
    AdvisorConversation,
    ItemPrice,
    Player,
    RecommendationEntry,
    RecommendationSnapshot,
)
from tracker.db.projection import build_player_state
from tracker.db.repository import roadmap_selection
from tracker.db.session import session_scope
from tracker.domain.types import Freshness, PlayerState
from tracker.estimation.prices import (
    REASON_CACHED_HIGH,
    REASON_CACHED_LOW,
    REASON_RECENT_HIGH,
    REASON_RECENT_LOW,
)
from tracker.freshness.policy import freshness
from tracker.integrations.llm.types import AdvisorProvider, AdvisorTurn
from tracker.progression.engine import compute_capability_states


class AdvisorNotFound(LookupError):
    """No such player, or no such conversation. Nothing would help but a sync or a new thread."""


class AdvisorThrottled(RuntimeError):
    """§22.7 declined — asked again too soon, one is in flight, or the day is spent.

    An ordinary, explainable refusal. Never a silent wait and never a partial answer.
    """


@dataclass(frozen=True, slots=True)
class AdvisorReply:
    """One answered question, and whether the account moved underneath the thread."""

    conversation_id: int
    turn: AdvisorTurn
    digest_changed: bool


class AdvisorService:
    """§22's read-gather-ask-write cycle over an advisor provider.

    ``provider`` is ``None`` on an install that has not configured the feature, which is a
    supported configuration rather than an error state (D14, §22.1). :attr:`enabled` is what
    callers check; every other method assumes it is true.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        content: Content,
        settings: Settings,
        *,
        provider: AdvisorProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._content = content
        self._settings = settings.integrations.llm.advisor
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(UTC))
        # §5 is one process, so a plain lock is the whole of single-flight.
        self._lock = threading.Lock()
        self._last_call_at: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self._provider is not None

    def close(self) -> None:
        if self._provider is not None:
            self._provider.close()

    def ask(
        self, player_id: int, question: str, *, conversation_id: int | None = None
    ) -> AdvisorReply:
        """Answer one question in a new or existing thread."""
        if self._provider is None:
            raise AdvisorThrottled("the advisor is not configured on this install")
        asked = question.strip()
        if not asked:
            raise AdvisorNotFound("a question is required")

        now = self._clock()
        fingerprint = tools_fingerprint()

        # --- Session A: gather, then close before anything is paid for. ----------------
        with session_scope(self._session_factory) as session:
            if session.get(Player, player_id) is None:
                raise AdvisorNotFound(f"player {player_id} does not exist")
            conversation = self._conversation(session, player_id, conversation_id)
            snapshot = self._snapshot(session, player_id, now)
            digest = render_digest(build_digest(snapshot))
            current_hash = digest_hash(ADVISOR_SYSTEM_PROMPT, digest, fingerprint)
            history = (
                advisor_repo.history_for_prompt(
                    session, conversation.id, max_turns=self._settings.max_history_turns
                )
                if conversation is not None
                else ()
            )
            digest_changed = conversation is not None and conversation.digest_hash != current_hash
            existing_id = conversation.id if conversation is not None else None

        prompt = build_prompt(
            digest=digest,
            question=asked,
            history=history,
            tools_fingerprint=fingerprint,
            digest_changed=digest_changed,
        )

        # --- The bounds. Nothing below this line is free. ------------------------------
        if not self._lock.acquire(blocking=False):
            raise AdvisorThrottled("a question is already being answered; wait for it to finish")
        try:
            self._check_interval(now)
            self._check_daily_cap(now)
            turn = self._provider.converse(
                prompt,
                TOOLS,
                partial(execute_tool, snapshot),
                max_iterations=self._settings.max_model_iterations,
                max_tool_calls=self._settings.max_tool_calls,
            )
            self._last_call_at = now
        finally:
            self._lock.release()

        # --- Session B: write. ---------------------------------------------------------
        with session_scope(self._session_factory) as session:
            conversation = (
                advisor_repo.get_conversation(session, player_id, existing_id)
                if existing_id is not None
                else None
            )
            if conversation is None:
                conversation = advisor_repo.start_conversation(
                    session,
                    player_id=player_id,
                    question=asked,
                    digest_hash=prompt.digest_hash,
                    schema_version=ADVISOR_SCHEMA_VERSION,
                    model=turn.model or "unknown",
                    now=now,
                )
            advisor_repo.append_turn(
                session,
                conversation,
                question=asked,
                turn=turn,
                digest_hash=prompt.digest_hash,
                keep_messages=self._settings.keep_messages_per_conversation,
                now=now,
            )
            advisor_repo.prune_conversations(
                session, player_id, keep=self._settings.keep_conversations
            )
            return AdvisorReply(
                conversation_id=conversation.id,
                turn=turn,
                digest_changed=digest_changed,
            )

    # ------------------------------------------------------------------
    # §22.7's bounds
    # ------------------------------------------------------------------

    def _check_interval(self, now: datetime) -> None:
        minimum = self._settings.min_interval_seconds
        if minimum <= 0 or self._last_call_at is None:
            return
        elapsed = (now - self._last_call_at).total_seconds()
        if elapsed < minimum:
            raise AdvisorThrottled(
                f"the last answer was {elapsed:.0f}s ago; wait "
                f"{minimum - elapsed:.0f}s before asking again"
            )

    def _check_daily_cap(self, now: datetime) -> None:
        cap = self._settings.max_calls_per_day
        if cap <= 0:
            return
        # Midnight UTC rather than a rolling 24 hours, for §21.6's reason: a ceiling a user can
        # reason about beats one that expires in pieces they cannot see.
        since = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with session_scope(self._session_factory) as session:
            used = advisor_repo.answers_since(session, since)
        if used >= cap:
            raise AdvisorThrottled(
                f"the daily limit of {cap} advisor answers has been reached; "
                "it resets at midnight UTC"
            )

    # ------------------------------------------------------------------
    # Gathering
    # ------------------------------------------------------------------

    def _conversation(
        self, session: Session, player_id: int, conversation_id: int | None
    ) -> AdvisorConversation | None:
        """The thread to continue, or ``None`` to start one.

        An explicitly requested id that does not exist is an error rather than a silent new
        thread: the user followed a link to a specific conversation, and quietly giving them a
        different one loses their history without saying so.
        """
        if conversation_id is None:
            return None
        conversation = advisor_repo.get_conversation(session, player_id, conversation_id)
        if conversation is None:
            raise AdvisorNotFound(f"conversation {conversation_id} does not exist")
        return conversation

    def _snapshot(self, session: Session, player_id: int, now: datetime) -> AdvisorSnapshot:
        state = build_player_state(session, player_id)
        capabilities = compute_capability_states(state, self._content, self._content.profile, now)
        ranked, blocked = _persisted_entries(session, player_id, self._content)
        return build_advisor_snapshot(
            state=state,
            content=self._content,
            capabilities=tuple(capabilities.values()),
            roadmaps=roadmap_selection(session, player_id),
            ranked=ranked,
            blocked=blocked,
            stale_practice=_stale_practice(state, self._content, now),
            prices=_price_facts(session, self._content),
            now=now,
        )


def _stale_practice(
    state: PlayerState, content: Content, now: datetime
) -> tuple[tuple[str, str], ...]:
    """§6.9's aged execution evidence, per milestone, for §22.2's practice section.

    Per *milestone* rather than per practice group. The group carries an ``urgency`` float that
    moves every day, and §22.3 hashes this rendering into the conversation's cached prefix — a
    daily-moving number there would re-cache the whole prefix on a turn that earned nothing.
    The three freshness *bands* transition rarely, which is the same trade
    :class:`~tracker.advisor.snapshot.ObservationAge` already makes for the sync timestamp.

    :func:`~tracker.freshness.policy.freshness` returns ``None`` twice over, and both silences
    are load-bearing (G6): a ``knowledge`` or ``threshold`` milestone does not age, and a
    milestone with no ``last_practiced_at`` has no evidence *either way* — reporting that as
    stale would turn absence of evidence into evidence of decay.

    Ordering is left to :func:`~tracker.advisor.snapshot.build_advisor_snapshot`, which sorts.
    """
    aged = []
    for key, milestone in state.milestones.items():
        band = freshness(milestone.last_practiced_at, now, milestone.class_)
        if band is None or band is Freshness.CURRENT:
            continue
        declared = content.milestones.get(key)
        aged.append((declared.name if declared is not None else key, band.value))
    return tuple(aged)


def _persisted_entries(
    session: Session, player_id: int, content: Content
) -> tuple[tuple[RankedTask, ...], tuple[RankedTask, ...]]:
    """The latest run's entries, **read back rather than re-ranked**.

    §21.5's reason, one feature over: the persisted entry is what the user is looking at, and
    re-deriving it here could hand the model a reason, an estimate or a consequence the ranked
    list never displayed. An account with no run yet yields two empty tuples rather than an
    error — that is a real state, and the digest says so in words.
    """
    snapshot = session.scalar(
        sa.select(RecommendationSnapshot)
        .where(RecommendationSnapshot.player_id == player_id)
        .order_by(RecommendationSnapshot.run_at.desc(), RecommendationSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return (), ()

    ranked: list[RankedTask] = []
    blocked: list[RankedTask] = []
    for entry in session.scalars(
        sa.select(RecommendationEntry)
        .where(RecommendationEntry.snapshot_id == snapshot.id)
        .order_by(RecommendationEntry.rank)
    ):
        task = _entry_to_task(entry, content)
        (blocked if entry.blocked else ranked).append(task)
    return tuple(ranked), tuple(blocked)


def _entry_to_task(entry: RecommendationEntry, content: Content) -> RankedTask:
    """One persisted row, in the shape §22.2 and §22.4 read.

    The name falls back through content, then the refresher templates, then the raw id — the
    same cascade :mod:`tracker.sync.guidance` uses, so a renamed or deleted candidate degrades
    to something readable rather than raising.
    """
    candidate = content.candidates.get(entry.candidate_id)
    template = content.refreshers.get(entry.candidate_id)
    name = (
        candidate.name
        if candidate is not None
        else (template.name if template is not None else entry.candidate_id)
    )
    return RankedTask(
        candidate_id=entry.candidate_id,
        name=name,
        kind=candidate.kind.value if candidate is not None else "practice",
        rank=entry.rank,
        score=entry.score,
        reason=entry.reason or "",
        blocked=entry.blocked,
        hours=entry.estimated_hours,
        gp=entry.estimated_gp,
        confidence=entry_decode.confidence_word(entry.estimate_confidence),
        blockers=entry_decode.blockers_from_json(entry.blockers),
        bands=entry_decode.bands_from_json(entry.bands),
        consequences=entry_decode.consequences_from_json(entry.consequences),
    )


def _price_facts(session: Session, content: Content) -> dict[int, PriceFact]:
    """The cached prices, named from the corpus.

    Read-only and never a fetch (D15): §7.5's scheduler owns when this application talks to the
    wiki, and a refresh chosen by a model would be an outbound request the user did not ask for.

    ``selected_price_gp`` in preference to ``high_price_gp`` so the model sees the figure §8.3's
    cascade actually costed, rather than a raw quote the estimator may have declined to use.
    """
    names = {item.item_id: item.name for item in content.items.values() if item.item_id is not None}

    def selected_trade_at(row: ItemPrice) -> datetime | None:
        if row.selected_price_gp is None:
            return row.high_trade_at if row.high_price_gp is not None else None
        if row.selection_reason in {REASON_RECENT_HIGH, REASON_CACHED_HIGH}:
            return row.high_trade_at
        if row.selection_reason in {REASON_RECENT_LOW, REASON_CACHED_LOW}:
            return row.low_trade_at
        # Static hints and unknown selection reasons have no attributable market trade.
        return None

    return {
        row.item_id: PriceFact(
            item_id=row.item_id,
            name=names.get(row.item_id, str(row.item_id)),
            price_gp=(
                row.selected_price_gp if row.selected_price_gp is not None else row.high_price_gp
            ),
            trade_at=selected_trade_at(row),
            fetched_at=row.fetched_at,
            provider=row.provider,
        )
        for row in session.scalars(sa.select(ItemPrice))
    }
