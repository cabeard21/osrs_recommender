"""The shipped `content/` corpus: shape, the §6.6 milestone classification, and the
numbers §9.3's worked table depends on.

This is a test of *content*, not of code. It exists because the corpus is the fixture
every engine test downstream runs against, so a silent edit to a roadmap weight would
otherwise surface as an inexplicable ranking change three steps later.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from tracker.content.loader import Content
from tracker.content.validate import load_and_validate
from tracker.domain.types import Confidence, MilestoneClass, MilestoneKind

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"


@pytest.fixture(scope="module")
def content() -> Content:
    return load_and_validate(CONTENT_ROOT)


class TestShape:
    def test_the_shipped_corpus_validates(self, content: Content) -> None:
        assert content.profile.version == 2

    def test_capabilities(self, content: Content) -> None:
        assert set(content.capabilities) == {
            "ice_barrage_nh",
            "deep_wildy_nh",
            "budget_nh",
            "anti_pk",
            "vengeance_pvp",
        }

    def test_roadmaps(self, content: Content) -> None:
        assert set(content.roadmaps) == {"main_nh", "anti_pk"}

    def test_a_capability_and_a_roadmap_share_the_id_anti_pk(self, content: Content) -> None:
        """As §4.2 (capability) and §9.3 (roadmap) both use it."""
        assert "anti_pk" in content.capabilities
        assert "anti_pk" in content.roadmaps
        assert content.capabilities["anti_pk"].name == "Anti-PK"
        assert content.roadmaps["anti_pk"].name == "Anti-PKer"

    def test_deep_wildy_declares_the_high_readiness_bar(self, content: Content) -> None:
        """§6.9 — this is what makes decayed practice show as 'not today'."""
        assert content.capabilities["deep_wildy_nh"].recommended_readiness is Confidence.HIGH
        assert content.capabilities["budget_nh"].recommended_readiness is Confidence.MEDIUM


class TestMilestones:
    """§6.6's classification table, plus §10.3 and §6.6's separate-practice blockquote."""

    def test_every_milestone_in_the_classification_table_is_present(self, content: Content) -> None:
        assert set(content.milestones) == {
            "first_wilderness_kill",
            "first_anti_pk",
            "successfully_freeze_log",
            "lms_wins_10",
            "lms_wins_100",
            "teleblock_understanding",
            "comfortable_4_way_switches",
            "consistent_overhead_prayers",
            "freeze_logging_practice",
            "vengeance_timing",
        }

    @pytest.mark.parametrize(
        ("milestone_id", "expected"),
        [
            ("first_wilderness_kill", MilestoneClass.THRESHOLD),
            ("first_anti_pk", MilestoneClass.THRESHOLD),
            ("successfully_freeze_log", MilestoneClass.THRESHOLD),
            ("lms_wins_10", MilestoneClass.THRESHOLD),
            ("lms_wins_100", MilestoneClass.THRESHOLD),
            ("teleblock_understanding", MilestoneClass.KNOWLEDGE),
            ("comfortable_4_way_switches", MilestoneClass.EXECUTION),
            ("consistent_overhead_prayers", MilestoneClass.EXECUTION),
            ("freeze_logging_practice", MilestoneClass.EXECUTION),
            ("vengeance_timing", MilestoneClass.EXECUTION),
        ],
    )
    def test_classification_matches_the_sdd(
        self, content: Content, milestone_id: str, expected: MilestoneClass
    ) -> None:
        assert content.milestones[milestone_id].class_ is expected

    def test_freeze_logging_is_two_milestones(self, content: Content) -> None:
        """§6.6's blockquote: one row meaning both would make `achieved` ambiguous.

        The threshold one records that it happened and stays achieved forever; the
        execution one decays and drives refreshers.
        """
        achievement = content.milestones["successfully_freeze_log"]
        practice = content.milestones["freeze_logging_practice"]

        assert achievement.class_ is MilestoneClass.THRESHOLD
        assert achievement.practice_group is None
        assert practice.class_ is MilestoneClass.EXECUTION
        assert practice.practice_group == "nh_fundamentals"

    def test_the_self_attested_set_stays_small(self, content: Content) -> None:
        """§6.6 — keeping this small is what makes §2's 'almost no manual entry' true."""
        derived = {m.id for m in content.milestones.values() if m.kind is MilestoneKind.DERIVED}
        assert derived == {
            "first_wilderness_kill",
            "first_anti_pk",
            "lms_wins_10",
            "lms_wins_100",
        }

    def test_only_execution_milestones_belong_to_a_group(self, content: Content) -> None:
        for milestone in content.milestones.values():
            if milestone.practice_group is not None or milestone.practiced_by:
                assert milestone.class_ is MilestoneClass.EXECUTION, milestone.id

    def test_threshold_milestones_carry_their_target(self, content: Content) -> None:
        assert content.milestones["lms_wins_10"].threshold == 10
        assert content.milestones["lms_wins_100"].threshold == 100


