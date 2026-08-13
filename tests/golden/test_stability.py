"""§16.2's three stability tests: *"small input changes must not cause large reorderings"*.

    +10,000 Magic XP does not replace the top recommendation unless a threshold is crossed.
    A 2% item price movement does not move a candidate from rank 8 to rank 1.
    A milestone crossing 30 days does not reorder the primary progression list.

**Each is paired with its negative.** A stability test that only ever asserts *nothing
changed* is satisfied by an engine that ignores its input, which would be a far worse bug
than the instability the test was written to catch. So every test here also pins the change
that *must* register: seven Magic levels do replace the top entry, a 40× price movement does
reorder the acquisitions, and crossing 30 days does produce a refresher.

The three scenarios come from the corpus rather than being built here. A stability claim is
about a realistic account — an artificial state can be made stable by construction, which is
exactly the property under test.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.golden.loader import Scenario, corpus, evaluate
from tracker.domain.types import (
    CandidateKind,
    MilestoneState,
    PlayerState,
    Recommendation,
    SkillState,
)
from tracker.estimation.xp_table import xp_for_level

CONTENT, SCENARIOS = corpus()
PROFILE = CONTENT.profile


def _scenario(scenario_id: str) -> Scenario:
    return next(scenario for scenario in SCENARIOS if scenario.id == scenario_id)


def _order(scenario: Scenario) -> tuple[str, ...]:
    return evaluate(scenario, CONTENT, PROFILE).order


def _primary(scenario: Scenario) -> tuple[Recommendation, ...]:
    return evaluate(scenario, CONTENT, PROFILE).primary


def _with_state(scenario: Scenario, state: PlayerState) -> Scenario:
    return replace(scenario, state=state)


def _with_xp(state: PlayerState, skill: str, xp: int) -> PlayerState:
    """The account with one skill's XP pinned, level recomputed from the curve.

    Level and XP must move together: §6.2 stores both, and a state claiming 87 Magic with
    94's XP is not a state any sync could produce. Setting only one would let this test pass
    against an engine that reads the other.
    """
    from tracker.estimation.xp_table import level_for_xp

    existing = state.skills[skill]
    skills = dict(state.skills)
    skills[skill] = SkillState(
        level=level_for_xp(xp), xp=xp, source=existing.source, observed_at=existing.observed_at
    )
    return replace(state, skills=skills)


# ---------------------------------------------------------------------------
# 1. +10,000 Magic XP
# ---------------------------------------------------------------------------


class TestSkillXpStability:
    """§16.2: *"+10,000 Magic XP does not replace the top recommendation unless a threshold
    is crossed."*

    ``far_from_barrage`` is the account used, at 75 Magic (1,210,421 XP). 10,000 XP is under
    a percent of that and crosses no level boundary — 76 Magic is 1,336,443 — so nothing
    about what the player *can do* has changed. The recommendation must not change either.
    """

    def test_ten_thousand_magic_xp_does_not_replace_the_top_recommendation(self) -> None:
        scenario = _scenario("far_from_barrage")
        base_xp = xp_for_level(75)
        before = _with_state(scenario, _with_xp(scenario.state, "magic", base_xp))
        after = _with_state(scenario, _with_xp(scenario.state, "magic", base_xp + 10_000))

        assert _order(before)[0] == _order(after)[0]
        assert _order(before) == _order(after), (
            "10k XP is under a percent of the account's Magic and crosses no level; a "
            "reordering here would mean the ranking tracks noise"
        )

    def test_the_score_moves_by_less_than_a_percent(self) -> None:
        """The quantitative half. Rank stability with a wildly swinging score would still
        thrash §9.9's 1.10× margin on the next sync, so the *score* has to be smooth too."""
        scenario = _scenario("far_from_barrage")
        base_xp = xp_for_level(75)
        before = _primary(_with_state(scenario, _with_xp(scenario.state, "magic", base_xp)))
        after = _primary(_with_state(scenario, _with_xp(scenario.state, "magic", base_xp + 10_000)))

        top_before, top_after = before[0], after[0]
        assert top_before.candidate_id == top_after.candidate_id
        drift = abs(top_after.score - top_before.score) / top_before.score
        assert drift < 0.01, f"top score moved {drift:.1%} on a sub-1% XP change"

    def test_but_crossing_the_threshold_does_replace_it(self) -> None:
        """The negative. 75 → 94 Magic *completes* the Magic candidate, which must drop out
        of the ranking entirely (§16.2: a completed candidate never ranks). Without this,
        the test above is also satisfied by an engine that never changes its mind."""
        scenario = _scenario("far_from_barrage")
        before = _order(_with_state(scenario, _with_xp(scenario.state, "magic", xp_for_level(75))))
        after = _order(_with_state(scenario, _with_xp(scenario.state, "magic", xp_for_level(94))))

        assert before[0] == "train_magic_87_to_94"
        assert "train_magic_87_to_94" not in after


