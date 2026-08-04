"""The seam between Step 2.5's candidate derivations and Step 4's evaluator.

These two units were built in parallel against a contract rather than against each
other, so this is the first place their halves meet. It exists because both suites were
green while the seam was broken: ``tracker.domain.candidates`` declared its protocol
members as bare attributes, which demand read *and write* access, and the evaluator
returns a **frozen** dataclass. Nothing inside either package could notice — a protocol
is only checked where an implementation is actually assigned to it.

The static half of the check is `make typecheck`, which covers `tests/` for exactly this
reason. The annotations below are the assertions; mypy is what runs them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import Requirement
from tracker.content.validate import load_and_validate
from tracker.domain.candidates import (
    EvalOutcome,
    RequirementEvaluator,
    UnlocksAfterFacts,
    blocked,
    completed,
    effective_capability_weights,
    gate_value,
    proximity,
    pvp_value,
)
from tracker.domain.types import (
    PlayerState,
    RoadmapSelection,
    SkillState,
    Source,
    Status,
    Tri,
    UnlockState,
)
from tracker.progression.engine import compute_capability_states
from tracker.progression.evaluate import EvalResult, Evaluator, evaluate

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"
NOW = datetime(2026, 8, 4, tzinfo=UTC)

# --- the static assertions -------------------------------------------------
# These are not decoration. Each is a mypy check that the concrete implementation
# satisfies the protocol the other package was written against.
_EVALUATOR_SATISFIES_PROTOCOL: RequirementEvaluator = evaluate
_RESULT_SATISFIES_PROTOCOL: type[EvalOutcome] = EvalResult


@pytest.fixture(scope="module")
def content() -> Content:
    return load_and_validate(CONTENT_ROOT)


def state_with(**overrides: object) -> PlayerState:
    """A player who has 87 Magic, by default with nothing else observed."""
    defaults: dict[str, object] = {
        "player_id": 1,
        "skills": {
            "magic": SkillState(level=87, xp=1_500_000, source=Source.RUNELITE, observed_at=NOW)
        },
        "last_sync_at": NOW,
    }
    defaults.update(overrides)
    return PlayerState(**defaults)  # type: ignore[arg-type]


def xp_for_level(level: int) -> int:
    """A stand-in curve until Step 5 ships the real table — monotonic is all we need."""
    return int(1000 * (1.1 ** (level - 1)))


class TestTheProtocolsAreSatisfied:
    def test_the_concrete_evaluator_is_accepted_where_the_protocol_is_required(
        self, content: Content
    ) -> None:
        """Runtime half. The static half is the module-level annotation above."""
        candidate = content.candidates["train_magic_87_to_94"]
        state = state_with()

        # Passing the real evaluate() straight into a derivation that was only ever
        # tested against a stub.
        assert completed(candidate, state, content, evaluate) is False

    def test_the_result_carries_every_field_the_protocol_names(self, content: Content) -> None:
        outcome = evaluate(
            content.candidates["train_magic_87_to_94"].completion, state_with(), content
        )
        assert isinstance(outcome.value, Tri)
        assert isinstance(outcome.satisfied_leaves, int)
        assert isinstance(outcome.total_leaves, int)

    def test_the_memoized_evaluator_needs_a_two_line_adapter(self, content: Content) -> None:
        """Step 6 will reuse one ``Evaluator`` across many candidates rather than
        re-walking a shared ``capability:`` prerequisite once per dependant.

        **It does not satisfy the protocol directly**, and that is by design on both
        sides: ``Evaluator`` binds ``(state, content)`` at construction — which is what
        makes the memo table sound — while the protocol passes them per call, because a
        derivation must not assume its evaluator is pinned to one account. The adapter
        below is the whole cost, and pinning it here means Step 6 discovers it from a
        test rather than from a type error.
        """
        state = state_with()
        session = Evaluator(state, content)

        def memoized(
            requirement: Requirement, _state: PlayerState, _content: Content
        ) -> EvalOutcome:
            return session.evaluate(requirement)

        adapter: RequirementEvaluator = memoized
        candidate = content.candidates["train_magic_87_to_94"]
        assert completed(candidate, state, content, adapter) is False


class TestDerivationsAgainstTheRealEvaluator:
    def test_an_unknown_gate_is_not_blocked(self, content: Content) -> None:
        """G3, end to end. `train_magic_87_to_94` requires `unlock: ancient_magicks`;
        an account that has never synced its unlocks must read *sync this*, not *do this*."""
        candidate = content.candidates["train_magic_87_to_94"]
        state = state_with()  # no unlocks observed at all

        assert gate_value(candidate, state, content, evaluate) is Tri.UNKNOWN
        assert blocked(candidate, state, content, evaluate) is False

    def test_a_genuinely_unsatisfied_gate_is_blocked(self, content: Content) -> None:
        candidate = content.candidates["train_magic_87_to_94"]
        state = state_with(unlocks={"ancient_magicks": UnlockState.LOCKED})

        assert gate_value(candidate, state, content, evaluate) is Tri.UNSATISFIED
        assert blocked(candidate, state, content, evaluate) is True

    def test_available_is_not_a_satisfied_gate(self, content: Content) -> None:
        """§6.3's trap, reaching a candidate through the evaluator: *available* means
        purchasable, not held."""
        candidate = content.candidates["train_magic_87_to_94"]
        state = state_with(unlocks={"ancient_magicks": UnlockState.AVAILABLE})

        assert blocked(candidate, state, content, evaluate) is True

    def test_completion_flips_only_on_satisfied(self, content: Content) -> None:
        candidate = content.candidates["train_magic_87_to_94"]
        unlocks = {"ancient_magicks": UnlockState.UNLOCKED}

        at_87 = state_with(unlocks=unlocks)
        at_94 = state_with(
            unlocks=unlocks,
            skills={
                "magic": SkillState(level=94, xp=7_200_000, source=Source.RUNELITE, observed_at=NOW)
            },
        )

        assert completed(candidate, at_87, content, evaluate) is False
        assert completed(candidate, at_94, content, evaluate) is True

    def test_proximity_increases_as_the_player_approaches_the_target(
        self, content: Content
    ) -> None:
        """§16.2 — of two otherwise identical candidates, the closer ranks higher."""
        candidate = content.candidates["train_magic_87_to_94"]
        unlocks = {"ancient_magicks": UnlockState.UNLOCKED}

        near = proximity(
            candidate,
            state_with(
                unlocks=unlocks,
                skills={
                    "magic": SkillState(
                        level=93, xp=xp_for_level(93), source=Source.RUNELITE, observed_at=NOW
                    )
                },
            ),
            content,
            evaluate,
            xp_for_level,
        )
        far = proximity(
            candidate,
            state_with(
                unlocks=unlocks,
                skills={
                    "magic": SkillState(
                        level=70, xp=xp_for_level(70), source=Source.RUNELITE, observed_at=NOW
                    )
                },
            ),
            content,
            evaluate,
            xp_for_level,
        )

        assert 0.0 <= far < near <= 1.0


class TestTheUnlocksAfterFactsSeam:
    """The second injected callable — Step 6 must build this from the progression engine."""

    def test_the_engine_can_supply_the_predicate(self, content: Content) -> None:
        def unlocks_after_facts(
            capability_id: str, grants: Requirement, state: PlayerState, content_: Content
        ) -> bool:
            """*Flip*, not *state*: already-unlocked does not count as unlocked **by** this."""
            before = compute_capability_states(state, content_, content_.profile, NOW)
            if before[capability_id].status is Status.UNLOCKED:
                return False
            after = compute_capability_states(
                _apply(state, grants), content_, content_.profile, NOW
            )
            return after[capability_id].status is Status.UNLOCKED

        predicate: UnlocksAfterFacts = unlocks_after_facts
        assert callable(predicate)

    def test_pvp_value_reproduces_the_worked_table_with_real_content(
        self, content: Content
    ) -> None:
        """§9.3, computed through the same code path Step 6 will use."""
        weights = effective_capability_weights(
            RoadmapSelection({"main_nh": 0.75, "anti_pk": 0.25}), content
        )
        assert pvp_value(content.candidates["train_magic_87_to_94"], weights) == pytest.approx(0.90)


def _apply(state: PlayerState, grants: Requirement) -> PlayerState:
    """Crudely apply a `skill:` grant so the flip predicate has something to observe.

    Step 6 needs a real version of this; here it only has to be enough to show the
    engine can answer the question the derivation asks.
    """
    from tracker.content.requirements import SkillLeaf, iter_leaves

    skills = dict(state.skills)
    for leaf in iter_leaves(grants):
        if isinstance(leaf, SkillLeaf):
            skills[leaf.skill] = SkillState(
                level=leaf.level, xp=None, source=Source.DERIVED, observed_at=NOW
            )
    return PlayerState(
        player_id=state.player_id,
        skills=skills,
        unlocks=state.unlocks,
        quests=state.quests,
        observed_items=state.observed_items,
        container_scans=state.container_scans,
        milestones=state.milestones,
        combat_level=state.combat_level,
        quest_points=state.quest_points,
        gp_sensitivity=state.gp_sensitivity,
        last_sync_at=state.last_sync_at,
    )
