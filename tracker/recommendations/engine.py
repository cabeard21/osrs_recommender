"""``recommend()`` — the pure entry point §16.1 mandates.

    recommend(state, selection, content, profile, incumbent) -> list[Recommendation]

Everything the answer depends on arrives as an argument. No database access, no HTTP, no
``datetime.now()``: §16.1 requires this so the golden corpus can pin a scenario and get the
same ranking every time, and §9.9's ``incumbent`` is a parameter for exactly that reason —
letting the engine fetch its own previous snapshot would reintroduce the dependency the
signature exists to remove.

Two keyword-only arguments extend §16.1's list, and both are inputs the SDD requires
elsewhere. ``now`` is the clock §6.6's freshness policy and §8.4's price confidence both
measure against; ``prices`` is the resolved map §8.3 says the estimator *"never fetches"*.
Keeping them keyword-only leaves the positional signature byte-identical to §16.1's, so a
caller written from the SDD still compiles.

The pipeline
------------

1. **Blend** the active roadmaps into one capability-weight map (§9.3).
2. **Derive** each candidate's factors (§10.6) — dropping the completed, gating out the
   blocked (§16.2).
3. **Synthesize** one composite refresher per decayed practice group (§9.8).
4. **Score** everything through the same weighted geometric mean (§9.4, §9.5).
5. **Rank**, then apply §9.9's hysteresis, then §9.8's list policy, then cut the primary
   list to ``max_primary_entries`` (§9.7).

The cut is last for the same reason the list policy is late: it operates on an ordering it
cannot influence. Truncating earlier — or filtering candidates before scoring — would let
list length decide what gets ranked, which is the one thing §10.6 keeps content from doing.

Steps 4 and 5 treat progression candidates and refreshers identically, which is what keeps
G10 from needing a special case: a refresher competes on its merits and is *then* capped at
one per list, rather than being suppressed by a rule that hides how well it actually did.

Leverage across two kinds of candidate
--------------------------------------

§10.6 defines ``leverage`` as the normalized count of capabilities a candidate's facts would
flip to ``unlocked``. A refresher grants no facts and would score zero forever — not merely
harsh but wrong, since restoring decayed practice is precisely what moves a capability from
*"unlocked but not today"* back to *"recommended now"* (§4.4). Refreshers are therefore
credited with the count of capabilities whose **``recommended_now``** would flip: the
readiness-layer twin of the status flip, normalized against the same maximum so the two
kinds stay comparable. Recorded as an open amendment candidate in ``plans/`` — the SDD does
not say, and the code ships a documented choice rather than an invention.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from tracker.content.loader import Content
from tracker.content.requirements import Requirement
from tracker.content.schema import Candidate, ScoringProfile
from tracker.domain.candidates import (
    MethodUnlockWinner,
    advances_value,
    blocked,
    completed,
    effective_capability_weights,
    gate_value,
    leverage,
    method_unlock_scores,
    proximity,
    unlock_flips,
)
from tracker.domain.consequences import consequences_for
from tracker.domain.types import (
    CandidateKind,
    Confidence,
    Estimate,
    IncumbentRecommendation,
    MilestoneState,
    PlayerState,
    Recommendation,
    RoadmapSelection,
    Tri,
)
from tracker.estimation.prices import PriceRecord
from tracker.estimation.xp_table import xp_for_level
from tracker.progression.engine import compute_capability_states
from tracker.progression.evaluate import EvalResult, Evaluator
from tracker.recommendations.details import leverage_detail, progression_details
from tracker.recommendations.facts import EstimateOracle, GateOracle, LeverageOracle, _Worlds
from tracker.recommendations.hysteresis import apply_hysteresis
from tracker.recommendations.reasons import reason
from tracker.recommendations.refreshers import (
    PracticeCandidate,
    enforce_list_policy,
    practice_candidates,
)
from tracker.recommendations.scoring import cost_decay, effort_decay, kappa_for, score

#: A refresher's cost. §10.4 says a practice session buys nothing, and unlike ``hours`` this
#: needs no authored field: zero is a *fact* about refreshers, where zero hours would have
#: been a missing measurement (A8).
_PRACTICE_GP = 0


@dataclass(frozen=True, slots=True)
class RecommendationRun:
    """Everything one run produced, for callers needing more than the primary list.

    §16.1 fixes ``recommend()``'s return type at ``list[Recommendation]``, and §16.2 asks
    for two things that list cannot hold: blocked candidates *"excluded and surfaced
    separately"*, and the refreshers §9.8 routes to the Practice freshness view. Both fall
    out of the same scoring pass, and recomputing them in the UI would be a second
    implementation of the ranking. :func:`recommend` returns ``primary``; Step 9's pipeline
    and Step 11's views take the whole run.
    """

    primary: tuple[Recommendation, ...] = ()
    deferred_refreshers: tuple[Recommendation, ...] = ()
    blocked: tuple[Recommendation, ...] = ()


def recommend(
    state: PlayerState,
    selection: RoadmapSelection,
    content: Content,
    profile: ScoringProfile,
    incumbent: IncumbentRecommendation | None = None,
    *,
    prices: Mapping[int, PriceRecord] | None = None,
    now: datetime,
) -> list[Recommendation]:
    """§16.1's entry point: the ranked primary list, best first."""
    return list(
        recommend_run(state, selection, content, profile, incumbent, prices=prices, now=now).primary
    )