# ---------------------------------------------------------------------------
# 2. A 2% price movement
# ---------------------------------------------------------------------------


class TestPriceStability:
    """§16.2: *"a 2% item price movement does not move a candidate from rank 8 to rank 1."*

    ``gp_sensitivity_low`` is the account used, because it is the one where prices carry the
    most weight in the ranking: every skill grind is complete, so the list is acquisitions
    and cost_decay is doing nearly all the work. If a 2% move is going to reorder anything
    anywhere, it will reorder it here.

    Both directions are tested. ``exp(−gp/κ)`` is convex, so a 2% rise and a 2% fall are not
    symmetric, and an implementation could be stable against one and not the other.
    """

    @pytest.mark.parametrize("factor", [1.02, 0.98])
    def test_a_two_percent_price_move_does_not_reorder_the_list(self, factor: float) -> None:
        scenario = _scenario("gp_sensitivity_low")
        moved = replace(
            scenario,
            prices={item_id: record.scaled(factor) for item_id, record in scenario.prices.items()},
        )

        assert _order(scenario) == _order(moved), (
            f"a {abs(1 - factor):.0%} price move reordered the ranking; §16.2 requires "
            "market noise to be invisible to the coaching"
        )

    @pytest.mark.parametrize("factor", [1.02, 0.98])
    def test_no_score_moves_more_than_a_few_percent(self, factor: float) -> None:
        """Rank stability again is not enough on its own — see the XP test's second case.

        The bound is 10% rather than 2% because ``cost_decay = exp(−gp/κ)`` amplifies: at the
        Voidwaker's 85M against κ = 50M, a 2% price move is a 3.4% move in the factor. What
        must not happen is amplification without bound, which is what a small κ combined with
        a large ``cost_decay`` weight would produce.
        """
        scenario = _scenario("gp_sensitivity_low")
        moved = replace(
            scenario,
            prices={item_id: record.scaled(factor) for item_id, record in scenario.prices.items()},
        )
        before = {entry.candidate_id: entry.score for entry in _primary(scenario)}

        for entry in _primary(moved):
            baseline = before[entry.candidate_id]
            drift = abs(entry.score - baseline) / baseline
            assert drift < 0.10, f"{entry.candidate_id} moved {drift:.1%} on a 2% price move"

    def test_but_a_forty_fold_price_move_does_reorder_them(self) -> None:
        """The negative. A 2% move must be invisible; a 40× one must not be.

        Written as a **price rise** rather than a fall, and phrased about the pair's relative
        order rather than about who holds rank 1, so that it survives a retune. §16.3 is
        going to change these weights, and the baseline winner of the acquisition pair is
        exactly what a retune is expected to move — a test asserting it would fail on the
        very change it was written to permit.

        **It doubles as a floor under ``cost_decay``'s weight, and that is not incidental.**
        §9.4 floors every factor at ε = 0.01, so the worst mark cost can give a candidate is
        ``0.01 ^ w``: at ``w = 0.5`` that is 0.10, at ``w = 0.1`` it is 0.63. Below roughly
        ``w = 0.15``, no price however absurd can overcome a 1.6× relevance advantage, and
        this assertion is the one that notices. Step 13's search proposes lowering
        ``cost_decay``; if a proposal ever takes it far enough that a 3.4-billion-GP purchase
        still ranks first, this test fails and says so.
        """
        scenario = _scenario("gp_sensitivity_low")
        dearer = replace(
            scenario,
            prices={
                item_id: (record.scaled(40.0) if item_id == _VOIDWAKER else record)
                for item_id, record in scenario.prices.items()
            },
        )
        order = _order(dearer)

        assert order.index("buy_high_risk_gear") < order.index("buy_voidwaker"), (
            "a 3.4-billion-GP Voidwaker must rank below a 16.5M gear set at any weights; "
            "if it does not, cost is not reaching the ranking at all"
        )


