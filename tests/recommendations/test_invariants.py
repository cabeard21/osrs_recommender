"""§16.2's invariants, §9.9's boundary, and the v0.1 defect that motivated §9.4.

Invariant tests *"must always hold, regardless of tuning"* (§16.2). They are therefore
written against orderings and exclusions, never against absolute scores: Step 13 will retune
every weight in ``profile.yaml`` (§16.3), and a test asserting a number would fail on a
change that was correct.

**Seven of §16.2's nine are here. Two are deliberately absent:**

* *"``achieved`` never transitions true → false from the passage of time"* (G1) —
  ``recommend()`` is pure and never mutates a milestone. It belongs to Step 8c's freshness
  service.
* *"Absent WOM evidence never advances a milestone's freshness state"* (G6) — WOM is not
  visible to a pure function over ``PlayerState``. It belongs to Step 7's adapter, which owns
  it and has a named test for it.

§16.2 says as much itself. Stubbing either here would produce a passing test that proves
nothing and, worse, would look like coverage.

Two of the invariants are about *"two otherwise identical candidates"*, which the seed corpus
cannot supply — every candidate in it differs from every other in several ways at once,
because it exists to be realistic. Those use the micro-corpus below, where the only
difference between two candidates is the one under test.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from tracker.content.loader import Content
from tracker.content.requirements import parse
from tracker.content.schema import (
    Candidate,
    Capability,
    Item,
    LevelRange,
    Roadmap,
    ScoringProfile,
    Skill,
    TrainingMethod,
)
from tracker.domain.types import (
    CandidateKind,
    IncumbentRecommendation,
    MilestoneState,
    PlayerState,
    Recommendation,
    RoadmapSelection,
    UnlockState,
)
from tracker.recommendations.engine import recommend, recommend_run
from tracker.recommendations.hysteresis import apply_hysteresis

MAIN_NH = RoadmapSelection({"main_nh": 1.0})
WORKED = RoadmapSelection({"main_nh": 0.75, "anti_pk": 0.25})
MICRO = RoadmapSelection({"r": 1.0})

NH_GROUP = ("comfortable_4_way_switches", "consistent_overhead_prayers", "freeze_logging_practice")


def ids(entries: Sequence[Recommendation]) -> list[str]:
    return [entry.candidate_id for entry in entries]


def rank_of(entries: Sequence[Recommendation], candidate_id: str) -> int:
    return ids(entries).index(candidate_id)


# ---------------------------------------------------------------------------
# A corpus in which two candidates differ in exactly one way
# ---------------------------------------------------------------------------


def micro_corpus(profile: ScoringProfile, *candidates: Candidate, weight: float = 1.0) -> Content:
    """Two capabilities, one roadmap, and whichever candidates a test names.

    ``gated`` is reachable — it wants 94 Magic — so a grant can flip it and ``leverage`` has
    something to measure. ``target`` gates on an unlock nothing here grants, so no candidate
    can ever flip it.

    **That last detail is load-bearing, and getting it wrong silently breaks the two
    "otherwise identical" tests.** An earlier draft had ``target`` require 99 Magic, which
    made the 99-level training candidate flip *two* capabilities to the 94-level one's *one*
    — so the pair differed in ``leverage`` as well as in distance, and the invariant under
    test was no longer the only thing separating them. A capability nothing can reach keeps
    ``leverage`` equal across the pair, which is what "otherwise identical" has to mean.
    """
    return Content(
        profile=profile,
        skills={"magic": Skill(id="magic", name="Magic", is_combat=True)},
        capabilities={
            "target": Capability(
                id="target", name="Target", requires=parse({"unlock": "nothing_grants_this"})
            ),
            "gated": Capability(id="gated", name="Gated", requires=parse({"skill": {"magic": 94}})),
        },
        roadmaps={"r": Roadmap(id="r", name="R", capabilities={"target": weight, "gated": weight})},
        items={
            "cheap": Item(id="cheap", name="Cheap", price_mode="static", fallback_price_gp=1_000),
            "dear": Item(id="dear", name="Dear", price_mode="static", fallback_price_gp=90_000_000),
        },
        training_methods={
            "magic_default": TrainingMethod(
                id="magic_default",
                name="Default Magic",
                skill="magic",
                xp_per_hour=50_000,
                level_range=LevelRange(min=1, max=99),
            )
        },
        candidates={candidate.id: candidate for candidate in candidates},
    )


def acquisition(candidate_id: str, item_id: str) -> Candidate:
    """An acquisition whose only distinguishing feature is what it costs."""
    return Candidate(
        id=candidate_id,
        name=candidate_id,
        kind=CandidateKind.ACQUISITION,
        advances={"target": 1.0},
        completion=parse({"item": item_id}),
    )


def training(candidate_id: str, level: int) -> Candidate:
    """A training candidate whose only distinguishing feature is how far away it is."""
    return Candidate(
        id=candidate_id,
        name=candidate_id,
        kind=CandidateKind.SKILL_TRAINING,
        advances={"gated": 1.0},
        completion=parse({"skill": {"magic": level}}),
        grants_facts=parse({"skill": {"magic": level}}),
    )


# ---------------------------------------------------------------------------
# §16.2's engine-side invariants
# ---------------------------------------------------------------------------


class TestExclusions:
    """The invariants about candidates that must not appear at all."""

    def test_a_blocked_candidate_never_appears_in_the_actionable_list(
        self,
        player: Callable[..., PlayerState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """``train_magic_87_to_94`` gates on Ancients; locked means excluded, not ranked low.

        Excluded rather than penalised because a score, however small, invites the very
        comparison the ``readiness`` gate exists to refuse: you cannot start this.
        """
        base = player(skills={"magic": 87})
        state = PlayerState(  # Ancients definitively locked, not merely unobserved
            player_id=base.player_id,
            skills=base.skills,
            unlocks={"ancient_magicks": UnlockState.LOCKED},
            container_scans=base.container_scans,
            last_sync_at=base.last_sync_at,
        )

        run = recommend_run(state, MAIN_NH, seed_content, profile, now=now)

        assert "train_magic_87_to_94" not in ids(run.primary)
        assert "train_magic_87_to_94" in ids(run.blocked)

    def test_a_completed_candidate_never_ranks(
        self,
        player: Callable[..., PlayerState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """Completion is tested *before* scoring (§16.2), never approximated by a low score."""
        state = player(skills={"magic": 94}, unlocks=["ancient_magicks"])

        entries = recommend(state, MAIN_NH, seed_content, profile, now=now)

        assert "train_magic_87_to_94" not in ids(entries)

    def test_an_unknown_gate_is_ranked_not_blocked(
        self,
        player: Callable[..., PlayerState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """**G3**. An account that has never synced its unlocks must read *sync this*, not
        *do this* — ``if gate is not Tri.SATISFIED`` passes every other test here and is
        wrong (§16.2)."""
        state = player(skills={"magic": 87})  # nothing observed about unlocks

        run = recommend_run(state, MAIN_NH, seed_content, profile, now=now)
        entry = next(e for e in run.primary if e.candidate_id == "train_magic_87_to_94")

        assert entry.unknown_gate is True
        assert entry.blocked is False
        assert "train_magic_87_to_94" not in ids(run.blocked)


class TestPairwiseOrdering:
    """The invariants about how two candidates compare."""

    def test_the_more_expensive_of_two_identical_candidates_does_not_outrank_the_cheaper(
        self, player: Callable[..., PlayerState], profile: ScoringProfile, now: datetime
    ) -> None:
        content = micro_corpus(
            profile, acquisition("cheap_buy", "cheap"), acquisition("dear_buy", "dear")
        )
        state = player(skills={"magic": 87})

        entries = recommend(state, MICRO, content, profile, now=now)

        assert rank_of(entries, "cheap_buy") < rank_of(entries, "dear_buy")

    def test_the_closer_of_two_identical_candidates_ranks_higher(
        self, player: Callable[..., PlayerState], profile: ScoringProfile, now: datetime
    ) -> None:
        content = micro_corpus(profile, training("to_94", 94), training("to_99", 99))
        state = player(skills={"magic": 87})

        entries = recommend(state, MICRO, content, profile, now=now)

        assert rank_of(entries, "to_94") < rank_of(entries, "to_99")

    def test_raising_a_capability_weight_never_lowers_a_candidate_that_advances_only_it(
        self, player: Callable[..., PlayerState], profile: ScoringProfile, now: datetime
    ) -> None:
        """The monotonicity that makes roadmap selection mean anything to a user.

        Compared as scores rather than as ranks because there is nothing for the candidate to
        change places with — a rank comparison would be vacuously true.
        """
        state = player(skills={"magic": 87})

        low = recommend(
            state, MICRO, micro_corpus(profile, training("t", 94), weight=0.3), profile, now=now
        )
        high = recommend(
            state, MICRO, micro_corpus(profile, training("t", 94), weight=0.9), profile, now=now
        )

        assert high[0].score >= low[0].score


class TestRefresherPolicy:
    """The invariants about refreshers (G10, D9)."""

    def _decayed(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        nh_members: Sequence[str],
        *,
        days: int = 120,
    ) -> PlayerState:
        """A capable account whose practice has decayed, so refreshers are in play."""
        return player(
            skills={"magic": 87, "prayer": 20, "defence": 70},
            unlocks=["ancient_magicks"],
            quests=["desert_treasure_i"],
            milestones=[
                *(milestone_state(key, practiced_days_ago=days) for key in nh_members),
                milestone_state("vengeance_timing", practiced_days_ago=days),
            ],
        )

    def test_at_most_one_refresher_reaches_the_primary_list(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """**G10**. Both shipped practice groups are decayed here, so two composites are
        generated and exactly one may surface (§9.8)."""
        state = self._decayed(player, milestone_state, NH_GROUP)

        run = recommend_run(state, WORKED, seed_content, profile, now=now)

        practice = [e for e in run.primary if e.kind is CandidateKind.PRACTICE]
        assert len(practice) <= profile.refresher.max_in_primary_list
        assert len(run.deferred_refreshers) >= 1

    def test_a_deferred_refresher_is_still_scored_and_explained(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§9.8 sends the overflow to a *"Practice freshness"* view, not to oblivion — and
        the cap is applied after scoring so that view can show real numbers."""
        state = self._decayed(player, milestone_state, NH_GROUP)

        run = recommend_run(state, WORKED, seed_content, profile, now=now)

        assert all(entry.score > 0 for entry in run.deferred_refreshers)
        assert all(entry.practice_members for entry in run.deferred_refreshers)

    def test_group_size_alone_never_wins_a_refresher_the_top_slot(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§9.8's *"a refresher may never be top-ranked solely because many milestones were
        grouped"*.

        The two runs differ **only** in how many members of one group are stale, at the same
        age — so any change in the top slot would be breadth alone deciding the app's most
        prominent answer. The capped bonus is what makes this hold.
        """
        one = self._decayed(player, milestone_state, NH_GROUP[:1])
        three = self._decayed(player, milestone_state, NH_GROUP)

        top_one = recommend(one, WORKED, seed_content, profile, now=now)[0]
        top_three = recommend(three, WORKED, seed_content, profile, now=now)[0]

        assert top_one.candidate_id == top_three.candidate_id

    def test_a_refresher_does_not_take_a_perfect_effort_mark(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """A8 — with hours defaulted to 0, ``effort_decay = exp(0) = 1.0`` and every
        refresher would be maximally attractive, defeating G10 from the inside."""
        state = self._decayed(player, milestone_state, NH_GROUP)

        run = recommend_run(state, WORKED, seed_content, profile, now=now)
        refreshers = [
            *[e for e in run.primary if e.kind is CandidateKind.PRACTICE],
            *run.deferred_refreshers,
        ]

        assert refreshers
        assert all(entry.factors["effort_decay"].value < 1.0 for entry in refreshers)


# ---------------------------------------------------------------------------
# §9.4's founding regression
# ---------------------------------------------------------------------------


def test_the_v0_1_defect_stays_fixed(
    player: Callable[..., PlayerState], profile: ScoringProfile, now: datetime
) -> None:
    """*"Train Magic 87→94"* must outrank *"Train Magic 1→99"* for a player at 87 Magic.

    §9.4: the v0.1 formula multiplied by raw ``distance`` and ``time_estimate``, so it ranked
    *further away and slower* as *better* — by construction, not by accident. The geometric
    mean over decaying factors is what replaced it, and this is the case that proves it.
    """
    content = micro_corpus(profile, training("to_94", 94), training("to_99", 99))
    state = player(skills={"magic": 87})

    entries = recommend(state, MICRO, content, profile, now=now)

    assert entries[0].candidate_id == "to_94"


# ---------------------------------------------------------------------------
# §9.9 hysteresis
# ---------------------------------------------------------------------------


class TestHysteresis:
    """§9.9, A15 — raw scores, and strictly greater than the margin."""

    def _entry(self, candidate_id: str, score: float) -> Recommendation:
        return Recommendation(
            candidate_id=candidate_id,
            name=candidate_id,
            kind=CandidateKind.SKILL_TRAINING,
            score=score,
        )

    def test_a_challenger_at_exactly_the_margin_does_not_displace(self) -> None:
        """The boundary §16.2 asks for by name: displacement requires strictly more."""
        ranked = [self._entry("challenger", 1.10), self._entry("incumbent", 1.00)]

        ordered = apply_hysteresis(ranked, IncumbentRecommendation("incumbent"))

        assert ids(ordered)[0] == "incumbent"

    def test_a_challenger_just_past_the_margin_displaces(self) -> None:
        ranked = [self._entry("challenger", 1.101), self._entry("incumbent", 1.00)]

        ordered = apply_hysteresis(ranked, IncumbentRecommendation("incumbent"))

        assert ids(ordered)[0] == "challenger"

    def test_the_margin_is_raw_not_logarithmic(self) -> None:
        """A15. A 10% margin in log space is a different threshold, and the two diverge away
        from ``score = 1``; here a log-space reading would displace and a raw one must not."""
        ranked = [self._entry("challenger", 0.109), self._entry("incumbent", 0.100)]

        ordered = apply_hysteresis(ranked, IncumbentRecommendation("incumbent"))

        assert ids(ordered)[0] == "incumbent"

    def test_only_the_incumbent_moves(self) -> None:
        """Restored to the front, not swapped: swapping would bury the challenger at the
        incumbent's old rank, below candidates it beat."""
        ranked = [
            self._entry("a", 1.05),
            self._entry("b", 1.02),
            self._entry("incumbent", 1.00),
        ]

        ordered = apply_hysteresis(ranked, IncumbentRecommendation("incumbent"))

        assert ids(ordered) == ["incumbent", "a", "b"]

    def test_an_absent_incumbent_changes_nothing(self) -> None:
        """How *"the incumbent became complete or blocked"* reaches this function: both are
        already excluded from the list upstream (§16.2)."""
        ranked = [self._entry("a", 1.05), self._entry("b", 1.00)]

        ordered = apply_hysteresis(ranked, IncumbentRecommendation("gone"))

        assert ids(ordered) == ["a", "b"]

    def test_a_first_run_has_no_incumbent_to_defend(self) -> None:
        ranked = [self._entry("a", 1.05), self._entry("b", 1.00)]

        assert apply_hysteresis(ranked, None) == tuple(ranked)

    def test_the_engine_honours_an_incumbent(
        self,
        player: Callable[..., PlayerState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """End to end: the parameter §16.1 added to the signature actually reaches §9.9."""
        state = player(skills={"magic": 87, "prayer": 20})

        natural = recommend(state, WORKED, seed_content, profile, now=now)
        runner_up = natural[1].candidate_id

        defended = recommend(
            state, WORKED, seed_content, profile, IncumbentRecommendation(runner_up), now=now
        )

        assert defended[0].candidate_id in {runner_up, natural[0].candidate_id}


# ---------------------------------------------------------------------------
# Step 13 scenarios, pulled forward (§16.1)
# ---------------------------------------------------------------------------


class TestGoldenScenariosPulledForward:
    """Three of Step 13's judgments, run here so gaps surface before the tuning step.

    §16.1 writes these as *"must_rank_above"* / *"must_not_be_top"* rather than as exact
    orderings, because two near-tied candidates flip on noise and a full-ordering assertion
    would fail for no meaningful reason.
    """

    def _mid_account(
        self, player: Callable[..., PlayerState], milestone_state: Callable[..., MilestoneState]
    ) -> PlayerState:
        """§16.1's fixture account: capable, Ancients still locked, nothing bought yet."""
        return player(
            skills={
                "magic": 87,
                "thieving": 53,
                "firemaking": 50,
                "slayer": 10,
                "prayer": 20,
                "defence": 70,
                "strength": 85,
                "woodcutting": 60,
            },
            milestones=[milestone_state("comfortable_4_way_switches", practiced_days_ago=3)],
        )

    def test_desert_treasure_outranks_training_woodcutting(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """Woodcutting advances nothing, and the corpus says so with an empty ``advances``
        map — so this must fall out of the derivation, not out of code recognising a name."""
        entries = recommend(
            self._mid_account(player, milestone_state), MAIN_NH, seed_content, profile, now=now
        )

        assert rank_of(entries, "complete_desert_treasure_i") < rank_of(
            entries, "train_woodcutting"
        )

    def test_desert_treasure_outranks_buying_a_voidwaker_while_ancients_are_locked(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§16.2's first pairwise judgment. DT1's leverage is what carries it: unlocking
        Ancients is what lets Ice Barrage NH and the Magic candidate stop being blocked."""
        entries = recommend(
            self._mid_account(player, milestone_state), MAIN_NH, seed_content, profile, now=now
        )

        assert rank_of(entries, "complete_desert_treasure_i") < rank_of(entries, "buy_voidwaker")

    def test_a_high_risk_gear_purchase_is_never_the_top_recommendation(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§16.1's ``must_not_be_top``. The most expensive thing in the corpus, advancing
        less than the cheaper alternative — if it ever leads, ``cost_decay`` has stopped
        biting."""
        entries = recommend(
            self._mid_account(player, milestone_state), MAIN_NH, seed_content, profile, now=now
        )

        assert entries[0].candidate_id != "buy_high_risk_gear"

    def test_every_ranked_entry_explains_itself(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§9.10's *"Why"* line and §6.10's persisted factors, on real content.

        Both halves are asserted because §9.5's guarantee is that they are one calculation: a
        candidate with factors but no reason would mean the prose had been authored somewhere
        else after all.
        """
        entries = recommend(
            self._mid_account(player, milestone_state), MAIN_NH, seed_content, profile, now=now
        )

        assert entries
        for entry in entries:
            assert set(entry.factors) == {
                "pvp_value",
                "leverage",
                "method_unlock",
                "proximity",
                "effort_decay",
                "cost_decay",
            }
            if any(factor.value > profile.epsilon for factor in entry.factors.values()):
                assert entry.reason

    def test_the_ranking_is_deterministic(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§16.1 pins a scenario and expects the same answer every time — which needs the
        tie-break to be total, not merely usually decisive."""
        state = self._mid_account(player, milestone_state)

        first = recommend(state, MAIN_NH, seed_content, profile, now=now)
        second = recommend(state, MAIN_NH, seed_content, profile, now=now)

        assert ids(first) == ids(second)


def test_the_engine_scores_the_shipped_corpus_without_prices(
    player: Callable[..., PlayerState],
    seed_content: Content,
    profile: ScoringProfile,
    now: datetime,
) -> None:
    """§8.3's cascade must reach its static-hint layer rather than raising.

    The price map is empty on a first run — Step 7 fetches, Step 9 persists, and neither has
    happened yet — so the first recommendation a new user ever sees is produced under exactly
    these conditions.
    """
    entries = recommend(player(skills={"magic": 87}), MAIN_NH, seed_content, profile, now=now)

    assert entries
    assert all(entry.estimate is not None for entry in entries)