class TestRefreshers:
    def test_both_groups_have_a_refresher_and_declared_hours(self, content: Content) -> None:
        """A8 — no hours means effort_decay = 1.0, a perfect effort score (G10)."""
        assert set(content.refreshers) == {
            "refresh_nh_fundamentals",
            "refresh_vengeance_fundamentals",
        }
        for refresher in content.refreshers.values():
            assert refresher.suggested_session_hours > 0

    def test_every_group_has_at_least_one_execution_member(self, content: Content) -> None:
        for refresher in content.refreshers.values():
            members = content.milestones_in_group(refresher.practice_group)
            assert any(m.class_ is MilestoneClass.EXECUTION for m in members)

    def test_nh_fundamentals_groups_three_milestones(self, content: Content) -> None:
        """§9.8's grouping exists because per-milestone refreshers are useless coaching."""
        members = {m.id for m in content.milestones_in_group("nh_fundamentals")}
        assert members == {
            "comfortable_4_way_switches",
            "consistent_overhead_prayers",
            "freeze_logging_practice",
        }


class TestTrainingMethods:
    def test_the_fast_magic_method_is_gated_and_the_default_is_not(self, content: Content) -> None:
        """§8.2 step 3 — the fast method is behind the content being sequenced."""
        fast = content.training_methods["magic_bursting"]
        default = content.training_methods["magic_conservative"]

        assert fast.requires is not None
        assert default.requires is None
        assert fast.xp_per_hour > default.xp_per_hour

    def test_methods_are_ordered_fastest_first(self, content: Content) -> None:
        assert [m.id for m in content.methods_for_skill("magic")] == [
            "magic_bursting",
            "magic_conservative",
        ]

    def test_every_method_resolves_to_a_declared_skill(self, content: Content) -> None:
        for method in content.training_methods.values():
            assert method.skill in content.skills


class TestBlending:
    """§9.3's worked table must reproduce from the shipped roadmaps, not from invented
    numbers — otherwise step 2.5's derivation tests prove nothing about this corpus."""

    SELECTION: ClassVar[dict[str, float]] = {"main_nh": 0.75, "anti_pk": 0.25}

    def effective_weight(self, content: Content, capability_id: str) -> float:
        return sum(
            selection_weight * content.roadmaps[roadmap_id].capabilities.get(capability_id, 0.0)
            for roadmap_id, selection_weight in self.SELECTION.items()
        )

    def test_selection_weights_already_sum_to_one(self) -> None:
        assert sum(self.SELECTION.values()) == pytest.approx(1.0)

    def test_train_magic_blends_to_zero_point_nine(self, content: Content) -> None:
        """ "Train Magic to 94" advances ice_barrage_nh: 0.75(1.00) + 0.25(0.60) = 0.90."""
        assert self.effective_weight(content, "ice_barrage_nh") == pytest.approx(0.90)

    def test_vengeance_practice_blends_to_zero_point_three_seven_five(
        self, content: Content
    ) -> None:
        """ "Practice vengeance timing": 0.75(0.20) + 0.25(0.90) = 0.375."""
        assert self.effective_weight(content, "vengeance_pvp") == pytest.approx(0.375)

    def test_blending_never_accumulates(self, content: Content) -> None:
        """D3 — a capability in two roadmaps blends; the sum would be 1.60 here."""
        weights = [
            content.roadmaps[roadmap_id].capabilities["ice_barrage_nh"]
            for roadmap_id in self.SELECTION
        ]
        assert sum(weights) > 1.0  # the naive sum leaves [0, 1]
        assert 0.0 <= self.effective_weight(content, "ice_barrage_nh") <= 1.0


class TestScoringProfile:
    def test_matches_the_sdd_defaults(self, content: Content) -> None:
        profile = content.profile
        assert profile.tau_hours == 10
        assert (profile.kappa_gp.high, profile.kappa_gp.normal, profile.kappa_gp.low) == (
            8_000_000,
            20_000_000,
            50_000_000,
        )
        assert profile.observation_aged_days == 14  # A4
        assert profile.weights.pvp_value == 1.0
        assert profile.weights.leverage == 0.8
        assert profile.weights.proximity == 0.6
        assert profile.weights.effort_decay == 0.7
        assert profile.weights.cost_decay == 0.5
        assert profile.weights.method_unlock == 0.1  # A30 — live in v2 (D4)
        assert profile.refresher.max_in_primary_list == 1  # G10
        assert profile.refresher.breadth_bonus_cap == 0.10

    def test_is_declared_tuned_against_a_named_corpus(self, content: Content) -> None:
        """§16.3 step 7 — a tuned profile must name the corpus it was tuned against.

        The point is traceability, not the specific hash: a weight vector with no corpus
        behind it is indistinguishable from a guess, which is exactly what ``version: 1``
        declared by leaving this ``None``.
        """
        assert content.profile.tuned_against_corpus == "b978d44"
