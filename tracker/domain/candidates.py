"""The five candidate factor derivations of §10.6, as pure functions.

§10.6 and D11: *"Every factor in §9.4 derives from the fields above. **None is authored
directly**, so no content file can assert its own priority."* This module is where that
promise is kept — ``pvp_value``, ``leverage``, ``proximity``, ``completed`` and the
``blocked`` gate are computed here from :class:`~tracker.content.schema.Candidate` fields
and player facts, and nowhere else.

**No scoring lives here.** The §9.4 weighted geometric mean, the ε floor and the ranking
are Step 6's; this module only produces the factors it multiplies. Keeping the two apart
is what lets §16.2's invariants ("a completed candidate never ranks") be tested against a
derivation rather than inferred from a score.

Dependency injection at two seams
---------------------------------

Three of the five derivations need three-valued requirement evaluation (§9.1) and one
needs capability status, both of which live in ``tracker.progression``. Rather than
import that package, this module declares the *shape* it needs as protocols and takes the
implementation as an argument. Two reasons, in order of importance:

1. The engine is the thing whose behaviour these derivations must not silently depend on.
   Injecting it means every rule below is testable against a stub that makes the
   interesting case — an ``unknown`` gate — trivial to construct.
2. ``tracker.progression`` builds on this package, so importing it here would close a
   cycle.

The concrete evaluator satisfies :class:`EvalOutcome` and :class:`RequirementEvaluator`
**structurally**; neither package imports the other.

Why this module may import ``tracker.content`` when ``tracker.domain.types`` may not:
``tracker.content`` imports ``tracker.domain.types`` and never imports this module, so the
dependency stays one-way. A candidate derivation cannot be expressed without the
``Candidate`` model and the requirement AST, both of which are content.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from tracker.content.loader import Content
from tracker.content.requirements import Requirement, SkillLeaf, iter_leaves
from tracker.content.schema import Candidate
from tracker.domain.types import CandidateKind, PlayerState, RoadmapSelection, Tri

# ---------------------------------------------------------------------------
# The injected seams
# ---------------------------------------------------------------------------


class EvalOutcome(Protocol):
    """What a requirement evaluation reports back (§9.1, §6.9).

    ``satisfied_leaves`` and ``total_leaves`` are the two halves of ``unlock_fraction``:
    §6.9 requires unknown leaves to sit in the **denominator** without being credited, so
    the count of satisfied leaves cannot be reconstructed from ``value`` alone.

    **Members are read-only properties, not bare attributes**, and that distinction is
    load-bearing. A protocol declaring ``value: Tri`` demands read *and write* access, so
    the frozen dataclass the evaluator actually returns would not satisfy it — mypy
    rejects a read-only attribute against a mutable protocol member. Since nothing here
    ever assigns to an outcome, read-only is both what we need and what the
    implementation can provide.
    """

    @property
    def value(self) -> Tri: ...

    @property
    def satisfied_leaves(self) -> int: ...

    @property
    def total_leaves(self) -> int: ...


class RequirementEvaluator(Protocol):
    """Three-valued evaluation of one requirement tree against the player's facts.

    The parameters are **positional-only** (note the ``/``). A protocol whose ``__call__``
    names its parameters also demands that callers may pass them by keyword, which
    excludes every plain ``Callable[...]`` — including the stubs these derivations are
    tested against. Positional-only keeps the contract to what it is actually about: three
    arguments in this order.
    """

    def __call__(
        self, requirement: Requirement, state: PlayerState, content: Content, /
    ) -> EvalOutcome: ...


#: *"Would this capability's status become ``unlocked`` if these facts were true?"*
#:
#: A plain ``Callable`` rather than a ``Protocol`` deliberately: its parameters are
#: matched positionally, so the implementation Step 4 supplies is free to name them
#: whatever reads best there without breaking structural compatibility here.
#:
#: The predicate answers *flip*, not *state*: a capability already unlocked has not been
#: unlocked **by** this candidate and must not be counted (§10.6 — "whose ``status``
#: would **become** ``unlocked``").
UnlocksAfterFacts = Callable[[str, Requirement, PlayerState, Content], bool]

#: ``xp_for_level(level) -> total xp at that level``. The OSRS table is Step 5's (§8.2);
#: taking it as a parameter keeps this module free of a 99-entry constant and lets tests
#: substitute a small synthetic curve.
XpForLevel = Callable[[int], int]


# ---------------------------------------------------------------------------
# §9.3 — the effective capability-weight map
# ---------------------------------------------------------------------------


def effective_capability_weights(
    selection: RoadmapSelection, content: Content
) -> Mapping[str, float]:
    """Collapse every active roadmap into **one** capability-weight map (§9.3).

    ``effective_weight(c) = Σ_r selection_weight(r) × roadmap_capability_weight(r, c)``

    Because the selection weights are normalized to sum to 1 and each roadmap's weights
    lie in [0,1], this is a **convex combination** — automatically in [0,1], with no
    second normalization pass — which is what dissolves the double-counting problem: a
    capability in two roadmaps blends rather than accumulates (D3).

    A selected roadmap that is not in ``content`` contributes nothing but keeps its share
    of the normalization, so the result stays a convex combination and can only be
    conservative. Dropping it from the denominator instead would silently *inflate* every
    remaining roadmap the moment content was removed.
    """
    weights: dict[str, float] = {}
    for roadmap_id, selection_weight in selection.normalized().items():
        roadmap = content.roadmaps.get(roadmap_id)
        if roadmap is None:
            continue
        for capability_id, capability_weight in roadmap.capabilities.items():
            weights[capability_id] = (
                weights.get(capability_id, 0.0) + selection_weight * capability_weight
            )
    return weights


# ---------------------------------------------------------------------------
# pvp_value (§9.3, A2, D11)
# ---------------------------------------------------------------------------


def pvp_value(candidate: Candidate, effective_weights: Mapping[str, float]) -> float:
    """``max_c effective_weight(c) × advances(cand, c)`` (§9.3).

    **The order of operations is load-bearing.** ``effective_weights`` must already be
    the blended map from :func:`effective_capability_weights`; taking a maximum per
    roadmap and blending afterwards gives different answers for candidates advancing more
    than one capability, because ``max`` and convex combination do not commute. Only the
    blend-then-max form reproduces §9.3's worked table (0.90 and 0.375).

    **Maximum, never sum** (D11). Summation would let a candidate advancing four
    capabilities weakly outrank one advancing a single capability strongly, making
    breadth a substitute for relevance — the same failure §9.8 rejects for refresher
    group size.

    A capability the map does not weight contributes ``0``: it is not on any active
    roadmap, so advancing it is worth nothing *to this player*, which is not the same as
    the candidate being invalid. Validation (§10.7) is what rejects a target no roadmap
    could ever weight.
    """
    return advances_value(candidate.advances, effective_weights)


def advances_value(advances: Mapping[str, float], effective_weights: Mapping[str, float]) -> float:
    """:func:`pvp_value` over a bare ``advances`` map.

    Extracted because §9.8's composite refreshers are **not** ``Candidate`` objects — a
    refresher's completion predicate would evaluate ``satisfied`` on the very run it was
    most needed, see :mod:`tracker.recommendations.refreshers` — and yet §9.3's worked table
    scores one: *"Practice vengeance timing"* at 0.375. Two candidate shapes, one relevance
    rule. A second implementation for the second shape is how the maximum quietly becomes a
    sum along one of the two paths.
    """
    if not advances:
        return 0.0
    return max(
        effective_weights.get(capability_id, 0.0) * contribution
        for capability_id, contribution in advances.items()
    )


# ---------------------------------------------------------------------------
# leverage (§9.4, §10.6)
# ---------------------------------------------------------------------------


def unlock_flip_count(
    candidate: Candidate,
    state: PlayerState,
    content: Content,
    unlocks_after_facts: UnlocksAfterFacts,
) -> int:
    """How many capabilities ``grants_facts`` would flip to ``unlocked`` (§10.6).

    A candidate declaring no ``grants_facts`` changes nothing objective, so it unlocks
    nothing — zero, never "unknown". ``leverage`` is a relevance factor, not a status.
    """
    if candidate.grants_facts is None:
        return 0
    return sum(
        1
        for capability_id in content.capabilities
        if unlocks_after_facts(capability_id, candidate.grants_facts, state, content)
    )


def leverage(unlock_count: int, max_unlock_count: int) -> float:
    """Normalize an unlock count by the largest in the current candidate set (§10.6).

    Normalizing against the candidate set rather than against the corpus is what makes
    the factor comparative: the best available candidate scores ``1.0`` whether it
    unlocks one capability or six, so a sparse corpus does not depress every score.

    When nothing in the set unlocks anything the value is ``0`` for everyone. That is
    uniform, so it cannot reorder the list, and §9.4's ε floor — applied by the scorer,
    not here — is what lifts the factor into ``(0,1]`` before the geometric mean sees it.
    Flooring here instead would hide a genuine zero behind a tuning constant.
    """
    if max_unlock_count <= 0:
        return 0.0
    return min(1.0, unlock_count / max_unlock_count)


def leverage_map(
    candidates: Iterable[Candidate],
    state: PlayerState,
    content: Content,
    unlocks_after_facts: UnlocksAfterFacts,
) -> Mapping[str, float]:
    """``leverage`` for a whole candidate set, which is the only scale it is defined on.

    Returned keyed by candidate id, so the caller cannot accidentally normalize one
    candidate's count against a maximum taken over a different set.
    """
    counts = {
        candidate.id: unlock_flip_count(candidate, state, content, unlocks_after_facts)
        for candidate in candidates
    }
    largest = max(counts.values(), default=0)
    return {candidate_id: leverage(count, largest) for candidate_id, count in counts.items()}


# ---------------------------------------------------------------------------
# proximity (§9.4, §10.6, A3)
# ---------------------------------------------------------------------------


def proximity(
    candidate: Candidate,
    state: PlayerState,
    content: Content,
    evaluate: RequirementEvaluator,
    xp_for_level: XpForLevel,
) -> float:
    """*"Closer is better"* — ``1 − remaining / total``, in [0,1] (§9.4, §10.6).

    Two derivations, one per §10.6's table:

    * ``kind: skill_training`` — ``1 − remaining_xp / span_xp`` against the XP curve.
    * every other kind — the ``unlock_fraction`` (§6.9) of the ``completion`` predicate.
      The same machinery, and it generalizes to candidates with no numeric target.

    ``xp_for_level`` is injected because the OSRS XP table is Step 5's (§8.2); tests pass
    a small synthetic curve.

    **What ``span_xp`` measures, and why.** §10.6 names a span but the schema declares no
    starting level — the *"87 →"* in ``Train Magic 87 → 94`` is prose in ``name``, not a
    field, and D11 forbids adding one that would let an author inflate a factor. Span is
    therefore the whole curve up to the target: ``proximity = current_xp / xp(target)``.
    The alternative — measuring from the level the player held when the candidate first
    appeared — is not a function of the player's current facts, so it would make this
    module impure and the factor unstable across syncs. The full-curve form keeps the
    §16.2 invariant that matters here: of two otherwise identical candidates the closer
    one ranks higher, and a distant target (99) scores below a near one (94) for the same
    account.
    """
    if candidate.kind is CandidateKind.SKILL_TRAINING:
        skill_proximity = _skill_training_proximity(candidate, state, xp_for_level)
        if skill_proximity is not None:
            return skill_proximity
        # A skill_training candidate whose completion names no skill is odd but not
        # invalid; fall through to the general form rather than inventing a number.

    outcome = evaluate(candidate.completion, state, content)
    if outcome.total_leaves <= 0:  # pragma: no cover — §10.7 rejects an empty completion
        return 0.0
    return outcome.satisfied_leaves / outcome.total_leaves


def _skill_training_proximity(
    candidate: Candidate, state: PlayerState, xp_for_level: XpForLevel
) -> float | None:
    """The XP-curve form, or ``None`` when ``completion`` names no skill.

    A completion predicate naming several skills takes the **minimum** proximity: the
    candidate is only as close as its most distant requirement, and averaging would let
    a nearly-done skill mask one barely started.
    """
    targets = [leaf for leaf in iter_leaves(candidate.completion) if isinstance(leaf, SkillLeaf)]
    if not targets:
        return None

    fractions: list[float] = []
    for leaf in targets:
        span_xp = xp_for_level(leaf.level)
        if span_xp <= 0:  # a level-1 target is already met by every account
            fractions.append(1.0)
            continue
        fractions.append(min(1.0, _current_xp(state, leaf.skill, xp_for_level) / span_xp))
    return min(fractions)


def _current_xp(state: PlayerState, skill_id: str, xp_for_level: XpForLevel) -> float:
    """Current XP in one skill, degrading gracefully rather than guessing upward.

    ``SkillSnapshot.xp`` is nullable and ``None`` means *unranked*, never ``0`` (G5), so
    the level is used as the floor instead. A skill never observed at all contributes
    ``0`` XP — proximity is a distance, and the honest distance to an unobserved skill is
    the whole way. The *unknown-ness* of that skill is carried by the completion
    predicate evaluating ``unknown``, not by this number.
    """
    snapshot = state.skills.get(skill_id)
    if snapshot is None:
        return 0.0
    if snapshot.xp is None:
        return float(xp_for_level(snapshot.level))
    return float(snapshot.xp)


# ---------------------------------------------------------------------------
# completed and the readiness gate (§16.2, G3)
# ---------------------------------------------------------------------------


def completed(
    candidate: Candidate, state: PlayerState, content: Content, evaluate: RequirementEvaluator
) -> bool:
    """``completion`` evaluates ``satisfied`` (§10.6).

    Only ``satisfied`` counts. An ``unknown`` completion means we have not observed
    whether the player already owns the Voidwaker — that is a reason to sync, not a
    reason to declare the candidate done, and treating it as done would hide the
    recommendation that would fix it.

    §16.2: *"a completed candidate never ranks"* — completion is tested **before**
    scoring, never approximated by giving completed candidates a low score. A returned
    ``bool`` rather than a ``Tri`` is the point: this is the exclusion decision itself.
    """
    return evaluate(candidate.completion, state, content).value is Tri.SATISFIED


def gate_value(
    candidate: Candidate, state: PlayerState, content: Content, evaluate: RequirementEvaluator
) -> Tri:
    """The three-valued verdict on ``requires`` — the primitive :func:`blocked` reads.

    A candidate with no gate is ``satisfied``: nothing stands in the way. It is never
    ``unknown``, because an absent requirement is a fact about the content, not a missing
    observation.

    Kept three-valued so the caller can tell blocked from unknown; ``Recommendation``
    carries both ``blocked`` and ``unknown_gate`` for exactly this reason (§9.10, §15).
    """
    if candidate.requires is None:
        return Tri.SATISFIED
    return evaluate(candidate.requires, state, content).value


def blocked(
    candidate: Candidate, state: PlayerState, content: Content, evaluate: RequirementEvaluator
) -> bool:
    """``requires`` evaluates ``unsatisfied`` — the §9.4 ``readiness`` gate is 0.

    **An ``unknown`` gate is not blocked** (§10.6, D11, G3). It is unknown, and belongs
    with the capability unknowns — *"sync this"*, not *"do this"* (§15). Collapsing
    unknown into blocked is the D8 error one layer out, and §16.2 lists it among the
    invariants with a plausible-looking wrong implementation: ``if gate is not
    Tri.SATISFIED`` passes every other test in the document and is wrong here.
    """
    return gate_value(candidate, state, content, evaluate) is Tri.UNSATISFIED
