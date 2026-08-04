"""Domain type invariants (§4.4, §6, §9.1, A6, A7, A9)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tracker.domain.types import (
    Confidence,
    Container,
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    MilestoneState,
    PlayerState,
    PracticeDomain,
    QuestStatus,
    RoadmapSelection,
    Status,
    Tri,
    UnlockState,
)

NOW = datetime(2026, 8, 4, tzinfo=UTC)


class TestTri:
    """``Tri`` must be impossible to collapse into a boolean (§9.1, D8)."""

    def test_has_exactly_three_members(self) -> None:
        assert set(Tri) == {Tri.SATISFIED, Tri.UNSATISFIED, Tri.UNKNOWN}

    @pytest.mark.parametrize("value", list(Tri))
    def test_truthiness_raises(self, value: Tri) -> None:
        """`if not satisfied` must fail loudly, not silently treat unknown as false.

        Every enum member is truthy by default, so `if tri:` would be *always* true —
        a bug that never announces itself. Raising converts the §9.1 warning from a
        code-review rule into a runtime guarantee.
        """
        with pytest.raises(TypeError, match="no truth value"):
            bool(value)

    def test_not_operator_raises_too(self) -> None:
        with pytest.raises(TypeError, match="no truth value"):
            _ = not Tri.UNKNOWN

    def test_identity_comparison_is_the_supported_idiom(self) -> None:
        assert Tri.SATISFIED is Tri.SATISFIED
        assert Tri.UNKNOWN is not Tri.UNSATISFIED

    @pytest.mark.parametrize("value", list(Tri))
    def test_exhaustive_match_covers_every_member(self, value: Tri) -> None:
        """A match over the three arms is total — no member falls through."""
        match value:
            case Tri.SATISFIED:
                label = "satisfied"
            case Tri.UNSATISFIED:
                label = "unsatisfied"
            case Tri.UNKNOWN:
                label = "unknown"
            case _:  # pragma: no cover — proves totality if it ever fires
                pytest.fail(f"unhandled Tri member {value!r}")
        assert label == value.value

    def test_from_bool_lifts_a_genuine_boolean(self) -> None:
        assert Tri.from_bool(True) is Tri.SATISFIED
        assert Tri.from_bool(False) is Tri.UNSATISFIED


class TestConfidence:
    """A9 — ``recommended_now`` compares against a threshold, so ordering is required."""

    def test_is_ordered_low_to_high(self) -> None:
        assert Confidence.LOW < Confidence.MEDIUM < Confidence.HIGH

    def test_comparison_against_a_declared_bar(self) -> None:
        bar = Confidence.HIGH
        assert not (Confidence.MEDIUM >= bar)
        assert Confidence.HIGH >= bar

    def test_string_ordering_would_have_been_wrong(self) -> None:
        """Sorting by name gives high < low < medium — the bug an IntEnum prevents."""
        by_name = sorted(Confidence, key=lambda c: c.name)
        by_value = sorted(Confidence)
        assert [c.name for c in by_name] == ["HIGH", "LOW", "MEDIUM"]
        assert [c.name for c in by_value] == ["LOW", "MEDIUM", "HIGH"]

    def test_max_and_min_work(self) -> None:
        assert min(Confidence.HIGH, Confidence.LOW) is Confidence.LOW


class TestFactEnums:
    def test_unlock_state_has_four_states(self) -> None:
        """§6.3 — the Unlocks UI renders four, and `unknown` is first-class."""
        assert {state.value for state in UnlockState} == {
            "unlocked",
            "available",
            "locked",
            "unknown",
        }

    def test_quest_status_has_four_states(self) -> None:
        assert {status.value for status in QuestStatus} == {
            "not_started",
            "in_progress",
            "complete",
            "unknown",
        }

    def test_status_is_tri_valued_not_boolean(self) -> None:
        """D8 — a boolean cannot represent 'we have never observed your bank'."""
        assert {s.value for s in Status} == {"unlocked", "locked", "unknown"}

    def test_the_six_practice_domains(self) -> None:
        assert {domain.value for domain in PracticeDomain} == {
            "lms",
            "nh_combat",
            "wilderness_pvp",
            "vengeance_pvp",
            "anti_pking",
            "general_pvp",
        }

    def test_kind_and_class_are_orthogonal(self) -> None:
        """§6.6 — how a milestone is measured is independent of how it ages."""
        assert {k.value for k in MilestoneKind} == {"derived", "self_attested"}
        assert {c.value for c in MilestoneClass} == {"knowledge", "execution", "threshold"}


class TestMilestoneState:
    def test_attested_is_tri_valued(self) -> None:
        """A7 — 'never prompted' and 'asked, said no' are different facts."""
        never_prompted = MilestoneState(
            key="teleblock_understanding",
            achieved=False,
            attested=Tri.UNKNOWN,
            kind=MilestoneKind.SELF_ATTESTED,
            class_=MilestoneClass.KNOWLEDGE,
        )
        declined = MilestoneState(
            key="teleblock_understanding",
            achieved=False,
            attested=Tri.UNSATISFIED,
            kind=MilestoneKind.SELF_ATTESTED,
            class_=MilestoneClass.KNOWLEDGE,
        )
        assert never_prompted.achieved == declined.achieved
        assert never_prompted.attested is not declined.attested

    def test_is_frozen(self) -> None:
        milestone = MilestoneState(
            key="k",
            achieved=True,
            attested=Tri.SATISFIED,
            kind=MilestoneKind.DERIVED,
            class_=MilestoneClass.THRESHOLD,
        )
        with pytest.raises(AttributeError):
            milestone.achieved = False  # type: ignore[misc]


class TestPlayerState:
    def test_defaults_to_a_fully_unobserved_account(self) -> None:
        state = PlayerState(player_id=1)
        assert state.last_sync_at is None  # A6 — combat_level/quest_points → unknown
        assert state.container_scans == {}  # §6.5 — nothing has ever been scanned
        assert state.combat_level is None
        assert state.gp_sensitivity is GpSensitivity.NORMAL

    def test_carries_container_scan_timestamps(self) -> None:
        """§6.5 — without these, 'not seen' and 'never looked' collapse."""
        state = PlayerState(player_id=1, container_scans={Container.BANK: NOW})
        assert state.container_scans[Container.BANK] == NOW
        assert Container.EQUIPMENT not in state.container_scans


class TestRoadmapSelection:
    def test_normalizes_to_sum_one(self) -> None:
        """§4.3 — normalized on read so removing a roadmap cannot rescale the rest."""
        normalized = RoadmapSelection({"main_nh": 1.00, "anti_pk": 0.25}).normalized()
        assert sum(normalized.values()) == pytest.approx(1.0)
        assert normalized["main_nh"] == pytest.approx(0.8)
        assert normalized["anti_pk"] == pytest.approx(0.2)

    def test_stored_weights_are_untouched(self) -> None:
        selection = RoadmapSelection({"main_nh": 1.00, "anti_pk": 0.25})
        selection.normalized()
        assert selection.weights == {"main_nh": 1.00, "anti_pk": 0.25}

    def test_empty_selection_normalizes_to_empty(self) -> None:
        assert RoadmapSelection().normalized() == {}
        assert RoadmapSelection({"main_nh": 0.0}).normalized() == {}
