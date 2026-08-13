"""Orchestration for §21: cache, throttle, ask, store.

Lives in ``tracker/sync/`` because that is where this codebase puts the layer owning a
session *and* an integration — the same place :class:`~tracker.sync.worker.SingleFlightRefresher`
lives, and this mirrors its shape deliberately.

**The order of the four checks is the design**, and §21.6 fixes it:

1. **Cache first, before any throttle.** Re-reading advice is not a new request. A user who
   reloads the page, or opens the same task twice, must never be told to wait — the answer is
   already bought and paid for.
2. **Single-flight.** One generation at a time, acquired non-blocking, so a double-click
   returns immediately rather than queueing a second paid call behind the first.
3. **Minimum interval**, mirroring §7.5's manual-refresh throttle.
4. **Daily ceiling**, counted from the stored notes so a restart does not reset it.

``force`` skips step 1 and nothing else. Somebody who wants a second opinion may have one;
somebody who wants forty in a minute may not.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.schema import Candidate
from tracker.db import guidance as guidance_repo
from tracker.db.enums import RecommendationCandidateKind
from tracker.db.models import RecommendationEntry, RecommendationSnapshot
from tracker.db.projection import build_player_state
from tracker.db.repository import roadmap_selection
from tracker.db.session import session_scope
from tracker.domain.types import (
    Acceleration,
    BandEstimate,
    CandidateKind,
    Confidence,
    Consequences,
    Estimate,
    FactorContribution,
    GateProgress,
    GoalLink,
    GoalProgress,
    LeafRef,
    Recommendation,
    UnblockedCapability,
)
from tracker.guidance.context import build_task_context
from tracker.guidance.prompt import GUIDANCE_SCHEMA_VERSION, build_prompt
from tracker.integrations.llm.types import GuidanceDTO, GuidanceProvider


class GuidanceNotFound(LookupError):
    """No such player, or the task is not in the latest ranking.

    Distinct from a provider failure: nothing was asked and nothing would help but a sync.
    """


class GuidanceThrottled(RuntimeError):
    """§21.6 declined — asked again too soon, a generation is in flight, or the day is spent.

    An ordinary, explainable refusal. Never a silent wait and never a partial answer.
    """


@dataclass(frozen=True, slots=True)
class StoredGuidance:
    """One answer, and whether it cost anything to obtain just now."""

    dto: GuidanceDTO
    task_name: str
    cached: bool


class GuidanceService:
    """§21's read-through cache over a guidance provider.

    ``provider`` is ``None`` on an install that has not configured the feature, and that is a
    supported configuration rather than an error state (D14). :attr:`enabled` is what callers
    check; every other method assumes it is true.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        content: Content,
        settings: Settings,
        *,
        provider: GuidanceProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._content = content
        self._settings = settings.integrations.llm
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

    def guidance_for(
        self, player_id: int, candidate_id: str, *, force: bool = False
    ) -> StoredGuidance:
        """Return guidance for one ranked task, from cache or from the provider."""
        if self._provider is None:
            raise GuidanceThrottled("task guidance is not configured on this install")

        now = self._clock()
        with session_scope(self._session_factory) as session:
            recommendation = self._recommendation(session, player_id, candidate_id)
            context = build_task_context(
                state=build_player_state(session, player_id),
                recommendation=recommendation,
                content=self._content,
                roadmaps=roadmap_selection(session, player_id),
            )
            prompt = build_prompt(context)

            if not force:
                cached = guidance_repo.latest_note(
                    session,
                    player_id,
                    candidate_id,
                    context_hash=prompt.context_hash,
                    schema_version=GUIDANCE_SCHEMA_VERSION,
                    not_before=now - timedelta(hours=self._settings.guidance_ttl_hours),
                )
                if cached is not None:
                    return StoredGuidance(
                        dto=guidance_repo.body_to_dto(cached),
                        task_name=recommendation.name,
                        cached=True,
                    )

            # Nothing below this line is free. Every throttle applies from here, `force`
            # included — a second opinion is allowed; forty in a minute are not.
            if not self._lock.acquire(blocking=False):
                raise GuidanceThrottled(
                    "guidance is already being generated; wait for it to finish"
                )
            try:
                self._check_interval(now)
                self._check_daily_cap(session, now)
                dto = self._provider.generate(prompt)
                self._last_call_at = now
            finally:
                self._lock.release()

            guidance_repo.record_note(
                session,
                player_id=player_id,
                candidate_id=candidate_id,
                context_hash=prompt.context_hash,
                schema_version=GUIDANCE_SCHEMA_VERSION,
                dto=dto,
                keep=self._settings.keep_notes_per_candidate,
            )
            return StoredGuidance(dto=dto, task_name=recommendation.name, cached=False)

    # ------------------------------------------------------------------
    # §21.6's bounds
    # ------------------------------------------------------------------

    def _check_interval(self, now: datetime) -> None:
        minimum = self._settings.min_interval_seconds
        if minimum <= 0 or self._last_call_at is None:
            return
        elapsed = (now - self._last_call_at).total_seconds()
        if elapsed < minimum:
            raise GuidanceThrottled(
                f"guidance was generated {elapsed:.0f}s ago; wait "
                f"{minimum - elapsed:.0f}s before asking again"
            )

    def _check_daily_cap(self, session: Session, now: datetime) -> None:
        cap = self._settings.max_calls_per_day
        if cap <= 0:
            return
        # Midnight UTC rather than a rolling 24 hours: a ceiling a user can reason about
        # ("it resets at midnight") beats one that expires in pieces they cannot see.
        since = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        used = guidance_repo.notes_generated_since(session, since)
        if used >= cap:
            raise GuidanceThrottled(
                f"the daily guidance limit of {cap} has been reached; it resets at midnight UTC"
            )

    # ------------------------------------------------------------------
    # Rehydrating the engine's own output
    # ------------------------------------------------------------------

    def _recommendation(
        self, session: Session, player_id: int, candidate_id: str
    ) -> Recommendation:
        """Rebuild the ``Recommendation`` the latest run produced for this task.

        Read back from the snapshot rather than re-ranked, for §6.10's reason: the persisted
        entry is what the user is looking at, and re-deriving it here could hand the model a
        reason, estimate or consequence the ranked list never showed.
        """
        snapshot = session.scalar(
            select(RecommendationSnapshot)
            .where(RecommendationSnapshot.player_id == player_id)
            .order_by(RecommendationSnapshot.run_at.desc(), RecommendationSnapshot.id.desc())
            .limit(1)
        )
        if snapshot is None:
            raise GuidanceNotFound(f"player {player_id} has no recommendation run to explain yet")
        entry = session.scalar(
            select(RecommendationEntry).where(
                RecommendationEntry.snapshot_id == snapshot.id,
                RecommendationEntry.candidate_id == candidate_id,
            )
        )
        if entry is None:
            raise GuidanceNotFound(f"{candidate_id!r} is not in the latest recommendation run")
        return _entry_to_recommendation(entry, self._content)


