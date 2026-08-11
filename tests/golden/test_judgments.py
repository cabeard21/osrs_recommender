"""§16.1's judgment tests: ``must_rank_above``, ``top_3_contains``, ``must_not_be_top``.

One test per judgment, not one per scenario. A scenario records a dozen preferences and a
single assertion over all of them reports "scenario 03 failed" — which says nothing about
*which* expert preference the engine disagreed with, and §16.3 step 5 is precisely the job
of reading that one disagreement. Parametrized ids are the judgment's own label, so a
failure line reads ``[midgame_main-buy_voidwaker > buy_high_risk_gear]``.

**No test here asserts a full ordering** (§16.1). Two near-tied candidates flip on noise;
a suite that fails for that reason trains its readers to ignore it.

The three §16.2 pairwise judgments are covered, each in the account it is stated about:

=====================================  ==========================================
DT1 > Voidwaker while Ancients locked  ``02``, ``03``, ``05``, ``10``, ``15``, ``18``
94 Magic > 99 Strength for Barrage     ``04``, ``07``, ``09``, ``16``, ``17``
Rigour ≯ Protect Item below 25 Prayer  ``01``, ``05`` (plus the counter-case in ``11``)
=====================================  ==========================================

``test_the_sdd_named_judgments_are_all_present`` fails if any of those three ever leaves the
corpus, so the coverage claim above cannot rot silently.
"""

from __future__ import annotations

import pytest

from tests.golden.loader import Judgment, Scenario, corpus, evaluate
from tracker.domain.types import CandidateKind, Status
from tracker.progression.engine import compute_capability_states

CONTENT, SCENARIOS = corpus()
PROFILE = CONTENT.profile

#: Every (scenario, judgment) pair in the corpus, flattened for parametrization.
CASES = [(scenario, judgment) for scenario in SCENARIOS for judgment in scenario.judgments]


def _id(case: tuple[Scenario, Judgment]) -> str:
    scenario, judgment = case
    return f"{scenario.id}-{judgment.label}"


@pytest.mark.golden
@pytest.mark.parametrize("case", CASES, ids=[_id(case) for case in CASES])
def test_judgment(case: tuple[Scenario, Judgment], request: pytest.FixtureRequest) -> None:
    """One recorded expert preference against the shipped weights.

    A judgment carrying ``pending_review`` is xfailed **strictly**: the shipped v1 weights
    are known to disagree, the disagreement is documented in ``docs/TUNING.md``, and §16.3
    step 5 leaves the resolution to a human. Strict, so that a retune which fixes one turns
    the suite red and demands the marker be removed rather than quietly passing.
    """
    scenario, judgment = case
    if judgment.pending_review:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                reason=f"§16.3 step 5, pending human review: {judgment.pending_review}",
            )
        )

    outcome = evaluate(scenario, CONTENT, PROFILE)
    verdict = outcome.verdict(judgment)

    assert verdict is not None, (
        f"{judgment.label} could not be evaluated in {scenario.id}: one of its candidates "
        f"did not rank. Ranked: {list(outcome.order)}. A judgment about a candidate that is "
        f"complete or blocked asserts nothing — fix the scenario or drop the judgment."
    )
    assert verdict, (
        f"{judgment.label} does not hold in {scenario.id}.\n"
        f"  ranking: {list(outcome.order)}\n"
        f"  because: {judgment.because.strip()}"
    )


# ---------------------------------------------------------------------------
# Corpus-level guarantees
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_the_corpus_has_at_least_twenty_scenarios() -> None:
    """§16.3 step 1 and the plan's exit criteria both say ~20."""
    assert len(SCENARIOS) >= 20


@pytest.mark.golden
def test_every_scenario_records_at_least_one_judgment() -> None:
    """A scenario with no judgments is a fixture, not a corpus entry."""
    silent = [scenario.id for scenario in SCENARIOS if not scenario.judgments]
    assert not silent, f"scenarios recording nothing: {silent}"


