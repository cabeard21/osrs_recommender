"""§9.8 — refresher urgency, group composition, and the list policy that caps them (G10)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from tracker.content.loader import Content
from tracker.content.schema import RefresherPolicy, ScoringProfile
from tracker.domain.types import (
    CandidateKind,
    MilestoneClass,
    MilestoneState,
    PlayerState,
    Recommendation,
)
from tracker.freshness.policy import STALE_AFTER, VERY_STALE_AFTER
from tracker.recommendations.refreshers import (
    enforce_list_policy,
    group_urgency,
    member_urgency,
    practice_candidates,
)

NH_GROUP = ("comfortable_4_way_switches", "consistent_overhead_prayers", "freeze_logging_practice")


class TestMemberUrgency:
    """§9.8's per-milestone curve, anchored on §6.6's own band boundaries."""

    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, 0.00),
            (29, 0.00),
            (30, 0.40),
            (60, 0.55),
            (90, 0.70),
            (180, 0.85),
            (270, 1.00),
            (1000, 1.00),
        ],
    )
    def test_the_curve_hits_its_published_anchors(
        self,
        milestone_state: Callable[..., MilestoneState],
        now: datetime,
        days: int,
        expected: float,
    ) -> None:
        """§9.8's table read as a function: 0 → 0.40 → 0.70 → 1.00, linear between.

        The 90-day row is the one worth staring at. §6.6 writes ``stale`` as the inclusive
        range *"30–90 days"*, so exactly 90 days is still stale and sits at the **top** of
        the stale range rather than the bottom of ``very_stale`` — and both readings give
        0.70, which is why the two segments were chosen to meet there.
        """
        state = milestone_state("comfortable_4_way_switches", practiced_days_ago=days)

        assert member_urgency(state, now) == pytest.approx(expected, abs=0.005)

    def test_urgency_never_decreases_with_age(
        self, milestone_state: Callable[..., MilestoneState], now: datetime
    ) -> None:
        ages = [0, 15, 30, 45, 90, 120, 300]
        urgencies = [
            member_urgency(milestone_state("x", practiced_days_ago=days), now) for days in ages
        ]

        assert urgencies == sorted(urgencies)

    @pytest.mark.parametrize("class_", [MilestoneClass.KNOWLEDGE, MilestoneClass.THRESHOLD])
    def test_only_execution_milestones_are_ever_urgent(
        self,
        milestone_state: Callable[..., MilestoneState],
        now: datetime,
        class_: MilestoneClass,
    ) -> None:
        """§6.6: knowledge is understanding once acquired, threshold is a thing that
        happened. Neither ages, so neither can justify a practice session."""
        state = milestone_state("x", class_=class_, practiced_days_ago=400)

        assert member_urgency(state, now) == 0.0

    def test_never_practiced_is_not_urgent(
        self, milestone_state: Callable[..., MilestoneState], now: datetime
    ) -> None:
        """**G6** at the urgency layer. No practice record is a statement about our
        observations, not about the player — reading it as maximum decay would convert
        absence of evidence into evidence of decay (§4.5)."""
        state = milestone_state("x", practiced_days_ago=None)

        assert member_urgency(state, now) == 0.0


class TestGroupUrgency:
    """§9.8 — maximum member plus a capped breadth bonus, never a sum."""

    def test_a_single_member_gets_no_bonus(self, profile: ScoringProfile) -> None:
        assert group_urgency([0.55], profile) == pytest.approx(0.55)

    def test_breadth_adds_the_authored_amount_per_extra_member(
        self, profile: ScoringProfile
    ) -> None:
        assert group_urgency([0.40, 0.40, 0.40], profile) == pytest.approx(0.46)

    def test_breadth_is_capped_before_it_is_added(self, profile: ScoringProfile) -> None:
        """*"The inner cap is what matters"* (§9.8).

        Twenty stale milestones and five stale milestones contribute the same +0.10, so
        urgency keeps meaning *how stale the worst item is* rather than *how many boxes are
        unticked*. Without the cap the twenty-member group saturates at 1.0 on breadth
        alone, and a session of trivia would outrank real account progression.
        """
        five = group_urgency([0.40] * 5, profile)
        twenty = group_urgency([0.40] * 20, profile)

        assert five == twenty == pytest.approx(0.50)

    def test_it_takes_the_maximum_not_the_sum(self, profile: ScoringProfile) -> None:
        members = [0.40, 0.45, 0.50]

        assert group_urgency(members, profile) < sum(members)
        assert group_urgency(members, profile) >= max(members)

    def test_it_never_exceeds_one(self, profile: ScoringProfile) -> None:
        assert group_urgency([1.0] * 8, profile) == 1.0

    def test_an_empty_group_is_not_urgent(self, profile: ScoringProfile) -> None:
        assert group_urgency([], profile) == 0.0


class TestGroupComposition:
    """§9.8, §10.4 — one composite candidate per group, over the members that decayed."""

    def _state(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        **ages: int,
    ) -> PlayerState:
        return player(
            milestones=[milestone_state(key, practiced_days_ago=days) for key, days in ages.items()]
        )

    def test_a_fresh_group_produces_nothing(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        state = self._state(player, milestone_state, **dict.fromkeys(NH_GROUP, 5))

        assert practice_candidates(state, seed_content, profile, now) == ()

    def test_one_candidate_covers_the_whole_group(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """D9's point: three stale mechanics produce **one** session, not three lines."""
        state = self._state(player, milestone_state, **dict.fromkeys(NH_GROUP, 45))

        candidates = practice_candidates(state, seed_content, profile, now)

        assert len(candidates) == 1
        assert candidates[0].id == "refresh_nh_fundamentals"
        assert set(candidates[0].members) == set(NH_GROUP)

    def test_only_the_decayed_members_are_listed(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§9.8's *"mark session complete"* refreshes exactly this list, so a current member
        must not appear — the session would attest to practice that did not happen."""
        state = self._state(
            player,
            milestone_state,
            comfortable_4_way_switches=45,
            consistent_overhead_prayers=1,
            freeze_logging_practice=120,
        )

        candidates = practice_candidates(state, seed_content, profile, now)

        assert candidates[0].members == ("comfortable_4_way_switches", "freeze_logging_practice")

    def test_an_unachieved_milestone_is_not_decayed(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """Acquiring a skill is progression, not maintenance. Coaching someone to refresh
        what they have never claimed would also let practice evidence stand in for the
        attestation itself, which G7 forbids."""
        state = player(
            milestones=[
                milestone_state(key, achieved=False, practiced_days_ago=200) for key in NH_GROUP
            ]
        )

        assert practice_candidates(state, seed_content, profile, now) == ()

    def test_the_authored_hours_ride_along(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """A8 — the mandatory ``suggested_session_hours``, which is what stops a refresher
        scoring a perfect ``effort_decay``."""
        state = self._state(player, milestone_state, comfortable_4_way_switches=45)

        candidate = practice_candidates(state, seed_content, profile, now)[0]

        assert candidate.hours > 0
        assert candidate.hours == seed_content.refreshers[candidate.id].suggested_session_hours

    def test_groups_are_returned_most_urgent_first(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """The list policy keeps the first refresher, so ordering decides which group is
        surfaced when two have decayed."""
        state = player(
            milestones=[
                milestone_state("comfortable_4_way_switches", practiced_days_ago=35),
                milestone_state("vengeance_timing", practiced_days_ago=300),
            ]
        )

        candidates = practice_candidates(state, seed_content, profile, now)

        assert [entry.id for entry in candidates] == [
            "refresh_vengeance_fundamentals",
            "refresh_nh_fundamentals",
        ]

    def test_a_group_advances_the_capabilities_its_template_names(
        self,
        player: Callable[..., PlayerState],
        milestone_state: Callable[..., MilestoneState],
        seed_content: Content,
        profile: ScoringProfile,
        now: datetime,
    ) -> None:
        """§9.8: the composite *"inherits the maximum relevant capability value, never the
        sum"* — so the map it carries is a plain membership statement, one entry per
        capability the template serves, with the maximum taken downstream."""
        state = self._state(player, milestone_state, vengeance_timing=100)

        candidate = practice_candidates(state, seed_content, profile, now)[0]

        assert candidate.advances == {"vengeance_pvp": 1.0}


class TestListPolicy:
    """**G10** — *"at most one refresher in the primary recommendation list"* (§9.8)."""

    def _entry(self, candidate_id: str, kind: CandidateKind) -> Recommendation:
        return Recommendation(candidate_id=candidate_id, name=candidate_id, kind=kind, score=1.0)

    def test_the_second_refresher_is_deferred(self, profile: ScoringProfile) -> None:
        ranked = [
            self._entry("refresh_a", CandidateKind.PRACTICE),
            self._entry("train_magic", CandidateKind.SKILL_TRAINING),
            self._entry("refresh_b", CandidateKind.PRACTICE),
        ]

        primary, deferred = enforce_list_policy(ranked, profile)

        assert [entry.candidate_id for entry in primary] == ["refresh_a", "train_magic"]
        assert [entry.candidate_id for entry in deferred] == ["refresh_b"]

    def test_progression_candidates_are_never_capped(self, profile: ScoringProfile) -> None:
        ranked = [self._entry(f"c{index}", CandidateKind.SKILL_TRAINING) for index in range(6)]

        primary, deferred = enforce_list_policy(ranked, profile)

        assert len(primary) == 6
        assert deferred == ()

    def test_the_kept_refresher_is_the_highest_ranked_one(self, profile: ScoringProfile) -> None:
        """The cap is applied after scoring, so *which* refresher survives is decided by the
        ranking rather than by corpus declaration order."""
        ranked = [
            self._entry("refresh_best", CandidateKind.PRACTICE),
            self._entry("refresh_worse", CandidateKind.PRACTICE),
        ]

        primary, deferred = enforce_list_policy(ranked, profile)

        assert [entry.candidate_id for entry in primary] == ["refresh_best"]
        assert [entry.candidate_id for entry in deferred] == ["refresh_worse"]

    def test_the_cap_is_authored(self, make_profile: Callable[..., ScoringProfile]) -> None:
        """§9.7 puts the count in ``profile.yaml``, so §9.8's policy is tunable content."""
        ranked = [self._entry(f"refresh_{index}", CandidateKind.PRACTICE) for index in range(3)]

        primary, _ = enforce_list_policy(
            ranked, make_profile(refresher=RefresherPolicy(max_in_primary_list=2))
        )

        assert len(primary) == 2


def test_the_urgency_curve_meets_the_freshness_policy_at_both_seams(
    milestone_state: Callable[..., MilestoneState], now: datetime
) -> None:
    """The bands and the curve must not drift apart.

    §9.8's urgency is defined *in terms of* §6.6's freshness bands, so the day a milestone
    becomes stale is the day it becomes urgent. Importing the boundaries rather than
    restating them is what makes this hold; the test is here so a future edit that inlines
    ``30`` and ``90`` fails loudly.
    """
    just_current = milestone_state("x", practiced_days_ago=0)
    at_stale = milestone_state("x", practiced_days_ago=STALE_AFTER.days)
    just_before = milestone_state("x", practiced_days_ago=STALE_AFTER.days - 1)
    past_very_stale = milestone_state("x", practiced_days_ago=VERY_STALE_AFTER.days + 1)

    assert member_urgency(just_current, now) == 0.0
    assert member_urgency(just_before, now) == 0.0
    assert member_urgency(at_stale, now) == pytest.approx(0.40)
    assert member_urgency(past_very_stale, now) > 0.70


def test_a_practice_age_in_the_future_is_not_urgent(
    milestone_state: Callable[..., MilestoneState], now: datetime
) -> None:
    """Clock skew between the plugin and the server is not evidence of decay."""
    state = milestone_state("x", practiced_days_ago=0)
    tomorrow = MilestoneState(
        key=state.key,
        achieved=True,
        attested=state.attested,
        kind=state.kind,
        class_=state.class_,
        last_practiced_at=now + timedelta(days=1),
    )

    assert member_urgency(tomorrow, now) == 0.0
