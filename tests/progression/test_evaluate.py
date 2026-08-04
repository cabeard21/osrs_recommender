"""Leaf resolution and result assembly (§9.1, §6.9, A3, A5, A6, A7).

There is one test class per row of §9.1's leaf resolution table, because a row that is
silently wrong produces recommendations that look plausible forever. The two rows whose
plain-English reading is misleading — ``unlock: available`` and ``quest: in_progress`` —
get their own explicit tests saying so.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import (
    AllOf,
    AnyOf,
    AtLeast,
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MilestoneLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
)
from tracker.content.schema import Capability, Item, Milestone, Quest, Skill
from tracker.domain.types import (
    Container,
    ItemObservation,
    LeafRef,
    MilestoneClass,
    MilestoneKind,
    MilestoneState,
    PlayerState,
    QuestStatus,
    SkillState,
    Tri,
    UnlockState,
)
from tracker.progression.evaluate import (
    EvalResult,
    Evaluator,
    RequirementCycleError,
    evaluate,
)

NOW = datetime.fromisoformat("2026-08-04T00:00:00+00:00")

MAGIC = Skill(id="magic", name="Magic")
DEFENCE = Skill(id="defence", name="Defence")
DT1 = Quest(id="desert_treasure_i", name="Desert Treasure I")
VOIDWAKER = Item(id="voidwaker", name="Voidwaker", item_id=27690)
AGS = Item(id="armadyl_godsword", name="Armadyl godsword", item_id=11802)
UNTRACKED = Item(id="untracked", name="Untracked trinket")
SWITCHES = Milestone(
    id="comfortable_4_way_switches",
    name="Comfortable 4-way switches",
    **{"class": MilestoneClass.EXECUTION},
    kind=MilestoneKind.SELF_ATTESTED,
    practice_group="nh_fundamentals",
)
FIRST_ANTI_PK = Milestone(
    id="first_anti_pk",
    name="First anti-PK",
    **{"class": MilestoneClass.THRESHOLD},
    kind=MilestoneKind.DERIVED,
)

ContentFactory = Callable[..., Content]


def state(**kwargs: object) -> PlayerState:
    return PlayerState(player_id=1, **kwargs)  # type: ignore[arg-type]


class TestSkillLeaf:
    """§9.1: satisfied at or above the target, unsatisfied below, unknown with no snapshot."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(skills=[MAGIC])

    @pytest.mark.parametrize(
        ("level", "expected"), [(94, Tri.SATISFIED), (99, Tri.SATISFIED), (93, Tri.UNSATISFIED)]
    )
    def test_compares_against_the_target(
        self, content: Content, skill_at: Callable[..., SkillState], level: int, expected: Tri
    ) -> None:
        result = evaluate(
            SkillLeaf(skill="magic", level=94), state(skills={"magic": skill_at(level)}), content
        )
        assert result.value is expected

    def test_no_snapshot_from_any_source_is_unknown(self, content: Content) -> None:
        result = evaluate(SkillLeaf(skill="magic", level=94), state(), content)
        assert result.value is Tri.UNKNOWN

    def test_the_leaf_reference_names_the_target(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        result = evaluate(
            SkillLeaf(skill="magic", level=94), state(skills={"magic": skill_at(80)}), content
        )
        assert result.blockers == (LeafRef("skill", "magic", "94 Magic", 94),)


class TestUnlockLeaf:
    """§9.1 + A5. ``available`` reads as positive and is not."""

    @pytest.mark.parametrize(
        ("unlock_state", "expected"),
        [
            (UnlockState.UNLOCKED, Tri.SATISFIED),
            (UnlockState.AVAILABLE, Tri.UNSATISFIED),
            (UnlockState.LOCKED, Tri.UNSATISFIED),
            (UnlockState.UNKNOWN, Tri.UNKNOWN),
        ],
    )
    def test_every_state(
        self, build_content: ContentFactory, unlock_state: UnlockState, expected: Tri
    ) -> None:
        result = evaluate(
            UnlockLeaf(key="ancient_magicks"),
            state(unlocks={"ancient_magicks": unlock_state}),
            build_content(),
        )
        assert result.value is expected

    def test_available_is_unsatisfied_not_satisfied(self, build_content: ContentFactory) -> None:
        """A5 — *"available means purchasable, not held"* (§6.3). Rigour visible in the
        Prayer book is not Rigour unlocked."""
        result = evaluate(
            UnlockLeaf(key="rigour"),
            state(unlocks={"rigour": UnlockState.AVAILABLE}),
            build_content(),
        )
        assert result.value is Tri.UNSATISFIED
        assert result.blockers == (LeafRef("unlock", "rigour", "Rigour"),)

    def test_an_absent_entry_is_unknown(self, build_content: ContentFactory) -> None:
        assert evaluate(UnlockLeaf(key="rigour"), state(), build_content()).value is Tri.UNKNOWN


class TestQuestLeaf:
    """§9.1 + A5. ``in_progress`` is not partial credit."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(quests=[DT1])

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (QuestStatus.COMPLETE, Tri.SATISFIED),
            (QuestStatus.IN_PROGRESS, Tri.UNSATISFIED),
            (QuestStatus.NOT_STARTED, Tri.UNSATISFIED),
            (QuestStatus.UNKNOWN, Tri.UNKNOWN),
        ],
    )
    def test_every_status(self, content: Content, status: QuestStatus, expected: Tri) -> None:
        result = evaluate(
            QuestLeaf(quest_id="desert_treasure_i"),
            state(quests={"desert_treasure_i": status}),
            content,
        )
        assert result.value is expected

    def test_in_progress_is_unsatisfied(self, content: Content) -> None:
        """A5 — the grammar has no partial-credit leaf; progress is `unlock_fraction`."""
        result = evaluate(
            QuestLeaf(quest_id="desert_treasure_i"),
            state(quests={"desert_treasure_i": QuestStatus.IN_PROGRESS}),
            content,
        )
        assert result.value is Tri.UNSATISFIED
        assert result.blockers == (LeafRef("quest", "desert_treasure_i", "Desert Treasure I"),)


class TestItemLeaf:
    """§6.5's three-way ownership resolution."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(items=[VOIDWAKER, UNTRACKED])

    def test_seen_in_a_scan_is_satisfied(
        self,
        content: Content,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        result = evaluate(
            ItemLeaf(item_id="voidwaker"),
            state(observed_items={27690: owned(27690)}, container_scans=scans()),
            content,
        )
        assert result.value is Tri.SATISFIED

    def test_absent_from_a_fully_scanned_account_is_unsatisfied(
        self, content: Content, scans: Callable[..., dict[Container, datetime]]
    ) -> None:
        result = evaluate(ItemLeaf(item_id="voidwaker"), state(container_scans=scans()), content)
        assert result.value is Tri.UNSATISFIED
        assert result.blockers == (LeafRef("item", "voidwaker", "Voidwaker"),)

    def test_never_scanned_is_unknown(self, content: Content) -> None:
        """§6.5: *"no scan of that container has ever occurred"* — not "you don't own it"."""
        result = evaluate(ItemLeaf(item_id="voidwaker"), state(), content)
        assert result.value is Tri.UNKNOWN
        assert result.unknowns == (LeafRef("item", "voidwaker", "Voidwaker"),)

    def test_a_partially_scanned_account_is_still_unknown(
        self, content: Content, scans: Callable[..., dict[Container, datetime]]
    ) -> None:
        """An ``item:`` leaf names no container, so *"the container"* is all three.

        With equipment never scanned, *"you don't have a Voidwaker"* would be a guess
        about the one place nobody has looked (§4.5).
        """
        result = evaluate(
            ItemLeaf(item_id="voidwaker"),
            state(container_scans=scans(containers=[Container.BANK, Container.INVENTORY])),
            content,
        )
        assert result.value is Tri.UNKNOWN

    def test_ownership_counts_from_any_container(
        self,
        content: Content,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        result = evaluate(
            ItemLeaf(item_id="voidwaker"),
            state(
                observed_items={27690: owned(27690, containers=[Container.EQUIPMENT])},
                container_scans=scans(),
            ),
            content,
        )
        assert result.value is Tri.SATISFIED

    def test_an_item_with_no_numeric_id_is_unknown(
        self, content: Content, scans: Callable[..., dict[Container, datetime]]
    ) -> None:
        """No observation can ever refer to it (§10.5), so it is not a blocker."""
        result = evaluate(ItemLeaf(item_id="untracked"), state(container_scans=scans()), content)
        assert result.value is Tri.UNKNOWN


class TestMilestoneLeaf:
    """§9.1 + A7 — the unknown arm exists only for a self-attested milestone never prompted."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(milestones=[SWITCHES, FIRST_ANTI_PK])

    def test_achieved_is_satisfied(
        self, content: Content, milestone_state: Callable[..., MilestoneState]
    ) -> None:
        result = evaluate(
            MilestoneLeaf(key="comfortable_4_way_switches"),
            state(
                milestones={
                    "comfortable_4_way_switches": milestone_state("comfortable_4_way_switches")
                }
            ),
            content,
        )
        assert result.value is Tri.SATISFIED

    def test_attested_and_not_achieved_is_unsatisfied(
        self, content: Content, milestone_state: Callable[..., MilestoneState]
    ) -> None:
        """Asked, and the user said no — a real answer, not an absent one."""
        observed = milestone_state(
            "comfortable_4_way_switches", achieved=False, attested=Tri.UNSATISFIED
        )
        result = evaluate(
            MilestoneLeaf(key="comfortable_4_way_switches"),
            state(milestones={"comfortable_4_way_switches": observed}),
            content,
        )
        assert result.value is Tri.UNSATISFIED

    def test_self_attested_and_never_prompted_is_unknown(
        self, content: Content, milestone_state: Callable[..., MilestoneState]
    ) -> None:
        """A7 — ``attested_at IS NULL`` is a different fact from a declined prompt (§6.6)."""
        observed = milestone_state(
            "comfortable_4_way_switches", achieved=False, attested=Tri.UNKNOWN
        )
        result = evaluate(
            MilestoneLeaf(key="comfortable_4_way_switches"),
            state(milestones={"comfortable_4_way_switches": observed}),
            content,
        )
        assert result.value is Tri.UNKNOWN

    def test_a_missing_self_attested_row_is_unknown(self, content: Content) -> None:
        result = evaluate(MilestoneLeaf(key="comfortable_4_way_switches"), state(), content)
        assert result.value is Tri.UNKNOWN

    def test_a_missing_derived_row_is_unsatisfied(self, content: Content) -> None:
        """*"A derived milestone is never unknown for want of a prompt"* — nobody is asked
        about a hiscores counter, so absence means the counter has not got there."""
        result = evaluate(MilestoneLeaf(key="first_anti_pk"), state(), content)
        assert result.value is Tri.UNSATISFIED

    def test_a_derived_row_that_was_never_attested_is_still_unsatisfied(
        self, content: Content, milestone_state: Callable[..., MilestoneState]
    ) -> None:
        observed = milestone_state(
            "first_anti_pk",
            achieved=False,
            attested=Tri.UNKNOWN,
            kind=MilestoneKind.DERIVED,
            class_=MilestoneClass.THRESHOLD,
            practiced_days_ago=None,
        )
        result = evaluate(
            MilestoneLeaf(key="first_anti_pk"),
            state(milestones={"first_anti_pk": observed}),
            content,
        )
        assert result.value is Tri.UNSATISFIED


class TestCapabilityLeaf:
    """§9.1 — the child capability's ``status``, mirrored."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(
            skills=[MAGIC],
            capabilities=[
                Capability(
                    id="ice_barrage_nh",
                    name="Ice Barrage NH",
                    requires=SkillLeaf(skill="magic", level=94),
                )
            ],
        )

    @pytest.mark.parametrize(
        ("skills", "expected"),
        [
            ({"magic": 94}, Tri.SATISFIED),
            ({"magic": 80}, Tri.UNSATISFIED),
            ({}, Tri.UNKNOWN),
        ],
    )
    def test_mirrors_the_child_status(
        self,
        content: Content,
        skill_at: Callable[..., SkillState],
        skills: dict[str, int],
        expected: Tri,
    ) -> None:
        player = state(skills={name: skill_at(level) for name, level in skills.items()})
        result = evaluate(CapabilityLeaf(capability_id="ice_barrage_nh"), player, content)
        assert result.value is expected

    def test_the_child_counts_as_exactly_one_leaf(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        """``unlock_fraction`` is local (§6.9): the child publishes its own fraction."""
        result = evaluate(
            CapabilityLeaf(capability_id="ice_barrage_nh"),
            state(skills={"magic": skill_at(94)}),
            content,
        )
        assert (result.satisfied_leaves, result.total_leaves) == (1, 1)

    def test_the_blocker_names_the_capability_not_its_leaves(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        result = evaluate(
            CapabilityLeaf(capability_id="ice_barrage_nh"),
            state(skills={"magic": skill_at(80)}),
            content,
        )
        assert result.blockers == (LeafRef("capability", "ice_barrage_nh", "Ice Barrage NH"),)

    def test_contributing_reaches_through_the_child(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        """§6.9 calls the readiness walk *transitive*."""
        result = evaluate(
            CapabilityLeaf(capability_id="ice_barrage_nh"),
            state(skills={"magic": skill_at(94)}),
            content,
        )
        assert result.contributing == (
            LeafRef("capability", "ice_barrage_nh", "Ice Barrage NH"),
            LeafRef("skill", "magic", "94 Magic", 94),
        )

    def test_a_capability_with_no_requirements_is_satisfied(
        self, build_content: ContentFactory
    ) -> None:
        content = build_content(capabilities=[Capability(id="free", name="Free")])
        result = evaluate(CapabilityLeaf(capability_id="free"), state(), content)
        assert result.value is Tri.SATISFIED

    def test_an_undeclared_capability_is_unknown_not_a_crash(
        self, build_content: ContentFactory
    ) -> None:
        """§10.7 catches this at load; evaluation stays total rather than raising."""
        result = evaluate(CapabilityLeaf(capability_id="nonexistent"), state(), build_content())
        assert result.value is Tri.UNKNOWN


class TestMemoization:
    """A capability required twice is evaluated once (§4.1 — the graph is a DAG)."""

    class CountingSkills(dict[str, Skill]):
        """Counts lookups of the child's *requirement* — the work memoization saves."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self.lookups: list[str] = []

        def get(self, key: str, default: object = None) -> Skill | None:  # type: ignore[override]
            self.lookups.append(key)
            return super().get(key)

    def test_a_shared_prerequisite_is_evaluated_once(
        self, build_content: ContentFactory, skill_at: Callable[..., SkillState]
    ) -> None:
        shared = Capability(id="shared", name="Shared", requires=SkillLeaf(skill="magic", level=94))
        content = build_content(skills=[MAGIC], capabilities=[shared])
        counting = self.CountingSkills({"magic": MAGIC})
        content = dataclasses.replace(content, skills=counting)

        requirement = AllOf(
            children=(
                CapabilityLeaf(capability_id="shared"),
                CapabilityLeaf(capability_id="shared"),
            )
        )
        evaluate(requirement, state(skills={"magic": skill_at(94)}), content)

        assert counting.lookups == ["magic"]

    def test_one_evaluator_serves_many_capabilities(
        self, build_content: ContentFactory, skill_at: Callable[..., SkillState]
    ) -> None:
        content = build_content(
            skills=[MAGIC],
            capabilities=[
                Capability(id="a", name="A", requires=SkillLeaf(skill="magic", level=94)),
                Capability(id="b", name="B", requires=CapabilityLeaf(capability_id="a")),
            ],
        )
        evaluator = Evaluator(state(skills={"magic": skill_at(94)}), content)
        assert evaluator.capability("b").value is Tri.SATISFIED
        assert evaluator.capability("a") is evaluator.capability("a")


class TestCycleDetection:
    """A defensive backstop: §10.7 already proves the capability graph acyclic."""

    def test_a_cycle_raises_rather_than_recursing_to_death(
        self, build_content: ContentFactory
    ) -> None:
        content = build_content(
            capabilities=[
                Capability(id="a", name="A", requires=CapabilityLeaf(capability_id="b")),
                Capability(id="b", name="B", requires=CapabilityLeaf(capability_id="a")),
            ]
        )
        with pytest.raises(RequirementCycleError, match="a → b → a"):
            evaluate(CapabilityLeaf(capability_id="a"), state(), content)

    def test_a_self_reference_raises(self, build_content: ContentFactory) -> None:
        content = build_content(
            capabilities=[Capability(id="a", name="A", requires=CapabilityLeaf(capability_id="a"))]
        )
        with pytest.raises(RequirementCycleError):
            evaluate(CapabilityLeaf(capability_id="a"), state(), content)


class TestNumericLeaves:
    """``combat_level`` and ``quest_points`` (§9.1, A6)."""

    @pytest.mark.parametrize(
        ("combat_level", "expected"),
        [(100, Tri.SATISFIED), (90, Tri.SATISFIED), (89, Tri.UNSATISFIED)],
    )
    def test_combat_level_compares_against_the_target(
        self, build_content: ContentFactory, combat_level: int, expected: Tri
    ) -> None:
        player = state(combat_level=combat_level, last_sync_at=NOW)
        assert evaluate(CombatLevelLeaf(level=90), player, build_content()).value is expected

    def test_combat_level_is_unknown_when_the_account_was_never_synced(
        self, build_content: ContentFactory
    ) -> None:
        """A6 — ``last_sync_at IS NULL``, not "your combat level is 0"."""
        result = evaluate(CombatLevelLeaf(level=90), state(combat_level=100), build_content())
        assert result.value is Tri.UNKNOWN

    @pytest.mark.parametrize(("points", "expected"), [(150, Tri.SATISFIED), (149, Tri.UNSATISFIED)])
    def test_quest_points_compare_against_the_target(
        self, build_content: ContentFactory, points: int, expected: Tri
    ) -> None:
        player = state(quest_points=points, last_sync_at=NOW)
        assert evaluate(QuestPointsLeaf(points=150), player, build_content()).value is expected

    def test_quest_points_are_unknown_when_the_account_was_never_synced(
        self, build_content: ContentFactory
    ) -> None:
        result = evaluate(QuestPointsLeaf(points=150), state(quest_points=200), build_content())
        assert result.value is Tri.UNKNOWN


class TestCombinatorsOverRealLeaves:
    """The §9.1 tables, exercised through the evaluator rather than through `tri`."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(skills=[MAGIC, DEFENCE], items=[VOIDWAKER, AGS])

    def test_all_of_short_circuits_on_a_definite_unsatisfied(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        requirement = AllOf(
            children=(
                SkillLeaf(skill="magic", level=94),  # unsatisfied
                SkillLeaf(skill="defence", level=75),  # unknown — no snapshot
            )
        )
        result = evaluate(requirement, state(skills={"magic": skill_at(80)}), content)
        assert result.value is Tri.UNSATISFIED

    def test_any_of_is_satisfied_by_one_branch(
        self,
        content: Content,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        requirement = AnyOf(
            children=(ItemLeaf(item_id="voidwaker"), ItemLeaf(item_id="armadyl_godsword"))
        )
        player = state(observed_items={27690: owned(27690)}, container_scans=scans())
        assert evaluate(requirement, player, content).value is Tri.SATISFIED

    def test_at_least_over_leaves(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        requirement = AtLeast(
            n=2,
            of=(
                SkillLeaf(skill="magic", level=94),
                SkillLeaf(skill="defence", level=75),
                SkillLeaf(skill="magic", level=99),
            ),
        )
        player = state(skills={"magic": skill_at(94)})
        # magic 94 satisfied, magic 99 unsatisfied, defence unknown → 1 satisfied, 1 unknown.
        assert evaluate(requirement, player, content).value is Tri.UNKNOWN

    def test_not_swaps_a_definite_value(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        requirement = Not(child=SkillLeaf(skill="magic", level=94))
        assert (
            evaluate(requirement, state(skills={"magic": skill_at(80)}), content).value
            is Tri.SATISFIED
        )
        assert (
            evaluate(requirement, state(skills={"magic": skill_at(94)}), content).value
            is Tri.UNSATISFIED
        )

    def test_not_leaves_unknown_alone(self, content: Content) -> None:
        requirement = Not(child=SkillLeaf(skill="magic", level=94))
        assert evaluate(requirement, state(), content).value is Tri.UNKNOWN

    def test_not_keeps_the_leaf_counts_of_its_child(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        """§9.1 counts *"leaves evaluating to satisfied"*; negation changes the node's
        value, not what the leaf beneath it observed."""
        requirement = Not(child=SkillLeaf(skill="magic", level=94))
        result = evaluate(requirement, state(skills={"magic": skill_at(94)}), content)
        assert (result.satisfied_leaves, result.total_leaves) == (1, 1)


class TestUnlockFraction:
    """§6.9 + A3 — unknowns sit in the denominator and are never credited."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(skills=[MAGIC, DEFENCE], items=[VOIDWAKER])

    def test_one_satisfied_one_unsatisfied_one_unknown_is_a_third(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        """*"A capability with one satisfied, one unsatisfied and one unknown leaf reports
        0.33, not 0.50."*"""
        requirement = AllOf(
            children=(
                SkillLeaf(skill="magic", level=94),  # satisfied
                SkillLeaf(skill="magic", level=99),  # unsatisfied
                SkillLeaf(skill="defence", level=75),  # unknown
            )
        )
        result = evaluate(requirement, state(skills={"magic": skill_at(94)}), content)
        assert result.satisfied_leaves == 1
        assert result.total_leaves == 3
        assert round(result.unlock_fraction, 2) == 0.33

    def test_no_leaves_is_zero_not_a_division_error(self) -> None:
        assert EvalResult(value=Tri.SATISFIED).unlock_fraction == 0.0

    def test_a_leaf_mentioned_twice_counts_twice(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        """The counts are over tree positions; the ref lists are over distinct leaves."""
        requirement = AllOf(
            children=(SkillLeaf(skill="magic", level=94), SkillLeaf(skill="magic", level=94))
        )
        result = evaluate(requirement, state(skills={"magic": skill_at(80)}), content)
        assert result.total_leaves == 2
        assert len(result.blockers) == 1


class TestBlockersAndUnknowns:
    """§6.9 keeps the two lists apart because they demand different user actions."""

    @pytest.fixture
    def content(self, build_content: ContentFactory) -> Content:
        return build_content(skills=[MAGIC, DEFENCE], items=[VOIDWAKER, AGS])

    def test_they_are_disjoint_and_separately_populated(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        requirement = AllOf(
            children=(
                SkillLeaf(skill="magic", level=94),  # unsatisfied → blocker
                SkillLeaf(skill="defence", level=75),  # unknown → "sync this"
            )
        )
        result = evaluate(requirement, state(skills={"magic": skill_at(80)}), content)
        assert [ref.key for ref in result.blockers] == ["magic"]
        assert [ref.key for ref in result.unknowns] == ["defence"]
        assert not set(result.blockers) & set(result.unknowns)

    def test_a_satisfied_any_of_reports_no_blocker_for_its_losing_branch(
        self,
        content: Content,
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """Holding a Voidwaker must not surface *"requires Armadyl godsword"*."""
        requirement = AnyOf(
            children=(ItemLeaf(item_id="voidwaker"), ItemLeaf(item_id="armadyl_godsword"))
        )
        player = state(observed_items={27690: owned(27690)}, container_scans=scans())
        result = evaluate(requirement, player, content)
        assert result.value is Tri.SATISFIED
        assert result.blockers == ()
        assert result.unknowns == ()

    def test_an_unsatisfied_any_of_reports_every_alternative(
        self, content: Content, scans: Callable[..., dict[Container, datetime]]
    ) -> None:
        """Each alternative is a way to unblock, so each is a blocker."""
        requirement = AnyOf(
            children=(ItemLeaf(item_id="voidwaker"), ItemLeaf(item_id="armadyl_godsword"))
        )
        result = evaluate(requirement, state(container_scans=scans()), content)
        assert [ref.key for ref in result.blockers] == ["voidwaker", "armadyl_godsword"]

    def test_a_leaf_under_an_unsatisfied_sibling_does_not_contribute(
        self,
        content: Content,
        skill_at: Callable[..., SkillState],
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
    ) -> None:
        """§6.9: contributing leaves are those that *justify* the result."""
        requirement = AnyOf(
            children=(
                AllOf(
                    children=(
                        ItemLeaf(item_id="voidwaker"),  # satisfied
                        SkillLeaf(skill="magic", level=99),  # unsatisfied → branch loses
                    )
                ),
                SkillLeaf(skill="magic", level=94),  # satisfied → branch wins
            )
        )
        player = state(
            skills={"magic": skill_at(94)},
            observed_items={27690: owned(27690)},
            container_scans=scans(),
        )
        result = evaluate(requirement, player, content)
        assert result.value is Tri.SATISFIED
        assert [ref.key for ref in result.contributing] == ["magic"]

    def test_nothing_contributes_to_a_result_that_is_not_satisfied(
        self, content: Content, skill_at: Callable[..., SkillState]
    ) -> None:
        requirement = AllOf(
            children=(SkillLeaf(skill="magic", level=94), SkillLeaf(skill="magic", level=99))
        )
        result = evaluate(requirement, state(skills={"magic": skill_at(94)}), content)
        assert result.contributing == ()


class TestEvalResultInterface:
    """The shape Steps 5 and 6 code against. Renaming a field here breaks them silently."""

    def test_the_frozen_field_names(self) -> None:
        names = [field.name for field in dataclasses.fields(EvalResult)]
        assert names[:5] == [
            "value",
            "blockers",
            "unknowns",
            "satisfied_leaves",
            "total_leaves",
        ]

    def test_it_is_frozen(self) -> None:
        result = EvalResult(value=Tri.UNKNOWN)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.value = Tri.SATISFIED  # type: ignore[misc]

    def test_unlock_fraction_is_derived_not_stored(self) -> None:
        result = EvalResult(value=Tri.SATISFIED, satisfied_leaves=1, total_leaves=4)
        assert result.unlock_fraction == 0.25

    def test_evaluate_takes_its_arguments_positionally(
        self, build_content: ContentFactory, skill_at: Callable[..., SkillState]
    ) -> None:
        requirement: Requirement = SkillLeaf(skill="magic", level=94)
        content = build_content(skills=[MAGIC])
        assert (
            evaluate(requirement, state(skills={"magic": skill_at(94)}), content).value
            is Tri.SATISFIED
        )


class TestPurity:
    """§16.1 — the same inputs give the same answer, and no input is mutated."""

    def test_evaluation_is_repeatable(
        self, build_content: ContentFactory, skill_at: Callable[..., SkillState]
    ) -> None:
        content = build_content(skills=[MAGIC])
        player = state(skills={"magic": skill_at(94)})
        requirement: Requirement = SkillLeaf(skill="magic", level=94)
        assert evaluate(requirement, player, content) == evaluate(requirement, player, content)

    def test_the_player_state_is_untouched(
        self, build_content: ContentFactory, scans: Callable[..., dict[Container, datetime]]
    ) -> None:
        content = build_content(items=[VOIDWAKER])
        player = state(container_scans=scans(days_ago=400))
        before = dict(player.container_scans)
        evaluate(ItemLeaf(item_id="voidwaker"), player, content)
        assert dict(player.container_scans) == before

    def test_two_players_do_not_share_a_memo_table(
        self, build_content: ContentFactory, skill_at: Callable[..., SkillState]
    ) -> None:
        content = build_content(
            skills=[MAGIC],
            capabilities=[
                Capability(id="a", name="A", requires=SkillLeaf(skill="magic", level=94))
            ],
        )
        leaf = CapabilityLeaf(capability_id="a")
        assert evaluate(leaf, state(skills={"magic": skill_at(94)}), content).value is Tri.SATISFIED
        assert (
            evaluate(leaf, state(skills={"magic": skill_at(80)}), content).value is Tri.UNSATISFIED
        )


class TestSeedCorpus:
    """The shipped corpus evaluates end to end (§16.4)."""

    def test_an_unobserved_account_is_never_locked_by_default(self, seed_content: Content) -> None:
        """With nothing observed, an account's capabilities must not read as *"no"*."""
        requirement = seed_content.capabilities["ice_barrage_nh"].requires
        assert requirement is not None
        assert evaluate(requirement, state(), seed_content).value is Tri.UNKNOWN

    def test_a_fully_equipped_account_unlocks_deep_wilderness_nh(
        self,
        seed_content: Content,
        skill_at: Callable[..., SkillState],
        owned: Callable[..., ItemObservation],
        scans: Callable[..., dict[Container, datetime]],
        milestone_state: Callable[..., MilestoneState],
    ) -> None:
        requirement = seed_content.capabilities["deep_wildy_nh"].requires
        assert requirement is not None
        player = state(
            skills={name: skill_at(99) for name in seed_content.skills},
            unlocks={"ancient_magicks": UnlockState.UNLOCKED},
            quests=dict.fromkeys(seed_content.quests, QuestStatus.COMPLETE),
            observed_items={27690: owned(27690), 4091: owned(4091)},
            container_scans=scans(),
            milestones={
                milestone.id: milestone_state(
                    milestone.id, kind=milestone.kind, class_=milestone.class_
                )
                for milestone in seed_content.milestones.values()
            },
            combat_level=126,
            quest_points=300,
            last_sync_at=NOW,
        )
        assert evaluate(requirement, player, seed_content).value is Tri.SATISFIED