def recommend_run(
    state: PlayerState,
    selection: RoadmapSelection,
    content: Content,
    profile: ScoringProfile,
    incumbent: IncumbentRecommendation | None = None,
    *,
    prices: Mapping[int, PriceRecord] | None = None,
    now: datetime,
) -> RecommendationRun:
    """The full result of one scoring pass. See :class:`RecommendationRun`."""
    # One set of counterfactual worlds, shared by the pass that sizes them and the pass that
    # explains them. §9.10's explanation therefore builds none of its own — every world it
    # asks about was already built to answer A30.
    worlds = _Worlds(state, content)
    run = _Run(
        state=state,
        content=content,
        profile=profile,
        now=now,
        prices=prices or {},
        weights=effective_capability_weights(selection, content),
        evaluator=Evaluator(state, content),
        oracle=LeverageOracle(state, content, now),
        estimates=EstimateOracle(state, content, prices or {}, now, worlds=worlds),
        gates=GateOracle(worlds),
    )

    entries, context = _actionable(run)
    ranked = sorted(entries, key=lambda entry: (-entry.recommendation.score, entry.id))
    ordered = apply_hysteresis([entry.recommendation for entry in ranked], incumbent)
    primary, deferred = enforce_list_policy(ordered, profile)
    primary = primary[: profile.max_primary_entries]

    # §9.10's explanation, derived **after** the ranking is fixed and applied only to the
    # entries that ship. Two consequences of that placement, both deliberate. It cannot
    # influence what it describes: `_explain` reads the factors and returns a copy, so no
    # ordering input exists for it to touch. And it costs what the visible list costs rather
    # than what the corpus costs — 365 candidates are scored, a dozen are explained, and the
    # counterfactual worlds it asks about were all built by the A30 pass above.
    return RecommendationRun(
        primary=tuple(_explain(entry, run, context) for entry in primary),
        deferred_refreshers=tuple(_explain(entry, run, context) for entry in deferred),
        blocked=_blocked_entries(run),
    )


# ---------------------------------------------------------------------------
# The run's shared inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Run:
    """One invocation's inputs, plus the two caches that make it affordable.

    ``evaluator`` memoizes requirement evaluation across every candidate, so a
    ``capability:`` prerequisite shared by six gates is walked once rather than six times;
    ``oracle`` does the same for the counterfactual capability states ``leverage`` needs,
    and ``estimates`` for the §8 sizings ``method_unlock`` compares (A30) — which is where
    the memo matters most, since that factor asks an O(n²) question. All three are pinned to
    ``state`` and ``content`` and must not outlive this run.
    """

    state: PlayerState
    content: Content
    profile: ScoringProfile
    now: datetime
    prices: Mapping[int, PriceRecord]
    weights: Mapping[str, float]
    evaluator: Evaluator
    oracle: LeverageOracle
    estimates: EstimateOracle
    gates: GateOracle
    """§9.10's *"what is still in the way"*, sharing ``estimates``' counterfactual worlds."""

    def evaluate(
        self, requirement: Requirement, _state: PlayerState, _content: Content
    ) -> EvalResult:
        """Adapter matching :class:`~tracker.domain.candidates.RequirementEvaluator`.

        The protocol passes ``(requirement, state, content)`` per call because a derivation
        must not assume its evaluator is pinned to one account; :class:`Evaluator` binds the
        pair at construction because that is what makes its memo table sound. The two are
        ignored rather than checked here, since every caller in this module passes back the
        very objects ``self`` was built from.
        """
        return self.evaluator.evaluate(requirement)