@pytest.mark.golden
def test_the_sdd_named_judgments_are_all_present() -> None:
    """§16.2's three pairwise judgments must each appear somewhere in the corpus.

    Written against the pairs rather than against scenario ids so that reorganising the
    corpus cannot drop one. The reverse direction is checked too: recording the *opposite*
    of an SDD judgment anywhere would be a corpus bug that no per-judgment test can see,
    since each of those tests only ever reads its own row.
    """
    pairs = {(j.subject, j.over) for scenario in SCENARIOS for j in scenario.pairs}
    required = {
        ("complete_desert_treasure_i", "buy_voidwaker"),
        ("train_magic_87_to_94", "train_strength_to_99"),
        ("unlock_protect_item", "unlock_rigour"),
    }
    assert required <= pairs, f"§16.2 judgments missing from the corpus: {required - pairs}"
    inverted = {(over, subject) for subject, over in required} & pairs
    assert not inverted, f"corpus records the inverse of an §16.2 judgment: {inverted}"


@pytest.mark.golden
def test_no_scenario_asserts_more_than_a_relative_order() -> None:
    """§16.1's constraint on the corpus itself, enforced by the loader's key whitelist.

    The loader rejects any judgment key outside the three §16.1 names, so an ``expected_order``
    block cannot be added by accident. This test states the rule where a reader will look for
    it rather than leaving it implicit in a parser.
    """
    kinds = {judgment.kind for scenario in SCENARIOS for judgment in scenario.judgments}
    assert kinds <= {"must_rank_above", "top_3_contains", "must_not_be_top"}


# ---------------------------------------------------------------------------
# The tri-state scenario (§6.5, §4.5, G3)
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_unknown_bank_leaves_acquisitions_neither_complete_nor_blocked() -> None:
    """The whole reason ``07_unknown_bank`` exists (§16.2's last invariant, G3).

    With no ``ContainerScan``, every ``item:`` leaf evaluates ``unknown``. The two failure
    modes are symmetric and both plausible: reading unknown as *unsatisfied* would make the
    acquisitions look maximally incomplete, and reading it as *blocked* would hide them from
    the list the user acts on. Neither is *"we have not looked — sync this"*.
    """
    scenario = _scenario("unknown_bank")
    outcome = evaluate(scenario, CONTENT, PROFILE)

    acquisitions = {"buy_voidwaker", "buy_high_risk_gear"}
    assert acquisitions <= set(outcome.order), "an unknown completion is not completion"
    assert not acquisitions & {entry.candidate_id for entry in outcome.blocked}, (
        "an unknown gate is 'sync this', not 'blocked' (§16.2)"
    )


@pytest.mark.golden
def test_unknown_bank_leaves_item_gated_capabilities_unknown_with_no_readiness() -> None:
    """G3 at the capability layer: an unknown leaf never reaches ``readiness_confidence``.

    ``budget_nh`` is the capability this scenario turns unknown: every one of its leaves is
    definitely satisfied except the ``item: mystic_robe_top`` one, which nobody has looked
    for. Its status must therefore be ``unknown``, and — the part G3 is about — no readiness
    layer may be computed at all. The pair *"unlocked: yes / confidence: low because
    ownership is unknown"* has to be unrepresentable (§6.9), so the assertion is on
    ``readiness_confidence is None`` rather than on some value of it.

    ``ice_barrage_nh`` is checked in the same breath for the **opposite** reason, and it is
    the subtler half. It also has an unknown item leaf — but it wants 94 Magic and the
    account has 87, a *definite* failure. §9.1's three-valued conjunction says
    ``unsatisfied ∧ unknown = unsatisfied``: a known blocker dominates an unknown one, and
    the capability is honestly ``locked`` rather than being softened to ``unknown`` by the
    bank nobody scanned. An implementation that let any unknown leaf win would report
    "unknown" for almost every capability of almost every account and give the user nothing.
    """
    scenario = _scenario("unknown_bank")
    states = compute_capability_states(scenario.state, CONTENT, PROFILE, scenario.now)

    unknown = states["budget_nh"]
    assert unknown.status is Status.UNKNOWN
    assert unknown.readiness_confidence is None, "G3: unknowns stop at status"
    assert unknown.unknowns, "budget_nh is unknown but names no unknown leaf"

    locked = states["ice_barrage_nh"]
    assert locked.status is Status.LOCKED, "a definite blocker dominates an unknown one"
    assert locked.readiness_confidence is None