#: The numeric OSRS id §10.5 declares for the Voidwaker.
_VOIDWAKER = 27690


# ---------------------------------------------------------------------------
# 3. A milestone crossing 30 days
# ---------------------------------------------------------------------------


class TestFreshnessStability:
    """§16.2: *"a milestone crossing 30 days does not reorder the primary progression list."*

    30 days is ``STALE_AFTER``: the boundary where §6.6 turns ``current`` into ``stale`` and
    §9.8 starts emitting a refresher. **Something must change at that boundary** — a
    refresher appears, which is the entire point of the freshness layer — so the invariant is
    narrower than "nothing moves". It is D1 and G2 restated at the ranking layer: freshness
    creates refreshers and adjusts readiness; it never touches ``status``, and so it must
    never reorder the *progression* candidates among themselves.

    The account is ``mildly_stale_vs_progression``, whose nh group sits at 40 days. Rewinding
    it to 29 and pushing it to 31 brackets the boundary.
    """

    NH_GROUP = (
        "comfortable_4_way_switches",
        "consistent_overhead_prayers",
        "freeze_logging_practice",
    )

    def _at(self, days: float) -> Scenario:
        from datetime import timedelta

        scenario = _scenario("mildly_stale_vs_progression")
        milestones = dict(scenario.state.milestones)
        for key in self.NH_GROUP:
            existing = milestones[key]
            milestones[key] = MilestoneState(
                key=existing.key,
                achieved=existing.achieved,
                attested=existing.attested,
                kind=existing.kind,
                class_=existing.class_,
                value=existing.value,
                last_practiced_at=scenario.now - timedelta(days=days),
            )
        return _with_state(scenario, replace(scenario.state, milestones=milestones))

    def _progression(self, days: float) -> tuple[str, ...]:
        """Every objective candidate in score order — the *whole* ordering, not one page.

        Read off ``ranked`` rather than ``primary`` because the claim below is about
        ordering and ``primary`` is capped at ``max_primary_entries``. A refresher
        appearing at 31 days legitimately consumes one of those slots, which drops the
        last progression entry off the end; comparing capped lists would report that
        truncation as a reorder and fail a test whose subject is decay leaking into the
        status layer. The cap can only cut a tail, so nothing this test is about is hidden
        by looking past it.
        """
        return tuple(
            entry.candidate_id
            for entry in evaluate(self._at(days), CONTENT, PROFILE).ranked
            if entry.kind is not CandidateKind.PRACTICE
        )

    def test_crossing_thirty_days_does_not_reorder_the_progression_list(self) -> None:
        assert self._progression(29) == self._progression(31), (
            "practice decay reordered objective progression — G2 and D1 both forbid "
            "freshness reaching the status layer"
        )

    def test_the_progression_list_is_unchanged_across_the_whole_stale_band(self) -> None:
        """The same claim over the band rather than at one boundary. §9.8's urgency ramps
        from 0.40 to 0.70 across 30–90 days, so a leak from freshness into the progression
        ordering could hide anywhere inside it and miss a two-point test."""
        reference = self._progression(1)
        for days in (29, 31, 45, 60, 89, 91, 200):
            assert self._progression(days) == reference, f"reordered at {days} days"

    def test_but_crossing_thirty_days_does_produce_a_refresher(self) -> None:
        """The negative, and the reason this test is phrased about the *progression* list.

        At 29 days the nh group is ``current`` and §10.4's trigger
        (``any_member_freshness_at_least: stale``) has not fired; at 31 it has. A test
        asserting the whole primary list was unchanged would forbid exactly the behaviour
        §9.8 specifies.
        """
        assert not self._refreshers(29)
        assert self._refreshers(31) == ("refresh_nh_fundamentals",)

    def _refreshers(self, days: float) -> tuple[str, ...]:
        return tuple(
            entry.candidate_id
            for entry in evaluate(self._at(days), CONTENT, PROFILE).ranked
            if entry.kind is CandidateKind.PRACTICE
        )