@dataclass(frozen=True, slots=True)
class _Entry:
    """A scored candidate and the id used to break ties deterministically."""

    id: str
    recommendation: Recommendation


@dataclass(frozen=True, slots=True)
class _ScoringContext:
    """What the scoring pass learned that §9.10's explanation would otherwise recompute.

    ``unlock_names`` and ``winners`` are the identities :func:`unlock_flips` and
    :func:`method_unlock_detail` retained on the way to the two factors that discard them.
    Carrying them forward is not an optimization so much as a correctness rule: A30's pass is
    O(n²), and running it a second time against a warmed estimate cache could disagree with
    the first about which candidate won a tie — leaving the *"Why"* line naming a grind the
    factor beside it was not computed from.

    ``open_candidates`` is likewise the pool ``method_unlock`` measured against, blocked
    entries included, so *"unblocks Y"* and *"speeds up Y"* cannot disagree about what exists.
    """

    open_candidates: tuple[Candidate, ...]
    unlock_names: Mapping[str, tuple[str, ...]]
    winners: Mapping[str, MethodUnlockWinner | None]


# ---------------------------------------------------------------------------
# Candidate selection (§16.2)
# ---------------------------------------------------------------------------


def _actionable(run: _Run) -> tuple[tuple[_Entry, ...], _ScoringContext]:
    """Score every candidate that may rank: not complete, not blocked (§16.2).

    ``leverage`` is normalized across this set and no other (§10.6), so both kinds are
    gathered before anything is scored. Normalizing per kind would let a refresher that
    unblocks one capability score the same 1.0 as a quest that unblocks three, purely
    because refreshers had been counted among themselves.

    ``method_unlock`` (A30) is normalized across the same set, but measured against a
    **wider** one: ``open`` includes the blocked candidates, because a blocked candidate's
    hours are perfectly computable and unblocking a 113-hour grind while making it a 16-hour
    one is precisely the effect the factor exists to see.
    """
    open_candidates = [
        candidate
        for candidate in run.content.candidates.values()
        if not completed(candidate, run.state, run.content, run.evaluate)
    ]
    progression = [
        candidate
        for candidate in open_candidates
        if not blocked(candidate, run.state, run.content, run.evaluate)
    ]
    practice = practice_candidates(run.state, run.content, run.profile, run.now)

    # The names come from the same walk as the count (§9.10); see :func:`unlock_flips` on
    # why counting in a second loop is how the two come to disagree.
    unlock_names = {
        candidate.id: unlock_flips(candidate, run.state, run.content, run.oracle)
        for candidate in progression
    }
    unlock_counts: dict[str, int] = {
        candidate_id: len(names) for candidate_id, names in unlock_names.items()
    }
    unlock_counts.update({entry.id: _practice_unlocks(entry, run) for entry in practice})
    largest = max(unlock_counts.values(), default=0)

    methods = method_unlock_scores(progression, open_candidates, run.estimates)
    unlocked_methods = methods.normalized

    entries = [
        _Entry(
            candidate.id,
            _score_progression(candidate, run, unlock_counts, largest, unlocked_methods),
        )
        for candidate in progression
    ]
    entries.extend(
        _Entry(entry.id, _score_practice(entry, run, unlock_counts, largest)) for entry in practice
    )
    context = _ScoringContext(
        open_candidates=tuple(open_candidates),
        unlock_names=unlock_names,
        winners=methods.winners,
    )
    return tuple(entries), context