def _entry_to_recommendation(entry: RecommendationEntry, content: Content) -> Recommendation:
    """One persisted row, back into the frozen shape §21.2 consumes.

    The name falls back through content, then the refresher templates, then the raw id — the
    same cascade the UI uses, so a renamed or deleted candidate degrades to something
    readable rather than raising.
    """
    candidate = content.candidates.get(entry.candidate_id)
    template = content.refreshers.get(entry.candidate_id)
    name = (
        candidate.name
        if candidate is not None
        else (template.name if template is not None else entry.candidate_id)
    )
    return Recommendation(
        candidate_id=entry.candidate_id,
        name=name,
        kind=_kind(entry, candidate),
        score=entry.score,
        factors=_factors(entry.factors),
        reason=entry.reason,
        estimate=_estimate(entry),
        blocked=entry.blocked,
        blockers=_blockers(entry.blockers),
        consequences=_consequences(entry.consequences),
    )


def _kind(entry: RecommendationEntry, candidate: Candidate | None) -> CandidateKind:
    """Recover the domain kind from the coarser one §6.10 stores.

    ``recommendation_entry.candidate_kind`` is ``progression | refresher`` — the distinction
    §9.8's list policy needs, and deliberately not the five-way :class:`CandidateKind`. So a
    refresher maps straight to ``practice``, and a progression entry has to be resolved
    through the corpus. When the corpus no longer declares it — renamed, deleted — the
    fallback is ``skill_training``, which is what the overwhelming majority of generated
    candidates are and which only affects one word of the rendered prompt.
    """
    if entry.candidate_kind is RecommendationCandidateKind.REFRESHER:
        return CandidateKind.PRACTICE
    return candidate.kind if candidate is not None else CandidateKind.SKILL_TRAINING


