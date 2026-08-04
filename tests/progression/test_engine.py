"""The three status layers (§4.4, §6.9, §9.2, D8).

The two invariants this step owns are proved here, by test rather than by inspection:

* **G2** — freshness never influences ``status``.
* **G3** — an ``unknown`` leaf never becomes ``unlocked``, and never reaches
  ``readiness_confidence``.

Everything else in this file is a generator: ``recommended_now``, its reason, and the
three warning sources. They are the design's coaching voice, and §6.9 specifies them as
*generated, never authored*.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import (
    AllOf,
    AnyOf,
    CapabilityLeaf,
    ItemLeaf,
    MilestoneLeaf,
    Not,
    QuestLeaf,
    SkillLeaf,
    UnlockLeaf,
)
from tracker.content.schema import Capability, Item, Milestone, Quest, ScoringProfile, Skill
from tracker.domain.types import (
    CapabilityView,
    Confidence,
    Container,
    ItemObservation,
    MilestoneClass,
    MilestoneKind,
    MilestoneState,
    PlayerState,
    QuestStatus,
    SkillState,
    Status,
    Tri,
    UnlockState,
)
from tracker.progression.engine import compute_capability_states

NOW = datetime.fromisoformat("2026-08-04T00:00:00+00:00")

MAGIC = Skill(id="magic", name="Magic")
DEFENCE = Skill(id="defence", name="Defence")
DT1 = Quest(id="desert_treasure_i", name="Desert Treasure I")
VOIDWAKER = Item(id="voidwaker", name="Voidwaker", item_id=27690)
AGS = Item(id="armadyl_godsword", name="Armadyl godsword", item_id=11802)

SWITCHES = Milestone(
    id="comfortable_4_way_switches",
    name="Comfortable 4-way switches",
    **{"class": MilestoneClass.EXECUTION},
    kind=MilestoneKind.SELF_ATTESTED,
    practice_group="nh_fundamentals",
)
TELEBLOCK = Milestone(
    id="teleblock_understanding",
    name="Teleblock understanding",
    **{"class": MilestoneClass.KNOWLEDGE},
    kind=MilestoneKind.SELF_ATTESTED,
)

ContentFactory = Callable[..., Content]


def state(**kwargs: object) -> PlayerState:
    return PlayerState(player_id=1, **kwargs)  # type: ignore[arg-type]


class TestStatusIsObjective:
    """G2 — *"``status`` is objective; never influenced by freshness"* (§6.9, D8)."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(
            milestones=[SWITCHES],
            capabilities=[
                Capability(
                    id="nh",
                    name="NH",
                    requires=MilestoneLeaf(key="comfortable_4_way_switches"),
                )
            ],
        )

    def view(
        self,
        content: Content,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
        practiced_days_ago: int,
    ) -> CapabilityView:
        player = state(
            milestones={
                "comfortable_4_way_switches": milestone_state(
                    "comfortable_4_way_switches", practiced_days_ago=practiced_days_ago
                )
            }
        )
        return compute_capability_states(player, content, profile, NOW)["nh"]

    def test_a_very_stale_milestone_moves_readiness_and_nothing_else(
        self,
        content: Content,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        """The G2 proof: same account, different practice age, byte-identical status.

        Everything objective — ``status``, ``unlock_fraction``, ``blockers``,
        ``unknowns`` — must be indistinguishable between the two runs. Only the
        freshness-derived layers may differ.
        """
        fresh = self.view(content, profile, milestone_state, practiced_days_ago=1)
        decayed = self.view(content, profile, milestone_state, practiced_days_ago=400)

        objective = ("status", "unlock_fraction", "blockers", "unknowns")
        assert {field: getattr(fresh, field) for field in objective} == {
            field: getattr(decayed, field) for field in objective
        }
        assert fresh.status is Status.UNLOCKED
        assert fresh.readiness_confidence is Confidence.HIGH
        assert decayed.readiness_confidence is Confidence.LOW

    @pytest.mark.parametrize(
        ("practiced_days_ago", "expected"),
        [
            (0, Confidence.HIGH),
            (29, Confidence.HIGH),
            (30, Confidence.MEDIUM),
            (89, Confidence.MEDIUM),
            (91, Confidence.LOW),
        ],
    )
    def test_the_confidence_table(
        self,
        content: Content,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
        practiced_days_ago: int,
        expected: Confidence,
    ) -> None:
        """§6.9's table, driven through §6.6's bands."""
        view = self.view(content, profile, milestone_state, practiced_days_ago)
        assert view.status is Status.UNLOCKED
        assert view.readiness_confidence is expected

    def test_staleness_never_sets_achieved_false(
        self,
        content: Content,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        """D8/G1 — a decade-old practice record still leaves the capability unlocked."""
        view = self.view(content, profile, milestone_state, practiced_days_ago=3650)
        assert view.status is Status.UNLOCKED
        assert view.unlock_fraction == 1.0


class TestUnknownNeverBecomesUnlocked:
    """G3 — unknown evidence stops at ``status`` (§9.2, §6.9, D8)."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(
            items=[VOIDWAKER],
            capabilities=[
                Capability(
                    id="voidwaker_nh", name="Voidwaker NH", requires=ItemLeaf(item_id="voidwaker")
                )
            ],
        )

    def test_an_unknown_item_leaf_yields_unknown_status_and_no_confidence(
        self, content: Content, profile: ScoringProfile
    ) -> None:
        """§4.4's third worked example, exactly.

        The forbidden output is *"Unlocked: yes / Confidence: low because ownership is
        unknown"*. It must be unrepresentable, not merely unwritten.
        """
        view = compute_capability_states(state(), content, profile, NOW)["voidwaker_nh"]
        assert view.status is Status.UNKNOWN
        assert view.readiness_confidence is None
        assert view.recommended_now is False
        assert view.recommended_now_reason == "bank contents have never been observed"

    @pytest.mark.parametrize("days_ago", [0, 400])
    def test_no_view_ever_pairs_unlocked_with_a_missing_observation(
        self,
        content: Content,
        profile: ScoringProfile,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
        days_ago: int,
    ) -> None:
        """However aged the evidence, ``unlocked`` requires evidence to exist."""
        player = state(
            observed_items={27690: owned(27690)}, container_scans=scans(days_ago=days_ago)
        )
        view = compute_capability_states(player, content, profile, NOW)["voidwaker_nh"]
        assert view.status is Status.UNLOCKED
        assert view.readiness_confidence is not None

    def test_confidence_is_none_for_every_status_other_than_unlocked(
        self,
        content: Content,
        profile: ScoringProfile,
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        locked = compute_capability_states(state(container_scans=scans()), content, profile, NOW)[
            "voidwaker_nh"
        ]
        assert locked.status is Status.LOCKED
        assert locked.readiness_confidence is None


class TestUnlockFraction:
    """§6.9 + A3, through the engine."""

    def test_one_of_each_is_a_third(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        skill_at: Callable[..., SkillState],
    ) -> None:
        content = build_content(
            skills=[MAGIC, DEFENCE],
            capabilities=[
                Capability(
                    id="mixed",
                    name="Mixed",
                    requires=AllOf(
                        children=(
                            SkillLeaf(skill="magic", level=94),  # satisfied
                            SkillLeaf(skill="magic", level=99),  # unsatisfied
                            SkillLeaf(skill="defence", level=75),  # unknown
                        )
                    ),
                )
            ],
        )
        view = compute_capability_states(
            state(skills={"magic": skill_at(94)}), content, profile, NOW
        )["mixed"]
        assert round(view.unlock_fraction, 2) == 0.33
        assert view.status is Status.LOCKED


class TestRecommendedNow:
    """``recommended_now = status == unlocked AND confidence >= bar`` (§6.9, A9)."""

    def content_with_bar(self, build_content: ContentFactory, bar: Confidence) -> Content:
        return build_content(
            milestones=[SWITCHES],
            capabilities=[
                Capability(
                    id="nh",
                    name="NH",
                    requires=MilestoneLeaf(key="comfortable_4_way_switches"),
                    recommended_readiness=bar,
                )
            ],
        )

    @pytest.mark.parametrize(
        ("bar", "practiced_days_ago", "expected"),
        [
            (Confidence.MEDIUM, 1, True),
            (Confidence.MEDIUM, 45, True),  # stale → medium, which meets a medium bar
            (Confidence.MEDIUM, 400, False),  # very_stale → low
            (Confidence.HIGH, 1, True),
            (Confidence.HIGH, 45, False),  # §6.9's advanced-capability case
        ],
    )
    def test_the_threshold_comparison(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
        bar: Confidence,
        practiced_days_ago: int,
        expected: bool,
    ) -> None:
        content = self.content_with_bar(build_content, bar)
        player = state(
            milestones={
                "comfortable_4_way_switches": milestone_state(
                    "comfortable_4_way_switches", practiced_days_ago=practiced_days_ago
                )
            }
        )
        view = compute_capability_states(player, content, profile, NOW)["nh"]
        assert view.recommended_now is expected

    def test_a_capability_below_its_bar_suggests_a_refresher(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        """§6.9: *"discouraging deployment without revoking progress."*"""
        content = self.content_with_bar(build_content, Confidence.HIGH)
        player = state(
            milestones={
                "comfortable_4_way_switches": milestone_state(
                    "comfortable_4_way_switches", practiced_days_ago=45
                )
            }
        )
        view = compute_capability_states(player, content, profile, NOW)["nh"]
        assert view.status is Status.UNLOCKED
        assert view.recommended_now_reason == "complete a refresher session first"

    def test_a_recommended_capability_has_no_reason(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        content = self.content_with_bar(build_content, Confidence.MEDIUM)
        player = state(
            milestones={"comfortable_4_way_switches": milestone_state("comfortable_4_way_switches")}
        )
        view = compute_capability_states(player, content, profile, NOW)["nh"]
        assert view.recommended_now is True
        assert view.recommended_now_reason is None


class TestReasonGenerators:
    """§6.9's three cases, *generated, never authored* (A10)."""

    def test_locked_names_the_highest_value_blocker(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        skill_at: Callable[..., SkillState],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """§6.9's own example phrase: *"requires 94 Magic"*."""
        content = build_content(
            skills=[MAGIC, DEFENCE],
            items=[VOIDWAKER],
            capabilities=[
                Capability(
                    id="barrage",
                    name="Barrage",
                    requires=AllOf(
                        children=(
                            ItemLeaf(item_id="voidwaker"),
                            SkillLeaf(skill="defence", level=75),
                            SkillLeaf(skill="magic", level=94),
                        )
                    ),
                )
            ],
        )
        player = state(
            skills={"magic": skill_at(80), "defence": skill_at(70)}, container_scans=scans()
        )
        view = compute_capability_states(player, content, profile, NOW)["barrage"]
        assert view.status is Status.LOCKED
        assert view.recommended_now_reason == "requires 94 Magic"

    def test_a_locked_prerequisite_capability_is_named_first(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        skill_at: Callable[..., SkillState],
    ) -> None:
        """A locked prerequisite subsumes a whole subtree, so it is the useful thing to say."""
        content = build_content(
            skills=[MAGIC, DEFENCE],
            capabilities=[
                Capability(
                    id="barrage", name="Ice Barrage NH", requires=SkillLeaf(skill="magic", level=94)
                ),
                Capability(
                    id="deep",
                    name="Deep Wilderness NH",
                    requires=AllOf(
                        children=(
                            SkillLeaf(skill="defence", level=75),
                            CapabilityLeaf(capability_id="barrage"),
                        )
                    ),
                ),
            ],
        )
        player = state(skills={"magic": skill_at(80), "defence": skill_at(70)})
        view = compute_capability_states(player, content, profile, NOW)["deep"]
        assert view.recommended_now_reason == "requires Ice Barrage NH"

    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            (SkillLeaf(skill="magic", level=94), "your Magic level has never been observed"),
            (
                UnlockLeaf(key="ancient_magicks"),
                "whether you have Ancient Magicks has never been observed",
            ),
            (ItemLeaf(item_id="voidwaker"), "bank contents have never been observed"),
            (
                QuestLeaf(quest_id="desert_treasure_i"),
                "your progress in Desert Treasure I has never been observed",
            ),
            (
                MilestoneLeaf(key="comfortable_4_way_switches"),
                "you have never been asked about comfortable 4-way switches",
            ),
        ],
    )
    def test_unknown_names_the_unobserved_evidence(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        requirement: object,
        expected: str,
    ) -> None:
        """§4.4: *"no — bank contents have never been observed"*, never *"you don't have it"*."""
        content = build_content(
            skills=[MAGIC],
            quests=[DT1],
            items=[VOIDWAKER],
            milestones=[SWITCHES],
            capabilities=[Capability(id="c", name="C", requires=requirement)],  # type: ignore[arg-type]
        )
        view = compute_capability_states(state(), content, profile, NOW)["c"]
        assert view.status is Status.UNKNOWN
        assert view.recommended_now_reason == expected

    def test_an_item_that_cannot_be_matched_says_so(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """Every container scanned, and the leaf is *still* unknown: the authored item
        carries no numeric id, so no observation could ever refer to it (§10.5)."""
        content = build_content(
            items=[Item(id="mystery", name="Mystery")],
            capabilities=[Capability(id="c", name="C", requires=ItemLeaf(item_id="mystery"))],
        )
        view = compute_capability_states(state(container_scans=scans()), content, profile, NOW)["c"]
        assert view.status is Status.UNKNOWN
        assert view.recommended_now_reason == "this item cannot be matched to an in-game item id"

    def test_a_negated_requirement_has_no_blocker_to_name(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        skill_at: Callable[..., SkillState],
    ) -> None:
        """``not`` is the one unsatisfied form the ``LeafRef`` vocabulary cannot express —
        *"get rid of this"* is not a to-do item — so the reason falls back to a statement
        of fact rather than inventing a blocker."""
        content = build_content(
            skills=[MAGIC],
            capabilities=[
                Capability(id="c", name="C", requires=Not(child=SkillLeaf(skill="magic", level=94)))
            ],
        )
        view = compute_capability_states(
            state(skills={"magic": skill_at(99)}), content, profile, NOW
        )["c"]
        assert view.status is Status.LOCKED
        assert view.blockers == ()
        assert view.recommended_now_reason == "its requirements are not met"

    def test_an_unsynced_account_says_so(
        self, seed_content: Content, profile: ScoringProfile
    ) -> None:
        view = compute_capability_states(state(), seed_content, profile, NOW)["budget_nh"]
        assert view.recommended_now_reason == "this account has never been synced"


class TestWarnings:
    """§6.9's three generators (A11). Warnings explain results; they never cause them."""

    def test_a_stale_contributing_milestone_warns(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        content = build_content(
            milestones=[SWITCHES],
            capabilities=[
                Capability(
                    id="nh", name="NH", requires=MilestoneLeaf(key="comfortable_4_way_switches")
                )
            ],
        )
        player = state(
            milestones={
                "comfortable_4_way_switches": milestone_state(
                    "comfortable_4_way_switches", practiced_days_ago=100
                )
            }
        )
        view = compute_capability_states(player, content, profile, NOW)["nh"]
        assert view.warnings == (
            "Comfortable 4-way switches was last practiced 3 months ago (very stale)",
        )

    def test_an_aged_observation_is_phrased_as_age_not_absence(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """§6.5: *"last saw your bank 3 weeks ago"*, never *"you don't have a Voidwaker."*"""
        content = build_content(
            items=[VOIDWAKER],
            capabilities=[Capability(id="c", name="C", requires=ItemLeaf(item_id="voidwaker"))],
        )
        player = state(
            observed_items={27690: owned(27690)},
            container_scans=scans(days_ago=21, containers=[Container.BANK])
            | scans(containers=[Container.INVENTORY, Container.EQUIPMENT]),
        )
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.warnings == ("last saw your bank 3 weeks ago",)
        assert view.readiness_confidence is Confidence.MEDIUM

    def test_a_fresh_observation_does_not_warn(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """A4 — the threshold is ``observation_aged_days``, a profile value (default 14)."""
        content = build_content(
            items=[VOIDWAKER],
            capabilities=[Capability(id="c", name="C", requires=ItemLeaf(item_id="voidwaker"))],
        )
        player = state(observed_items={27690: owned(27690)}, container_scans=scans(days_ago=13))
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.warnings == ()
        assert view.readiness_confidence is Confidence.HIGH

    def test_two_aged_items_in_one_container_produce_one_warning(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """Three stale items in the same bank scan are one fact about the bank."""
        content = build_content(
            items=[VOIDWAKER, AGS],
            capabilities=[
                Capability(
                    id="c",
                    name="C",
                    requires=AllOf(
                        children=(
                            ItemLeaf(item_id="voidwaker"),
                            ItemLeaf(item_id="armadyl_godsword"),
                        )
                    ),
                )
            ],
        )
        player = state(
            observed_items={27690: owned(27690), 11802: owned(11802)},
            container_scans=scans(days_ago=30),
        )
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.warnings == ("last saw your bank 4 weeks ago",)

    def test_a_knowledge_milestone_gets_a_note_and_no_readiness_effect(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        """§6.6 permits the note and forbids the effect. Both halves are asserted here."""
        content = build_content(
            milestones=[TELEBLOCK],
            capabilities=[
                Capability(id="c", name="C", requires=MilestoneLeaf(key="teleblock_understanding"))
            ],
        )
        player = state(
            milestones={
                "teleblock_understanding": milestone_state(
                    "teleblock_understanding",
                    class_=MilestoneClass.KNOWLEDGE,
                    practiced_days_ago=400,
                )
            }
        )
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.warnings == (
            "Teleblock understanding was last practiced 13 months ago "
            "(informational — knowledge milestones never affect readiness)",
        )
        assert view.readiness_confidence is Confidence.HIGH

    def test_a_recently_practiced_knowledge_milestone_gets_no_note(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        content = build_content(
            milestones=[TELEBLOCK],
            capabilities=[
                Capability(id="c", name="C", requires=MilestoneLeaf(key="teleblock_understanding"))
            ],
        )
        player = state(
            milestones={
                "teleblock_understanding": milestone_state(
                    "teleblock_understanding",
                    class_=MilestoneClass.KNOWLEDGE,
                    practiced_days_ago=3,
                )
            }
        )
        assert compute_capability_states(player, content, profile, NOW)["c"].warnings == ()

    def test_an_observation_with_no_container_attribution_does_not_downgrade(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """An observation nobody could attribute to a container has no age to report, and
        an unestablished age is not a decayed one (G6)."""
        content = build_content(
            items=[VOIDWAKER],
            capabilities=[Capability(id="c", name="C", requires=ItemLeaf(item_id="voidwaker"))],
        )
        player = state(
            observed_items={
                27690: ItemObservation(
                    item_id=27690,
                    quantity=1,
                    containers=frozenset(),
                    observed_at=NOW - timedelta(days=400),
                )
            },
            container_scans=scans(days_ago=400),
        )
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.status is Status.UNLOCKED
        assert view.readiness_confidence is Confidence.HIGH
        assert view.warnings == ()

    def test_a_leaf_under_an_unsatisfied_sibling_never_warns(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        skill_at: Callable[..., SkillState],
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """§6.9's exclusion clause, verbatim: *"a leaf under an unsatisfied sibling …
        never affects readiness."*

        The capability is unlocked through 94 Magic. The year-old Armadyl godsword sits
        in a branch that failed on its Magic requirement, so it played no part and must
        not drag readiness down with it.
        """
        content = build_content(
            skills=[MAGIC],
            items=[AGS],
            capabilities=[
                Capability(
                    id="c",
                    name="C",
                    requires=AnyOf(
                        children=(
                            AllOf(
                                children=(
                                    ItemLeaf(item_id="armadyl_godsword"),
                                    SkillLeaf(skill="magic", level=99),
                                )
                            ),
                            SkillLeaf(skill="magic", level=94),
                        )
                    ),
                )
            ],
        )
        player = state(
            skills={"magic": skill_at(94)},
            observed_items={11802: owned(11802)},
            container_scans=scans(days_ago=365),
        )
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.readiness_confidence is Confidence.HIGH
        assert view.warnings == ()

    def test_every_satisfied_alternative_contributes(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """Two alternatives that *both* hold are both contributing (§6.9).

        §6.9 defines contributing as the leaves reached by the walk that evaluated
        ``satisfied``, and excludes only *losing* branches. An alternative the player
        actually owns is not a losing branch, so its aged bank scan counts — the
        conservative direction, and the one the words say.
        """
        content = build_content(
            items=[VOIDWAKER, AGS],
            capabilities=[
                Capability(
                    id="c",
                    name="C",
                    requires=AnyOf(
                        children=(
                            ItemLeaf(item_id="voidwaker"),
                            ItemLeaf(item_id="armadyl_godsword"),
                        )
                    ),
                )
            ],
        )
        player = state(
            observed_items={
                27690: owned(27690, containers=[Container.EQUIPMENT]),
                11802: owned(11802, containers=[Container.BANK]),
            },
            container_scans=scans(days_ago=365, containers=[Container.BANK])
            | scans(containers=[Container.INVENTORY, Container.EQUIPMENT]),
        )
        view = compute_capability_states(player, content, profile, NOW)["c"]
        assert view.readiness_confidence is Confidence.MEDIUM
        assert view.warnings == ("last saw your bank 12 months ago",)

    def test_a_never_practiced_milestone_does_not_warn_or_downgrade(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        """G6 — absent evidence never accelerates staleness (§7.6)."""
        content = build_content(
            milestones=[SWITCHES],
            capabilities=[
                Capability(
                    id="nh", name="NH", requires=MilestoneLeaf(key="comfortable_4_way_switches")
                )
            ],
        )
        player = state(
            milestones={
                "comfortable_4_way_switches": milestone_state(
                    "comfortable_4_way_switches", practiced_days_ago=None
                )
            }
        )
        view = compute_capability_states(player, content, profile, NOW)["nh"]
        assert view.readiness_confidence is Confidence.HIGH
        assert view.warnings == ()


class TestTransitiveReadiness:
    """§6.9's readiness walk is *transitive* — it reaches through ``capability:`` leaves."""

    def test_a_stale_milestone_in_a_prerequisite_lowers_the_dependant(
        self,
        build_content: ContentFactory,
        profile: ScoringProfile,
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        content = build_content(
            milestones=[SWITCHES],
            capabilities=[
                Capability(
                    id="basics",
                    name="Basics",
                    requires=MilestoneLeaf(key="comfortable_4_way_switches"),
                ),
                Capability(
                    id="advanced", name="Advanced", requires=CapabilityLeaf(capability_id="basics")
                ),
            ],
        )
        player = state(
            milestones={
                "comfortable_4_way_switches": milestone_state(
                    "comfortable_4_way_switches", practiced_days_ago=100
                )
            }
        )
        views = compute_capability_states(player, content, profile, NOW)
        assert views["basics"].readiness_confidence is Confidence.LOW
        assert views["advanced"].readiness_confidence is Confidence.LOW
        assert views["advanced"].unlock_fraction == 1.0


class TestSeedCorpus:
    """§4.4's worked examples, computed from the shipped corpus (§16.4)."""

    @pytest.fixture
    def geared_player(
        self,
        seed_content: Content,
        skill_at: Callable[..., SkillState],
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
        milestone_state: Callable[..., MilestoneState],
    ) -> PlayerState:
        return state(
            skills={name: skill_at(99) for name in seed_content.skills},
            unlocks={
                "ancient_magicks": UnlockState.UNLOCKED,
                "spellbook_lunar": UnlockState.UNLOCKED,
            },
            quests=dict.fromkeys(seed_content.quests, QuestStatus.COMPLETE),
            observed_items={27690: owned(27690), 4091: owned(4091)},
            container_scans=scans(),
            milestones={
                milestone.id: milestone_state(
                    milestone.id,
                    kind=milestone.kind,
                    class_=milestone.class_,
                    practiced_days_ago=45,
                )
                for milestone in seed_content.milestones.values()
            },
            combat_level=126,
            quest_points=300,
            last_sync_at=NOW,
        )

    def test_every_capability_gets_a_view(
        self, seed_content: Content, profile: ScoringProfile
    ) -> None:
        views = compute_capability_states(state(), seed_content, profile, NOW)
        assert set(views) == set(seed_content.capabilities)

    def test_budget_wilderness_nh_is_unlocked_and_recommended(
        self, seed_content: Content, profile: ScoringProfile, geared_player: PlayerState
    ) -> None:
        """§4.4's first worked example: unlocked · medium · recommended now."""
        view = compute_capability_states(geared_player, seed_content, profile, NOW)["budget_nh"]
        assert view.status is Status.UNLOCKED
        assert view.readiness_confidence is Confidence.MEDIUM
        assert view.recommended_now is True

    def test_deep_wilderness_nh_is_unlocked_but_not_recommended(
        self, seed_content: Content, profile: ScoringProfile, geared_player: PlayerState
    ) -> None:
        """§4.4's second: the ``recommended_readiness: high`` capability holds its progress
        while declining to recommend the fight."""
        view = compute_capability_states(geared_player, seed_content, profile, NOW)["deep_wildy_nh"]
        assert view.status is Status.UNLOCKED
        assert view.readiness_confidence is Confidence.MEDIUM
        assert view.recommended_now is False
        assert view.recommended_now_reason == "complete a refresher session first"

    def test_an_unobserved_account_is_unknown_rather_than_locked(
        self, seed_content: Content, profile: ScoringProfile
    ) -> None:
        views = compute_capability_states(state(), seed_content, profile, NOW)
        assert views["ice_barrage_nh"].status is Status.UNKNOWN
        assert all(view.readiness_confidence is None for view in views.values())

    def test_the_views_are_ordered_and_frozen(
        self, seed_content: Content, profile: ScoringProfile
    ) -> None:
        views = compute_capability_states(state(), seed_content, profile, NOW)
        assert list(views) == sorted(views)
        with pytest.raises(dataclasses.FrozenInstanceError):
            views["ice_barrage_nh"].status = Status.UNLOCKED  # type: ignore[misc]

    def test_computation_is_repeatable(
        self, seed_content: Content, profile: ScoringProfile, geared_player: PlayerState
    ) -> None:
        """§16.1 — a pure function of ``(state, content, profile, now)``."""
        first = compute_capability_states(geared_player, seed_content, profile, NOW)
        second = compute_capability_states(geared_player, seed_content, profile, NOW)
        assert first == second

    def test_advancing_the_clock_moves_only_the_freshness_layers(
        self, seed_content: Content, profile: ScoringProfile, geared_player: PlayerState
    ) -> None:
        """G2 again, at corpus scale: a year of inactivity revokes nothing."""
        later = NOW + timedelta(days=365)
        now_views = compute_capability_states(geared_player, seed_content, profile, NOW)
        later_views = compute_capability_states(geared_player, seed_content, profile, later)

        assert {key: view.status for key, view in now_views.items()} == {
            key: view.status for key, view in later_views.items()
        }
        assert now_views["budget_nh"].readiness_confidence is Confidence.MEDIUM
        assert later_views["budget_nh"].readiness_confidence is Confidence.LOW


class TestTriIsNeverCoerced:
    """§9.1 — ``Tri.__bool__`` raises, so a hidden ``if tri:`` fails the whole suite.

    Every path above already exercises the guard; this states the intent so that a future
    edit reintroducing ``if not satisfied`` is read as breaking a rule rather than a test.
    """

    def test_the_guard_is_still_armed(self) -> None:
        with pytest.raises(TypeError, match="no truth value"):
            bool(Tri.UNKNOWN)