def _blocked_entries(run: _Run) -> tuple[Recommendation, ...]:
    """Blocked candidates, unscored, for §16.2's *"surfaced separately"*.

    Deliberately unscored. A blocked candidate's ``readiness`` gate is 0, so §9.4 would
    return the ε-floored score of something nobody can act on — a number that invites
    ranking blocked work against actionable work, the exact comparison the gate exists to
    refuse.

    It does carry ``blockers``. An earlier version of this docstring said the UI could take
    them from the capability views instead; that was wrong once the corpus grew past the
    handful of candidates whose gates a capability also named. ``complete_lunar_diplomacy``
    is blocked by four ``quest:`` leaves no capability mentions, so without this the page
    could name the goal and nothing about how to reach it.

    A candidate whose gate is **unknown** is not here: G3 and §16.2 both say an unknown gate
    is *"sync this"*, not blocked, so it stays in the actionable list carrying
    ``unknown_gate``.
    """
    entries: list[Recommendation] = []
    for candidate in sorted(run.content.candidates.values(), key=lambda entry: entry.id):
        if candidate.requires is None:
            # No gate, so nothing to be blocked by — `blocked` agrees, and the explicit
            # check is what lets the evaluate call below take a non-optional tree.
            continue
        if not blocked(candidate, run.state, run.content, run.evaluate):
            continue
        # `blocked` already evaluated this tree; the evaluator memoizes per run, so asking
        # again is a cache read rather than a second walk.
        gate = run.evaluate(candidate.requires, run.state, run.content)
        entries.append(
            Recommendation(
                candidate_id=candidate.id,
                name=candidate.name,
                kind=candidate.kind,
                score=0.0,
                blocked=True,
                blockers=gate.blockers,
            )
        )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Scoring one progression candidate (§9.4)
# ---------------------------------------------------------------------------


def _score_progression(
    candidate: Candidate,
    run: _Run,
    unlock_counts: Mapping[str, int],
    largest: int,
    unlocked_methods: Mapping[str, float],
) -> Recommendation:
    sized = run.estimates.estimate(candidate)
    kappa = kappa_for(run.state.gp_sensitivity, run.profile)
    values = {
        "pvp_value": advances_value(candidate.advances, run.weights),
        "leverage": leverage(unlock_counts[candidate.id], largest),
        "method_unlock": unlocked_methods[candidate.id],
        "proximity": proximity(candidate, run.state, run.content, run.evaluate, xp_for_level),
        "effort_decay": effort_decay(sized.hours, run.profile),
        "cost_decay": cost_decay(sized.gp, kappa),
    }
    raw, factors = score(values, run.profile)

    return Recommendation(
        candidate_id=candidate.id,
        name=candidate.name,
        kind=candidate.kind,
        score=raw,
        factors=factors,
        # A generic reason, replaced by `_explain` for the entries that ship. Every scored
        # entry carries one so that nothing downstream has to cope with an unexplained
        # recommendation, and so the fallback is visible rather than implied.
        reason=reason(
            factors, run.profile, details=leverage_detail((), unlock_counts[candidate.id])
        ),
        estimate=sized,
        unknown_gate=gate_value(candidate, run.state, run.content, run.evaluate) is Tri.UNKNOWN,
    )


# ---------------------------------------------------------------------------
# Scoring one composite refresher (§9.8)
# ---------------------------------------------------------------------------


def _score_practice(
    entry: PracticeCandidate, run: _Run, unlock_counts: Mapping[str, int], largest: int
) -> Recommendation:
    """Score a refresher on the same six factors, with three substitutions.

    ``proximity`` carries §9.8's ``group_urgency`` — see
    :mod:`tracker.recommendations.refreshers` for why that is the factor it belongs in — and
    ``cost_decay`` is computed from a real zero rather than from an absent figure, which is
    the distinction A8 turns on: a refresher's cost is *known* to be nothing, while its hours
    are only knowable because §10.4 makes authoring them mandatory.

    ``method_unlock`` is a **real zero** and takes no readiness-layer twin. A30 measures the
    hours a candidate's ``grants_facts`` would remove from another candidate's estimate; a
    refresher grants no facts and §8 sizes nothing from practice freshness, so there is
    nothing to reduce. Unlike ``leverage`` — where A29? had to reinterpret the count, because
    a permanent zero there would have been *wrong* — zero here is simply the answer, and the
    ε floor treats it exactly as it treats a quest that unlocks no faster method.
    """
    kappa = kappa_for(run.state.gp_sensitivity, run.profile)
    sized = Estimate(hours=entry.hours, gp=_PRACTICE_GP, confidence=Confidence.HIGH)
    values = {
        "pvp_value": advances_value(entry.advances, run.weights),
        "leverage": leverage(unlock_counts[entry.id], largest),
        "method_unlock": 0.0,
        "proximity": entry.urgency,
        "effort_decay": effort_decay(entry.hours, run.profile),
        "cost_decay": cost_decay(_PRACTICE_GP, kappa),
    }
    raw, factors = score(values, run.profile)

    return Recommendation(
        candidate_id=entry.id,
        name=entry.name,
        kind=CandidateKind.PRACTICE,
        score=raw,
        factors=factors,
        reason=reason(
            factors,
            run.profile,
            details={
                **leverage_detail((), unlock_counts[entry.id]),
                "proximity": _urgency_phrase(entry.urgency),
            },
        ),
        estimate=sized,
        practice_members=entry.members,
    )