@pytest.mark.golden
def test_never_synced_blocks_nothing_at_all() -> None:
    """A6's account: ``last_sync_at IS NULL``, so every gate is unknown, so none is blocked."""
    scenario = _scenario("never_synced")
    outcome = evaluate(scenario, CONTENT, PROFILE)

    assert not outcome.blocked, (
        "nothing is known about this account, so nothing can be known to be blocked (G3)"
    )
    assert {entry.candidate_id for entry in outcome.ranked} == set(CONTENT.candidates)


@pytest.mark.golden
def test_the_blend_inverts_pvp_value_for_the_one_member_group() -> None:
    """What ``19_stale_vengeance_focus``'s deleted judgment was reaching for (D3, §9.8).

    The judgment as recorded said the one-member vengeance refresher must **outrank** the
    three-member nh refresher under a ``anti_pk 0.9 / main_nh 0.1`` blend. Step 13b deleted
    it: the engine keeps the nh group ahead on ``leverage``, and it is right to, because
    ``consistent_overhead_prayers`` is an ``anti_pk`` requirement — the nh session serves
    this roadmap too, which the judgment did not notice.

    What survives is the claim §9.8 actually makes, and it is a claim about a **factor**,
    not about a ranking: *"the composite inherits the maximum relevant capability value,
    never the sum"*. Group size must be absent from ``pvp_value``, so the one-member group
    must lead there — and does, which is why nothing about §9.8 needed changing. The two
    factors pulling in opposite directions in one scenario is the reason this scenario is
    kept.
    """
    scenario = _scenario("stale_vengeance_focus")
    outcome = evaluate(scenario, CONTENT, PROFILE)
    factors = {entry.candidate_id: entry.factors for entry in outcome.ranked}

    vengeance = factors["refresh_vengeance_fundamentals"]["pvp_value"].value
    nh = factors["refresh_nh_fundamentals"]["pvp_value"].value
    assert vengeance > nh, (
        "§9.8: group size must not reach pvp_value. The one-member vengeance group is "
        f"weighted 0.9 by the blend and reads {vengeance:.2f}; the three-member nh group "
        f"reads {nh:.2f}"
    )

    vengeance_leverage = factors["refresh_vengeance_fundamentals"]["leverage"].value
    nh_leverage = factors["refresh_nh_fundamentals"]["leverage"].value
    assert nh_leverage > vengeance_leverage, (
        "and the reason the nh group still wins the pair is A29?'s readiness flip, not "
        "its member count — if this ever inverts, D3's resolution needs re-reading"
    )


@pytest.mark.golden
def test_at_most_one_refresher_reaches_the_primary_list_in_every_scenario() -> None:
    """**G10**, swept across the whole corpus rather than in one constructed state.

    ``tests/recommendations/test_refreshers.py`` owns the invariant; what this adds is that
    no realistic account in the corpus — including the two where both practice groups fire
    at once — ever produces a second one.
    """
    for scenario in SCENARIOS:
        outcome = evaluate(scenario, CONTENT, PROFILE)
        practice = [e for e in outcome.primary if e.kind is CandidateKind.PRACTICE]
        assert len(practice) <= PROFILE.refresher.max_in_primary_list, scenario.id


def _scenario(scenario_id: str) -> Scenario:
    return next(scenario for scenario in SCENARIOS if scenario.id == scenario_id)
