"""§16.3's weight search: maximize pairwise agreement, then **stop and report**.

    python tools/tune_weights.py --report

Runs a grid search over §9.4's weights, τ and the three κ presets, subject to §9.6's
validation constraints, scoring each candidate profile by its **pairwise-agreement rate**
against ``tests/golden/scenarios/`` — and prints every disagreement with the reasoning the
corpus recorded for it.

**It never writes `content/scoring/profile.yaml`.** §16.3 step 5 — *"review every
disagreement manually; a disagreement is as likely to reveal a bad judgment as a bad
weight"* — is a human decision, and a tool that applied its own answer would have removed
the one step the procedure exists around. The proposed profile is printed for a person to
paste, together with what it costs and what it buys.

What is searched, and what is not
---------------------------------

**``pvp_value`` is pinned at 1.0 and is not a free parameter.** ``score = Π fᵢ ^ wᵢ`` and
``ln(score) = Σ wᵢ ln(fᵢ)``, so scaling *every* weight by a positive constant is a monotone
transform of the score: it changes no ordering, and §16.3 optimizes orderings. The weight
vector therefore has four degrees of freedom, not five, and searching the fifth would report
a family of numerically distinct profiles that all rank identically. Pinning §9.4's largest
factor as the numeraire also keeps the printed result readable against the shipped defaults.

``epsilon``, ``observation_aged_days`` and the ``refresher`` block are held at their authored
values. None of them is a §16.3 target: ε is a floor that exists so ``ln(0)`` cannot happen,
and the other two are freshness policy — tuning them against a *ranking* corpus would be
optimizing §6.6's semantics with a §9.4 objective.

``unknown_effort_hours`` tracks τ. §9.7 documents the default as equal to ``tau_hours`` for a
stated reason — an unsized candidate is charged exactly one effort scale, ``exp(−1)`` — and
letting the search separate them would let it discover that unsized candidates should be
charged nothing, which is A8's defect wearing a tuned number.

Why the search does not call ``recommend()`` in its inner loop
-------------------------------------------------------------

Every §9.4 factor except ``effort_decay`` and ``cost_decay`` is independent of the profile,
and those two are closed forms — ``exp(−hours/τ)`` and ``exp(−gp/κ)`` — over an ``Estimate``
that §8 computes without a profile at all. So the engine runs **once per scenario**, its
factor values and estimates are cached, and the inner loop is arithmetic. A full pass over
the grid re-scores the corpus a few hundred thousand times in under a minute.

The saving is real but the risk is obvious, so the winner is **re-verified against the real
engine** before anything is printed: :func:`verify` rebuilds a ``ScoringProfile``, calls
``recommend_run`` through the same loader the tests use, and asserts the agreement rate it
measures equals the one the surrogate reported. A mismatch aborts rather than prints.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:  # running as a script, not as an installed module
    sys.path.insert(0, str(REPO_ROOT))

from tests.golden.loader import Judgment, Scenario, corpus, evaluate  # noqa: E402
from tracker.content.loader import Content  # noqa: E402
from tracker.content.schema import KappaPresets, ScoringProfile, ScoringWeights  # noqa: E402
from tracker.recommendations.hysteresis import DISPLACEMENT_MARGIN  # noqa: E402
from tracker.recommendations.scoring import FACTOR_NAMES  # noqa: E402

#: §9.6's validation block, verbatim. Any κ the search proposes must satisfy these.
KAPPA_MIN = 1_000_000
KAPPA_MAX = 250_000_000

#: §9.6's authored presets — and, unlike every other number here, **not free to tune.**
#:
#: §9.6 publishes a worked table ("a 10M purchase reads 0.29 / 0.61 / 0.82 across the three
#: presets") that these three values are the unique solution to, and Step 6 carries a test
#: asserting it. The validation block below them permits any κ in [1M, 250M] with
#: ``high < normal < low``, so a search reading only the constraints will happily propose
#: κ_normal = 30M — which satisfies every constraint, improves agreement, and silently
#: falsifies a table the SDD prints for the user.
#:
#: The plan's rule decides it: *if tuning breaks a Step 4–6 invariant, the invariant wins.*
#: The search therefore runs twice — pinned, which is the proposal, and free, which is
#: reported as evidence about how much the pin costs.
SDD_KAPPA: dict[str, int] = {"high": 8_000_000, "normal": 20_000_000, "low": 50_000_000}

#: The four free weights. ``pvp_value`` is the numeraire — see the module docstring.
TUNED = ("leverage", "proximity", "effort_decay", "cost_decay")

GRID: dict[str, tuple[float, ...]] = {
    "leverage": (0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4),
    "proximity": (0.2, 0.4, 0.6, 0.8, 1.0, 1.2),
    "effort_decay": (0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4),
    "cost_decay": (0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0),
}
TAU_GRID: tuple[float, ...] = (5.0, 10.0, 15.0, 20.0, 30.0)
KAPPA_GRID: dict[str, tuple[int, ...]] = {
    "high": (4_000_000, 8_000_000, 12_000_000),
    "normal": (16_000_000, 20_000_000, 30_000_000),
    "low": (40_000_000, 50_000_000, 80_000_000),
}

QUICK_GRID: dict[str, tuple[float, ...]] = {
    "leverage": (0.4, 0.8, 1.2),
    "proximity": (0.2, 0.6, 1.0),
    "effort_decay": (0.4, 0.8, 1.2),
    "cost_decay": (0.1, 0.3, 0.7),
}


# ---------------------------------------------------------------------------
# The cached corpus (see the module docstring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    """One candidate's profile-independent §9.4 inputs, cached from a single engine run.

    ``hours`` and ``gp`` are ``None`` exactly where §8 could not size the candidate; the
    scorer charges one τ and one κ respectively, which is what
    :mod:`tracker.recommendations.scoring` does and what §9.7's ``unknown_effort_hours``
    authors.
    """

    candidate_id: str
    pvp_value: float
    leverage: float
    proximity: float
    hours: float | None
    gp: int | None


@dataclass(frozen=True, slots=True)
class ScenarioFacts:
    """Everything the inner loop needs about one scenario."""

    scenario: Scenario
    candidates: tuple[CandidateFacts, ...]
    kappa_key: str
    incumbent: str | None


@dataclass(frozen=True, slots=True)
class Profile:
    """One point in the search space, in the vocabulary §9.7 uses."""

    weights: dict[str, float]
    tau_hours: float
    kappa: dict[str, int]

    def as_scoring_profile(self, base: ScoringProfile) -> ScoringProfile:
        """The real :class:`ScoringProfile` this point denotes, for exact verification."""
        return base.model_copy(
            update={
                "tau_hours": self.tau_hours,
                "unknown_effort_hours": self.tau_hours,
                "kappa_gp": KappaPresets(**self.kappa),
                "weights": ScoringWeights(pvp_value=1.0, **self.weights),
            }
        )


def collect(content: Content, scenarios: Sequence[Scenario]) -> tuple[ScenarioFacts, ...]:
    """Run the engine once per scenario and keep what the profile cannot change."""
    facts: list[ScenarioFacts] = []
    for scenario in scenarios:
        outcome = evaluate(scenario, content, content.profile)
        candidates = tuple(
            CandidateFacts(
                candidate_id=entry.candidate_id,
                pvp_value=entry.factors["pvp_value"].value,
                leverage=entry.factors["leverage"].value,
                proximity=entry.factors["proximity"].value,
                hours=None if entry.estimate is None else entry.estimate.hours,
                gp=None if entry.estimate is None else entry.estimate.gp,
            )
            for entry in outcome.ranked
        )
        facts.append(
            ScenarioFacts(
                scenario=scenario,
                candidates=candidates,
                kappa_key=scenario.state.gp_sensitivity.value,
                incumbent=(None if scenario.incumbent is None else scenario.incumbent.candidate_id),
            )
        )
    return tuple(facts)


# ---------------------------------------------------------------------------
# Scoring one point in the search space
# ---------------------------------------------------------------------------


def rank(facts: ScenarioFacts, point: Profile, epsilon: float) -> tuple[str, ...]:
    """The ranking one profile produces for one scenario, §9.9 included.

    Reproduces :func:`tracker.recommendations.engine.recommend_run`'s ordering: score, sort
    descending with ties broken on id, then apply §9.9's hysteresis. §9.8's list policy is
    deliberately *not* applied — it moves refreshers to another view without changing what
    the engine preferred, and a pairwise judgment is a question about the preference.
    """
    kappa = float(point.kappa[facts.kappa_key])
    weights = point.weights
    scored: list[tuple[float, str]] = []

    for candidate in facts.candidates:
        hours = point.tau_hours if candidate.hours is None else max(candidate.hours, 0.0)
        gp = kappa if candidate.gp is None else float(max(candidate.gp, 0))
        values = {
            "pvp_value": candidate.pvp_value,
            "leverage": candidate.leverage,
            "proximity": candidate.proximity,
            "effort_decay": math.exp(-hours / point.tau_hours),
            "cost_decay": math.exp(-gp / kappa),
        }
        log_score = math.log(max(values["pvp_value"], epsilon))
        for name in TUNED:
            log_score += weights[name] * math.log(max(values[name], epsilon))
        scored.append((log_score, candidate.candidate_id))

    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    order = [candidate_id for _, candidate_id in scored]
    return _hysteresis(order, scored, facts.incumbent)


def _hysteresis(
    order: list[str], scored: Sequence[tuple[float, str]], incumbent: str | None
) -> tuple[str, ...]:
    """§9.9, on raw scores (A15), from the log scores the loop already has.

    ``challenger.score > 1.10 × incumbent.score`` is exactly
    ``ln(challenger) − ln(incumbent) > ln(1.10)``, so the comparison is done as a difference
    of logs rather than by exponentiating two numbers that can be 1e-5 apart. Same
    threshold, no round-trip through ``exp``.
    """
    if incumbent is None or incumbent not in order:
        return tuple(order)
    position = order.index(incumbent)
    if position == 0:
        return tuple(order)
    if scored[0][0] - scored[position][0] > math.log(DISPLACEMENT_MARGIN):
        return tuple(order)
    return (incumbent, *order[:position], *order[position + 1 :])


def agreement(
    facts: Sequence[ScenarioFacts], point: Profile, epsilon: float
) -> tuple[int, int, list[tuple[Scenario, Judgment]]]:
    """``(agreed, decidable, disagreements)`` over every pairwise judgment in the corpus.

    §16.3 step 4's objective. Only ``must_rank_above`` counts: the other two shapes are
    statements about a list position, and folding them in would let the search trade three
    genuine preference inversions for one candidate moving from rank 4 to rank 3.

    A pair naming a candidate that did not rank is **excluded from the denominator**, not
    counted as agreement. Otherwise the search could buy a perfect rate from candidates
    disappearing — and completion and blocking do not depend on the weights at all, so it
    would be buying it with a constant.
    """
    agreed = 0
    decidable = 0
    disagreements: list[tuple[Scenario, Judgment]] = []

    for entry in facts:
        order = rank(entry, point, epsilon)
        index = {candidate_id: position for position, candidate_id in enumerate(order)}
        for judgment in entry.scenario.pairs:
            if judgment.subject not in index or judgment.over not in index:
                continue
            decidable += 1
            if index[judgment.subject] < index[str(judgment.over)]:
                agreed += 1
            else:
                disagreements.append((entry.scenario, judgment))

    return agreed, decidable, disagreements


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------


def points(quick: bool, free_kappa: bool) -> Iterator[Profile]:
    """Every grid point satisfying §9.6's κ constraints.

    The ordering constraint (``high < normal < low``) and the min/max bounds are applied
    here rather than as a penalty on the objective: a profile violating them is not a worse
    profile, it is an invalid one, and §9.6 calls them *validation* constraints.

    With ``free_kappa`` false — the default, and what the proposal is built from — κ is
    pinned to :data:`SDD_KAPPA`; see that constant for why it is not a tunable.
    """
    weight_grid = QUICK_GRID if quick else GRID
    kappa_sets = (
        [
            {"high": high, "normal": normal, "low": low}
            for high, normal, low in itertools.product(*KAPPA_GRID.values())
            if high < normal < low and all(KAPPA_MIN <= k <= KAPPA_MAX for k in (high, normal, low))
        ]
        if free_kappa
        else [dict(SDD_KAPPA)]
    )
    weight_vectors = [
        dict(zip(TUNED, combination, strict=True))
        for combination in itertools.product(*(weight_grid[name] for name in TUNED))
    ]

    for tau in TAU_GRID:
        for kappa in kappa_sets:
            for weights in weight_vectors:
                yield Profile(weights=weights, tau_hours=tau, kappa=kappa)


def baseline(profile: ScoringProfile) -> Profile:
    """The shipped v1 profile as a search point, for the before/after comparison."""
    return Profile(
        weights={
            name: getattr(profile.weights, name) / profile.weights.pvp_value for name in TUNED
        },
        tau_hours=profile.tau_hours,
        kappa={
            "high": profile.kappa_gp.high,
            "normal": profile.kappa_gp.normal,
            "low": profile.kappa_gp.low,
        },
    )


def search(
    facts: Sequence[ScenarioFacts],
    epsilon: float,
    origin: Profile,
    quick: bool,
    free_kappa: bool = False,
) -> tuple[Profile, int, int, int]:
    """The best point on the grid, with ties broken toward the shipped profile.

    §16.3 step 6 asks for *"humanly interpretable values"*, and the tie-break is where that
    is bought: several hundred grid points typically reach the same agreement rate, and the
    one nearest the shipped defaults is both the most interpretable and the smallest change
    to justify to a reviewer. Distance is measured in grid units — each weight normalized by
    its own step, τ by 5 hours, κ by 4M — so no axis dominates the metric merely by being
    denominated in millions.
    """
    best: Profile | None = None
    best_agreed = -1
    best_distance = math.inf
    examined = 0

    for point in points(quick, free_kappa):
        examined += 1
        agreed, _, _ = agreement(facts, point, epsilon)
        if agreed < best_agreed:
            continue
        distance = _distance(point, origin)
        if agreed > best_agreed or distance < best_distance:
            best, best_agreed, best_distance = point, agreed, distance

    assert best is not None
    _, decidable, _ = agreement(facts, best, epsilon)
    return best, best_agreed, decidable, examined


def _distance(point: Profile, origin: Profile) -> float:
    weights = sum(abs(point.weights[name] - origin.weights[name]) / 0.2 for name in TUNED)
    tau = abs(point.tau_hours - origin.tau_hours) / 5.0
    kappa = sum(
        abs(point.kappa[k] - origin.kappa[k]) / 4_000_000 for k in ("high", "normal", "low")
    )
    return weights + tau + kappa


def verify(
    point: Profile, content: Content, scenarios: Sequence[Scenario], expected_rate: float
) -> None:
    """Re-measure the winner with the real engine and abort on any discrepancy.

    The surrogate is an optimization, and an optimization that silently drifted from the
    thing it approximates would hand a reviewer a number the app cannot reproduce. This runs
    ``recommend_run`` through the loader the tests use and compares the rates.
    """
    profile = point.as_scoring_profile(content.profile)
    agreed = decidable = 0
    for scenario in scenarios:
        outcome = evaluate(scenario, content, profile)
        for judgment in scenario.pairs:
            verdict = outcome.verdict(judgment)
            if verdict is None:
                continue
            decidable += 1
            agreed += int(verdict)

    measured = agreed / decidable if decidable else 0.0
    if abs(measured - expected_rate) > 1e-9:
        raise SystemExit(
            f"ABORT: the surrogate reported {expected_rate:.4f} and the real engine measures "
            f"{measured:.4f}. The fast scorer has drifted from recommend_run; fix it before "
            "trusting any number in this report."
        )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def report(quick: bool) -> int:
    content, scenarios = corpus()
    facts = collect(content, scenarios)
    epsilon = content.profile.epsilon
    origin = baseline(content.profile)

    total_pairs = sum(len(scenario.pairs) for scenario in scenarios)
    total_judgments = sum(len(scenario.judgments) for scenario in scenarios)

    print("§16.3 weight tuning — golden corpus\n" + "=" * 72)
    print(f"scenarios            {len(scenarios)}")
    print(f"judgments recorded   {total_judgments} ({total_pairs} pairwise)")
    print(f"grid                 {'quick' if quick else 'full'}")

    v1_agreed, v1_decidable, v1_disagreements = agreement(facts, origin, epsilon)
    print(f"\nv1 (shipped, provisional per D4)  {_rate(v1_agreed, v1_decidable)}")
    _print_profile(origin)

    started = time.perf_counter()
    best, best_agreed, best_decidable, examined = search(facts, epsilon, origin, quick)
    elapsed = time.perf_counter() - started
    best_rate = best_agreed / best_decidable if best_decidable else 0.0
    verify(best, content, scenarios, best_rate)

    print(f"\nbest on grid, κ pinned to §9.6's presets  {_rate(best_agreed, best_decidable)}")
    print(f"  {examined} points examined in {elapsed:.1f}s; verified against recommend_run")
    _print_profile(best)

    free, free_agreed, free_decidable, free_examined = search(
        facts, epsilon, origin, quick, free_kappa=True
    )
    print(f"\nbest with κ free (§9.6 validation only)  {_rate(free_agreed, free_decidable)}")
    print(f"  {free_examined} points examined")
    _print_profile(free)
    if free.kappa != SDD_KAPPA:
        print(
            "  NOT PROPOSED. §9.6 prints a worked cost_decay table that its three authored\n"
            "  presets are the unique solution to, and Step 6 asserts it\n"
            "  (test_cost_decay_reproduces_the_worked_table). Moving κ improves agreement by\n"
            f"  {free_agreed - best_agreed} pair(s) and falsifies a table the UI shows the user.\n"
            "  Reported so the reviewer can price the constraint, not so it can be adopted."
        )

    _print_disagreements("DISAGREEMENTS AT v1", v1_disagreements)
    _, _, best_disagreements = agreement(facts, best, epsilon)
    _print_disagreements("DISAGREEMENTS AT THE BEST GRID POINT", best_disagreements)

    fixed = {j.label for _, j in v1_disagreements} - {j.label for _, j in best_disagreements}
    broken = {j.label for _, j in best_disagreements} - {j.label for _, j in v1_disagreements}
    print("\nWHAT THE RETUNE WOULD CHANGE")
    print("-" * 72)
    print(f"  resolved by tuning : {sorted(fixed) or '(none)'}")
    print(f"  newly broken       : {sorted(broken) or '(none)'}")

    print("\nPROPOSED profile.yaml — NOT WRITTEN")
    print("-" * 72)
    print(_yaml(best, content.profile))

    print(
        "\n§16.3 step 5 is a human decision. This tool has not modified\n"
        "content/scoring/profile.yaml and will not. Review every disagreement above — a\n"
        "disagreement is as likely to reveal a bad judgment as a bad weight — record the\n"
        "resolution in docs/TUNING.md, then persist the profile by hand with version: 2 and\n"
        "tuned_against_corpus set to the corpus commit."
    )
    return 0


def _rate(agreed: int, decidable: int) -> str:
    pct = 100.0 * agreed / decidable if decidable else 0.0
    return f"pairwise agreement {agreed}/{decidable} = {pct:.1f}%"


def _print_profile(point: Profile) -> None:
    weights = "  ".join(f"{name}={point.weights[name]:g}" for name in TUNED)
    kappa = "/".join(f"{point.kappa[k] // 1_000_000}M" for k in ("high", "normal", "low"))
    print(f"  pvp_value=1 (numeraire)  {weights}")
    print(f"  tau={point.tau_hours:g}h  kappa={kappa}")


def _print_disagreements(title: str, disagreements: Sequence[tuple[Scenario, Judgment]]) -> None:
    print(f"\n{title}")
    print("-" * 72)
    if not disagreements:
        print("  (none)")
        return
    for scenario, judgment in disagreements:
        marker = " [already pending review]" if judgment.pending_review else ""
        print(f"  {scenario.id}: {judgment.label}{marker}")
        print(f"      recorded reason: {' '.join(judgment.because.split())}")


def _yaml(point: Profile, base: ScoringProfile) -> str:
    """The §9.7 block this search proposes, for a human to paste after reviewing."""
    lines = [
        "scoring_profile:",
        "  version: 2",
        "  tuned_against_corpus: <hash of the tests/golden/ commit>",
        f"  tau_hours: {point.tau_hours:g}",
        "  kappa_gp: {"
        + ", ".join(f"{k}: {point.kappa[k]}" for k in ("high", "normal", "low"))
        + "}",
        f"  observation_aged_days: {base.observation_aged_days}",
        f"  unknown_effort_hours: {point.tau_hours:g}",
        "  weights:",
        "    pvp_value: 1.0",
    ]
    lines.extend(f"    {name}: {point.weights[name]:g}" for name in TUNED)
    lines.append("  refresher:")
    lines.append(f"    max_in_primary_list: {base.refresher.max_in_primary_list}")
    lines.append(
        f"    breadth_bonus_per_extra_member: {base.refresher.breadth_bonus_per_extra_member:g}"
    )
    lines.append(f"    breadth_bonus_cap: {base.refresher.breadth_bonus_cap:g}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="§16.3 weight search over tests/golden/. Reports; never writes.",
        epilog="This tool has no --write flag by design: §16.3 step 5 is a human decision.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="print the full report (the only mode; accepted for the documented invocation)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="coarse 3-value weight grid, for a fast sanity pass",
    )
    args = parser.parse_args(argv)
    _ = args.report
    return report(quick=args.quick)


if __name__ == "__main__":
    raise SystemExit(main())


assert set(TUNED) | {"pvp_value"} == set(FACTOR_NAMES), (
    "the search must cover exactly §9.4's factor set; a factor missing from TUNED would be "
    "silently pinned at the shipped weight and reported as tuned"
)