def _practice_unlocks(entry: PracticeCandidate, run: _Run) -> int:
    """Capabilities whose ``recommended_now`` a completed session would flip to true.

    The readiness-layer twin of §10.6's status flip. Measured by re-running the progression
    engine against a state in which the session's members were practiced *now* — exactly
    what §9.8's *"mark session complete"* action will write — so the count promises only
    what the button delivers.

    Capabilities already recommended are excluded, for §10.6's reason one layer up: a
    refresher has not made recommendable what was recommendable anyway.
    """
    before = compute_capability_states(run.state, run.content, run.profile, run.now)
    after = compute_capability_states(
        _practiced_now(run.state, entry.members, run.now), run.content, run.profile, run.now
    )
    return sum(
        1
        for capability_id, view in after.items()
        if view.recommended_now and not before[capability_id].recommended_now
    )


def _practiced_now(state: PlayerState, members: Sequence[str], now: datetime) -> PlayerState:
    """The player's facts with one session's milestones freshly practiced.

    ``achieved`` is untouched — a session refreshes practice, it does not attest to
    competence (G7) — and this state is a hypothetical besides. Only ``last_practiced_at``
    moves, which is the single field §6.6's freshness policy reads.
    """
    refreshed = dict(state.milestones)
    for key in members:
        existing = refreshed.get(key)
        if existing is None:  # pragma: no cover — members come from achieved milestones
            continue
        refreshed[key] = MilestoneState(
            key=existing.key,
            achieved=existing.achieved,
            attested=existing.attested,
            kind=existing.kind,
            class_=existing.class_,
            value=existing.value,
            last_practiced_at=now,
        )
    return PlayerState(
        player_id=state.player_id,
        skills=state.skills,
        unlocks=state.unlocks,
        quests=state.quests,
        observed_items=state.observed_items,
        container_scans=state.container_scans,
        milestones=refreshed,
        combat_level=state.combat_level,
        quest_points=state.quest_points,
        gp_sensitivity=state.gp_sensitivity,
        last_sync_at=state.last_sync_at,
    )


# ---------------------------------------------------------------------------
# Reason detail (§9.10)
# ---------------------------------------------------------------------------


def _explain(recommendation: Recommendation, run: _Run, context: _ScoringContext) -> Recommendation:
    """Attach §9.10's consequences, and re-render the *"Why"* line now that names are known.

    **Nothing here can change a ranking.** It receives an entry whose score, factors and
    position are already decided, and returns a copy differing only in ``consequences`` and
    ``reason``. The re-rendered reason is :func:`reason` over the *same* ``factors`` mapping
    the scorer produced — only the words are substituted, never the credits — so the sentence
    stays a decomposition of the ranking rather than a commentary beside it.

    A refresher is explained differently and less. It grants no facts, so it unblocks no
    candidate, dents no capability's requirements and accelerates nothing: every consequence
    would be empty by construction. What it does have is §9.8's urgency, which is already the
    ``proximity`` phrase it has always carried.
    """
    if recommendation.kind is CandidateKind.PRACTICE:
        return recommendation

    candidate = run.content.candidates.get(recommendation.candidate_id)
    if candidate is None:  # pragma: no cover — every scored entry came from this corpus
        return recommendation

    consequences = consequences_for(
        candidate,
        content=run.content,
        weights=run.weights,
        unlocked_capability_ids=context.unlock_names.get(candidate.id, ()),
        accelerated=context.winners.get(candidate.id),
        others=context.open_candidates,
        outstanding_gate=run.gates,
        outstanding_capability_gate=run.gates.capability,
    )
    return replace(
        recommendation,
        consequences=consequences,
        reason=reason(
            recommendation.factors,
            run.profile,
            details=progression_details(
                consequences, len(context.unlock_names.get(candidate.id, ()))
            ),
        ),
    )


def _urgency_phrase(urgency: float) -> str:
    """What ``proximity`` means for a refresher, said in the vocabulary of practice."""
    if urgency >= 0.70:
        return "practice has badly decayed"
    if urgency >= 0.40:
        return "practice is going stale"
    return "practice is still fresh"
