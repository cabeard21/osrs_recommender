"""One turn's frozen view of the account (§22.2).

Built once per question and then read by two different consumers — :mod:`tracker.advisor.digest`,
which renders the always-present summary, and :mod:`tracker.advisor.dispatch`, which answers
tool calls. One object for both is the point: a digest built from one read and a tool answering
from a second could disagree about the same account within a single answer, and the user would
have no way to tell which half was current.

**This module runs no queries.** :func:`build_advisor_snapshot` is a pure assembler over inputs
the caller has already read — see the package docstring on D15 and on where the session lives.
The ranked entries in particular are the *persisted* ones from the latest run (§6.10), never
re-ranked, for the reason :meth:`tracker.sync.guidance.GuidanceService._recommendation` gives:
the persisted entry is what the user is looking at, and re-deriving it here could show the model
a reason or an estimate the list never displayed.

Ordering is fixed everywhere, because §22.3 hashes the digest rendered from this.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from tracker.content.loader import Content
from tracker.domain.types import (
    BandEstimate,
    CapabilityView,
    Confidence,
    Consequences,
    LeafRef,
    PlayerState,
    RoadmapSelection,
)
from tracker.gear.setup import GearProgress, gear_progress


class ObservationAge(Enum):
    """How old the account observations are, in buckets a sentence can use.

    §21.2 excludes clock reads from its context entirely, because a timestamp there would
    invalidate every stored note on every sync whether or not anything the advice depended on
    had moved. §22 hashes a *conversation's* prefix rather than a cached answer, so the cost
    of admitting time here is one re-cache per bucket transition — and what it buys is the
    fact the advisor most needs in order to hedge honestly, since advice given on month-old
    levels ought to say so.

    Buckets rather than a timestamp for the same reason: five values transition rarely, where
    a rendered datetime would differ on every single turn.
    """

    TODAY = "today"
    THIS_WEEK = "this week"
    THIS_MONTH = "this month"
    OLDER = "older than a month"
    NEVER = "never"


@dataclass(frozen=True, slots=True)
class RankedTask:
    """One entry of the latest persisted run, in the shape §22.2 and §22.4 both read.

    Carries the engine's own ``reason`` verbatim. §9.5 forbids authored justification and
    computes that sentence from factor headroom; relaying it unchanged is the only way the
    model can refer to the tracker's reasoning without inventing a paraphrase of it.
    """

    candidate_id: str
    name: str
    kind: str
    rank: int
    score: float
    reason: str
    blocked: bool
    hours: float | None = None
    gp: int | None = None
    confidence: str = "unknown"
    blockers: tuple[LeafRef, ...] = ()
    bands: tuple[BandEstimate, ...] = ()
    consequences: Consequences = field(default_factory=Consequences)


@dataclass(frozen=True, slots=True)
class PriceFact:
    """One cached price, with the two timestamps §6.8 insists on keeping apart.

    ``fetched_at`` is when the application called the API; ``trade_at`` is when the trade it
    reports actually happened. D10 exists because collapsing them lets a fresh retrieval of
    stale market data pass for a current price, and a tool that reported only one of them
    would reintroduce exactly that.

    ``price_gp`` is ``None`` when the row exists but carries no usable figure — which is not
    the same as the item being absent from the cache, and §22.4's tool renders the two
    differently.
    """

    item_id: int
    name: str
    price_gp: int | None
    trade_at: datetime | None
    fetched_at: datetime
    provider: str


@dataclass(frozen=True, slots=True)
class AdvisorSnapshot:
    """Everything §22 is allowed to know, before anyone asks a question.

    Deliberately holds :class:`~tracker.content.loader.Content` itself rather than a
    pre-flattened copy: the tool catalogue reaches arbitrary corners of the corpus — one
    candidate's requirement tree, one skill's methods, one quest's name — and pre-flattening
    all of it would mean building the whole corpus twice per turn to serve the handful of
    lookups a question actually makes.
    """

    state: PlayerState
    content: Content
    capabilities: tuple[CapabilityView, ...] = ()
    roadmaps: RoadmapSelection = field(default_factory=RoadmapSelection)
    ranked: tuple[RankedTask, ...] = ()
    blocked: tuple[RankedTask, ...] = ()
    stale_practice: tuple[tuple[str, str], ...] = ()
    prices: Mapping[int, PriceFact] = field(default_factory=dict)
    observed_age: ObservationAge = ObservationAge.NEVER
    gear: GearProgress = field(default_factory=GearProgress)
    """§23.4's computed setup, and the reason it is a *snapshot field* (D17).

    Computing it here rather than in a tool handler is what keeps §22.4's dispatch "a
    pure function of the frozen snapshot and the call". By the time any tool runs this is
    already-computed state, which is the category D15 permits a tool to project; a handler
    that evaluated requirement trees against model-chosen arguments would instead be an
    estimator on demand, which D15 forbids outright.
    """


def build_advisor_snapshot(
    *,
    state: PlayerState,
    content: Content,
    capabilities: Sequence[CapabilityView] = (),
    roadmaps: RoadmapSelection | None = None,
    ranked: Sequence[RankedTask] = (),
    blocked: Sequence[RankedTask] = (),
    stale_practice: Sequence[tuple[str, str]] = (),
    prices: Mapping[int, PriceFact] | None = None,
    now: datetime,
) -> AdvisorSnapshot:
    """Freeze and order one turn's inputs.

    ``now`` is passed rather than read so this stays pure, and it is used for exactly one
    thing: bucketing :attr:`PlayerState.last_sync_at` into an :class:`ObservationAge`.

    Ranked entries are sorted by rank and blocked entries by score, both with the candidate id
    as a tiebreak. The tiebreak is not decoration: two entries at the same rank would
    otherwise render in whatever order the caller's query returned them, and §22.3's hash
    would move on a difference the account never made.
    """
    return AdvisorSnapshot(
        state=state,
        content=content,
        capabilities=tuple(sorted(capabilities, key=lambda view: view.capability_id)),
        roadmaps=roadmaps if roadmaps is not None else RoadmapSelection(),
        ranked=tuple(sorted(ranked, key=lambda task: (task.rank, task.candidate_id))),
        blocked=tuple(sorted(blocked, key=lambda task: (-task.score, task.candidate_id))),
        stale_practice=tuple(sorted(stale_practice)),
        prices=dict(sorted((prices or {}).items())),
        observed_age=observation_age(state.last_sync_at, now=now),
        # Pricing keys on `item_id` alone and never the ownership union (§10.5), which is
        # exactly what `PriceFact` is keyed by, so the mapping passes straight through.
        gear=gear_progress(
            state,
            content,
            prices={item_id: fact.price_gp for item_id, fact in (prices or {}).items()},
        ),
    )


def observation_age(last_sync_at: datetime | None, *, now: datetime) -> ObservationAge:
    """Bucket the last sync into :class:`ObservationAge`.

    A sync stamped in the future buckets as ``TODAY`` rather than raising. Clock skew between
    the plugin and the host is real and entirely outside this application's control, and
    refusing to answer a question over it would be a poor trade for a hedge nobody needs.
    """
    if last_sync_at is None:
        return ObservationAge.NEVER
    elapsed = now - last_sync_at
    if elapsed < timedelta(days=1):
        return ObservationAge.TODAY
    if elapsed < timedelta(days=7):
        return ObservationAge.THIS_WEEK
    if elapsed < timedelta(days=30):
        return ObservationAge.THIS_MONTH
    return ObservationAge.OLDER


def confidence_word(confidence: Confidence | None) -> str:
    """Render §8.4's confidence as the lowercase word the prompt uses.

    ``None`` renders *unknown* rather than defaulting to a level, for §22.2's three-valued
    rule: an estimate with no confidence attached has not been assessed, and calling that
    *low* would assert an assessment nobody made.
    """
    return "unknown" if confidence is None else confidence.name.lower()