def _factors(raw: dict[str, Any] | None) -> dict[str, FactorContribution]:
    return {
        name: FactorContribution(
            name=name,
            value=float(values.get("value", 0.0)),
            weight=float(values.get("weight", 0.0)),
            log_contribution=float(values.get("log_contribution", 0.0)),
        )
        for name, values in (raw or {}).items()
    }


def _estimate(entry: RecommendationEntry) -> Estimate | None:
    bands = tuple(
        BandEstimate(
            from_level=int(band.get("from_level", 0)),
            to_level=int(band.get("to_level", 0)),
            method_id=band.get("method_id"),
            hours=float(band.get("hours", 0.0)),
            gp=int(band.get("gp", 0)),
            fallback=bool(band.get("fallback", False)),
        )
        for band in (entry.bands or ())
    )
    if entry.estimated_hours is None and entry.estimated_gp is None and not bands:
        return None
    return Estimate(
        hours=entry.estimated_hours,
        gp=entry.estimated_gp,
        confidence=Confidence(entry.estimate_confidence),
        bands=bands,
    )


def _blockers(raw: list[dict[str, Any]] | None) -> tuple[LeafRef, ...]:
    return tuple(
        LeafRef(
            leaf_type=str(leaf.get("leaf_type", "")),
            key=str(leaf.get("key", "")),
            description=str(leaf.get("description", "")),
            target=leaf.get("target"),
        )
        for leaf in (raw or ())
    )


def _consequences(raw: dict[str, Any] | None) -> Consequences:
    """§9.10's consequences, back from the JSON ``asdict`` wrote.

    An absent or empty object is a legitimate result — an entry that ranked on cheapness
    alone genuinely has nothing to say, and inventing something for it here would be exactly
    the authored justification §9.5 forbids.
    """
    data = raw or {}
    return Consequences(
        unblocks_capabilities=tuple(
            UnblockedCapability(**item) for item in data.get("unblocks_capabilities", ())
        ),
        gate_progress=tuple(
            GateProgress(
                candidate_id=item["candidate_id"],
                name=item["name"],
                remaining_before=item["remaining_before"],
                remaining_after=item["remaining_after"],
                satisfied=_blockers(item.get("satisfied")),
            )
            for item in data.get("gate_progress", ())
        ),
        goal_progress=tuple(
            GoalProgress(
                capability_id=item["capability_id"],
                name=item["name"],
                weight=item["weight"],
                remaining_before=item["remaining_before"],
                remaining_after=item["remaining_after"],
                on_roadmap=item["on_roadmap"],
                satisfied=_blockers(item.get("satisfied")),
            )
            for item in data.get("goal_progress", ())
        ),
        speeds_up=tuple(Acceleration(**item) for item in data.get("speeds_up", ())),
        goal_links=tuple(GoalLink(**item) for item in data.get("goal_links", ())),
    )
