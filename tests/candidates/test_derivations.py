"""The §10.6 factor derivations, against a stub evaluator.

The evaluator itself is step 4's (`tracker/progression/`). These tests inject a stub for
two reasons: the derivations must be provable independently of it, and the case that
matters most — a requirement evaluating `unknown` — is one line to construct here and a
whole fixture account to arrange through the real engine.

`StubOutcome` carries exactly the fields step 4's `EvalResult` is contractually frozen to
expose, so anything asserted here holds of the real one too (see `TestTheStep4Seam`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from tracker.content.loader import Content
from tracker.content.requirements import AnyOf, MilestoneLeaf, Requirement
from tracker.content.requirements import parse as parse_requirement
from tracker.content.schema import Candidate, RefresherTemplate
from tracker.content.validate import load_and_validate
from tracker.domain.candidates import (
    blocked,
    completed,
    effective_capability_weights,
    gate_value,
    leverage,
    leverage_map,
    method_unlock,
    method_unlock_detail,
    method_unlock_fraction,
    method_unlock_map,
    method_unlock_scores,
    proximity,
    pvp_value,
    unlock_flip_count,
    unlock_flips,
)
from tracker.domain.types import (
    CandidateKind,
    PlayerState,
    RoadmapSelection,
    SkillState,
    Source,
    Tri,
)

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"
NOW = datetime(2026, 8, 4, tzinfo=UTC)

#: §9.3's worked selection: one primary, one secondary, already summing to 1.
SDD_SELECTION = RoadmapSelection({"main_nh": 0.75, "anti_pk": 0.25})


#: A synthetic XP curve — 100 xp per level, linear. The real table is step 5's (§8.2);
#: proximity only needs *a* monotonic curve, and a linear one makes the arithmetic in
#: these assertions checkable by eye.
def linear_xp(level: int) -> int:
    return (level - 1) * 100


@pytest.fixture(scope="module")
def content() -> Content:
    return load_and_validate(CONTENT_ROOT)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StubOutcome:
    """The three fields `EvalOutcome` requires (§9.1, §6.9)."""

    value: Tri
    satisfied_leaves: int = 0
    total_leaves: int = 1


@dataclass
class StubEvaluator:
    """Returns a canned outcome per requirement tree, defaulting to `unknown`.

    Defaulting to `unknown` rather than `unsatisfied` is deliberate: a test that forgets
    to arrange a tree gets the value that exposes G3 bugs, not the one that hides them.
    """

    outcomes: Mapping[Requirement, StubOutcome] = field(default_factory=dict)
    default: StubOutcome = StubOutcome(Tri.UNKNOWN)

    def __call__(
        self, requirement: Requirement, state: PlayerState, content: Content
    ) -> StubOutcome:
        return self.outcomes.get(requirement, self.default)


def always(value: Tri, satisfied: int = 0, total: int = 1) -> StubEvaluator:
    return StubEvaluator(default=StubOutcome(value, satisfied, total))


def candidate(
    candidate_id: str = "c",
    *,
    kind: CandidateKind = CandidateKind.UNLOCK,
    advances: Mapping[str, float] | None = None,
    requires: str | None = None,
    completion: str = "unlock: something",
    grants_facts: str | None = None,
) -> Candidate:
    """Build a candidate from the §10.2 YAML spellings, as an author would write it."""
    return Candidate(
        id=candidate_id,
        name=candidate_id,
        kind=kind,
        advances=dict(advances or {}),
        requires=parse_requirement(_yaml(requires)) if requires else None,
        completion=parse_requirement(_yaml(completion)),
        grants_facts=parse_requirement(_yaml(grants_facts)) if grants_facts else None,
    )


def _yaml(source: str) -> object:
    return yaml.safe_load(source)


def skills(**levels: int) -> Mapping[str, SkillState]:
    return {
        skill: SkillState(level=level, xp=linear_xp(level), source=Source.RUNELITE, observed_at=NOW)
        for skill, level in levels.items()
    }


# ---------------------------------------------------------------------------
# §9.3 — blending
# ---------------------------------------------------------------------------


class TestEffectiveCapabilityWeights:
    """§9.3: all active roadmaps collapse into **one** map before anything is scored."""

    def test_reproduces_the_sdd_worked_blend(self, content: Content) -> None:
        """0.75(1.00) + 0.25(0.60) = 0.95 in the SDD's illustration; 0.90 in this corpus,
        whose anti_pk roadmap weights ice_barrage_nh at 0.60 (§9.3's candidate table)."""
        weights = effective_capability_weights(SDD_SELECTION, content)
        assert weights["ice_barrage_nh"] == pytest.approx(0.90)
        assert weights["vengeance_pvp"] == pytest.approx(0.375)

    def test_selection_weights_are_normalized_at_read_time(self, content: Content) -> None:
        """§4.3's UI default is `1.00` and `0.25`, which is not a convex combination
        until it is normalized — 0.8 and 0.2."""
        weights = effective_capability_weights(
            RoadmapSelection({"main_nh": 1.00, "anti_pk": 0.25}), content
        )
        expected = 0.8 * 1.00 + 0.2 * 0.60
        assert weights["ice_barrage_nh"] == pytest.approx(expected)

    def test_a_capability_in_two_roadmaps_blends_never_accumulates(self, content: Content) -> None:
        """D3 — the naive sum here is 1.60, outside the range every factor lives in."""
        weights = effective_capability_weights(SDD_SELECTION, content)
        assert 0.0 <= weights["ice_barrage_nh"] <= 1.0

    def test_every_blended_weight_stays_in_the_unit_interval(self, content: Content) -> None:
        weights = effective_capability_weights(SDD_SELECTION, content)
        assert weights
        assert all(0.0 <= weight <= 1.0 for weight in weights.values())

    def test_an_empty_selection_weights_nothing(self, content: Content) -> None:
        assert effective_capability_weights(RoadmapSelection({}), content) == {}

    def test_an_unknown_roadmap_id_cannot_inflate_the_others(self, content: Content) -> None:
        """A roadmap removed from content must make the blend conservative, never larger."""
        with_ghost = effective_capability_weights(
            RoadmapSelection({"main_nh": 0.75, "no_such_roadmap": 0.25}), content
        )
        assert with_ghost["ice_barrage_nh"] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# pvp_value (§9.3, A2, D11)
# ---------------------------------------------------------------------------


def candidate_from_refresher(refresher: RefresherTemplate, content: Content) -> Candidate:
    """§10.6's *"Refreshers are candidates"*, minimally.

    Synthesis proper belongs to step 6 (§9.8). All that matters here is the rule §10.6
    states: a generated refresher carries `kind: practice` and inherits `advances` from
    the group — which is what makes §9.3's second row scoreable from shipped content
    rather than from a number invented in a test.
    """
    members = content.milestones_in_group(refresher.practice_group)
    return Candidate(
        id=refresher.id,
        name=refresher.name,
        kind=CandidateKind.PRACTICE,
        advances=dict.fromkeys(refresher.advances, 1.0),
        completion=AnyOf(children=tuple(MilestoneLeaf(key=m.id) for m in members)),
    )


class TestPvpValueReproducesTheSddTable:
    """§9.3's worked table, from the shipped corpus, at `main_nh: 0.75, anti_pk: 0.25`."""

    def test_train_magic_to_94_scores_zero_point_nine(self, content: Content) -> None:
        weights = effective_capability_weights(SDD_SELECTION, content)
        train_magic = content.candidates["train_magic_87_to_94"]
        assert pvp_value(train_magic, weights) == pytest.approx(0.90)

    def test_practice_vengeance_timing_scores_zero_point_three_seven_five(
        self, content: Content
    ) -> None:
        weights = effective_capability_weights(SDD_SELECTION, content)
        practice = candidate_from_refresher(
            content.refreshers["refresh_vengeance_fundamentals"], content
        )
        assert pvp_value(practice, weights) == pytest.approx(0.375)


class TestPvpValueTakesTheMaximum:
    """D11 — *"Maximum, never sum."* Breadth must not substitute for relevance."""

    def test_a_multi_capability_candidate_takes_the_max_not_the_sum(self, content: Content) -> None:
        weights = effective_capability_weights(SDD_SELECTION, content)
        voidwaker = content.candidates["buy_voidwaker"]

        terms = [weights[c] * w for c, w in voidwaker.advances.items()]
        assert len(terms) > 1
        assert sum(terms) > 1.0  # the naive sum leaves [0, 1] entirely
        assert pvp_value(voidwaker, weights) == pytest.approx(max(terms))

    def test_four_weak_capabilities_do_not_outrank_one_strong_one(self, content: Content) -> None:
        """The exact failure D11 rejects, and the reason §9.8 forbids summing group size."""
        weights = effective_capability_weights(SDD_SELECTION, content)
        broad = candidate(
            "broad",
            advances={
                "ice_barrage_nh": 0.20,
                "deep_wildy_nh": 0.20,
                "anti_pk": 0.20,
                "budget_nh": 0.20,
            },
        )
        narrow = candidate("narrow", advances={"ice_barrage_nh": 0.80})

        assert pvp_value(narrow, weights) > pvp_value(broad, weights)

    def test_pvp_value_never_leaves_the_unit_interval(self, content: Content) -> None:
        weights = effective_capability_weights(SDD_SELECTION, content)
        for shipped in content.candidates.values():
            assert 0.0 <= pvp_value(shipped, weights) <= 1.0


class TestPvpValueOrderOfOperations:
    """§9.3: *"The order of operations is load-bearing."*"""

    def test_blend_then_max_differs_from_max_then_blend(self, content: Content) -> None:
        """`max` and convex combination do not commute, and only one order agrees with
        §9.3's table. A candidate advancing the two capabilities the two roadmaps
        disagree most about is where the two orders visibly part company."""
        both = candidate("both", advances={"ice_barrage_nh": 1.00, "anti_pk": 1.00})

        blend_then_max = pvp_value(both, effective_capability_weights(SDD_SELECTION, content))

        max_then_blend = sum(
            selection_weight
            * max(
                content.roadmaps[roadmap_id].capabilities.get(capability_id, 0.0) * contribution
                for capability_id, contribution in both.advances.items()
            )
            for roadmap_id, selection_weight in SDD_SELECTION.normalized().items()
        )

        assert blend_then_max == pytest.approx(0.90)
        assert max_then_blend == pytest.approx(1.00)
        assert blend_then_max != pytest.approx(max_then_blend)


class TestPvpValueEdges:
    def test_a_candidate_advancing_nothing_scores_zero(self, content: Content) -> None:
        """`train_woodcutting` is the shipped control: it ranks last because the content
        says it advances nothing, not because code knows what woodcutting is (§10.8)."""
        weights = effective_capability_weights(SDD_SELECTION, content)
        assert content.candidates["train_woodcutting"].advances == {}
        assert pvp_value(content.candidates["train_woodcutting"], weights) == 0.0

    def test_a_capability_no_active_roadmap_weights_contributes_nothing(self) -> None:
        assert pvp_value(candidate(advances={"unweighted": 1.0}), {}) == 0.0


# ---------------------------------------------------------------------------
# leverage (§9.4, §10.6)
# ---------------------------------------------------------------------------


class TestUnlockFlipCount:
    def test_counts_capabilities_the_probe_says_would_flip(self, content: Content) -> None:
        flips = {"ice_barrage_nh", "budget_nh"}
        count = unlock_flip_count(
            candidate(grants_facts="unlock: ancient_magicks"),
            PlayerState(player_id=1),
            content,
            lambda capability_id, _facts, _state, _content: capability_id in flips,
        )
        assert count == 2

    def test_a_candidate_granting_no_facts_unlocks_nothing(self, content: Content) -> None:
        """Zero, not unknown — leverage is a relevance factor, never a status (§4.4)."""
        count = unlock_flip_count(
            candidate(grants_facts=None),
            PlayerState(player_id=1),
            content,
            lambda *_args: pytest.fail("the probe must not be consulted"),
        )
        assert count == 0


class TestUnlockFlipsNamesWhatTheCountCounted:
    """§9.10 wants the names; §9.4 wants the count. One walk must produce both."""

    def test_the_names_are_exactly_the_capabilities_the_probe_flipped(
        self, content: Content
    ) -> None:
        flips = {"ice_barrage_nh", "budget_nh"}
        names = unlock_flips(
            candidate(grants_facts="unlock: ancient_magicks"),
            PlayerState(player_id=1),
            content,
            lambda capability_id, _facts, _state, _content: capability_id in flips,
        )
        assert set(names) == flips

    def test_the_count_and_the_names_cannot_disagree_over_the_whole_corpus(
        self, content: Content
    ) -> None:
        """Two loops is how the *Why* line comes to claim what the factor did not credit.

        Run over every shipped candidate rather than one, because the failure this guards
        is a later edit splitting the walk in two for a candidate shape nobody tested.
        """
        state = PlayerState(player_id=1)

        def probe(capability_id: str, _facts: Requirement, *_rest: object) -> bool:
            # Deterministic and non-uniform: a probe answering the same way for every
            # capability would let a count-of-all and a names-of-none implementation agree.
            return capability_id.startswith(("i", "b", "r"))

        for entry in content.candidates.values():
            names = unlock_flips(entry, state, content, probe)
            assert len(names) == unlock_flip_count(entry, state, content, probe), entry.id

    def test_a_candidate_granting_no_facts_names_nothing(self, content: Content) -> None:
        """The empty tuple, not a one-element tuple of nothing — the *Why* line joins these."""
        assert (
            unlock_flips(
                candidate(grants_facts=None),
                PlayerState(player_id=1),
                content,
                lambda *_args: pytest.fail("the probe must not be consulted"),
            )
            == ()
        )


class TestLeverageNormalization:
    """§10.6 — normalized by the largest count *across the current candidate set*."""

    def test_the_best_candidate_scores_one(self) -> None:
        assert leverage(3, 3) == pytest.approx(1.0)

    def test_the_rest_scale_against_it(self) -> None:
        assert leverage(1, 3) == pytest.approx(1 / 3)

    def test_a_candidate_that_unlocks_nothing_scores_zero(self) -> None:
        """§9.4's ε floor lifts this into (0,1] at scoring time; flooring it here would
        hide a genuine zero behind a tuning constant."""
        assert leverage(0, 3) == 0.0

    def test_when_nothing_unlocks_anything_the_factor_does_not_discriminate(self) -> None:
        assert leverage(0, 0) == 0.0

    def test_leverage_map_normalizes_within_the_set(self, content: Content) -> None:
        many = candidate("many", grants_facts="unlock: a")
        one = candidate("one", grants_facts="unlock: b")
        none = candidate("none")

        def probe(capability_id: str, facts: Requirement, *_rest: object) -> bool:
            if facts == many.grants_facts:
                return True
            return facts == one.grants_facts and capability_id == "ice_barrage_nh"

        scores = leverage_map([many, one, none], PlayerState(player_id=1), content, probe)

        assert scores["many"] == pytest.approx(1.0)
        assert scores["one"] == pytest.approx(1 / len(content.capabilities))
        assert scores["none"] == 0.0


# ---------------------------------------------------------------------------
# method_unlock (§9.4, §10.6, A30)
# ---------------------------------------------------------------------------


def hours_oracle(table: Mapping[str, Mapping[str | None, float | None]]) -> object:
    """A stub :data:`~tracker.domain.candidates.HoursAfterFacts` keyed by candidate id.

    ``table[candidate_id][None]`` is the baseline; ``table[candidate_id][grantor_id]`` the
    hours under that grantor's facts, defaulting to the baseline where unstated. Written as
    a table rather than as a real estimator because A30's arithmetic is what these tests are
    about — §8's sizing has its own suite, and going through it would make an assertion here
    fail for reasons that have nothing to do with the factor.
    """

    def probe(other: Candidate, grants: Requirement | None) -> float | None:
        row = table[other.id]
        if grants is None:
            return row[None]
        key = (
            getattr(grants, "key", None)
            or getattr(grants, "quest_id", None)
            # A skill grant keys on the skill name. Without this the stub would report *no*
            # reduction for every skill-granting candidate, which would make the Step 5
            # work-overlap tests below pass whether or not the rule they check exists.
            or getattr(grants, "skill", None)
        )
        return row.get(str(key), row[None])

    return probe


class TestMethodUnlockFraction:
    """A30 — *"how much of another candidate's grind would this delete?"*"""

    def test_the_reduction_is_the_share_of_hours_removed(self) -> None:
        """DT1's own numbers: 113 conservative hours become 16 bursting ones."""
        quest = candidate("quest", grants_facts="unlock: bursting")
        grind = candidate("grind")

        value = method_unlock_fraction(
            quest, [grind], hours_oracle({"grind": {None: 113.0, "bursting": 16.0}})
        )

        assert value == pytest.approx((113 - 16) / 113, abs=1e-3)

    def test_it_takes_the_maximum_never_the_sum(self) -> None:
        """A2's rule for ``pvp_value`` and §9.8's for refresher groups, a third time.

        Three grinds shaved by 20% each must not beat one grind cut by 90%: summing would
        make breadth a substitute for depth, which is the failure the design rejects every
        time it comes up.
        """
        broad = candidate("broad", grants_facts="unlock: broad")
        deep = candidate("deep", grants_facts="unlock: deep")
        others = [candidate(f"g{n}") for n in range(3)]
        table = {
            f"g{n}": {None: 100.0, "broad": 80.0, "deep": 100.0 if n else 10.0} for n in range(3)
        }

        assert method_unlock_fraction(broad, others, hours_oracle(table)) == pytest.approx(0.2)
        assert method_unlock_fraction(deep, others, hours_oracle(table)) == pytest.approx(0.9)

    def test_finishing_part_of_another_grind_is_not_a_method_unlock(self) -> None:
        """The Step 5 regression: work-overlap must not be priced as acceleration.

        Once skill training was decomposed into bands, a candidate granting Magic 94 took
        ``train_magic_85_to_90`` from 39.3 hours to zero and ``train_magic_94_to_99`` from
        258.9 to 145.4. Both are real reductions and neither is a *method*: the two
        candidates measure overlapping XP in the same skill, so the grind did not get
        faster, it was already done. Crediting it let any high-level band claim a perfect
        score for subsuming the bands beneath it, and flipped a recorded §16.3 judgment.
        """
        band = candidate(
            "train_magic_87_to_94",
            completion="skill: {magic: 94}",
            grants_facts="skill: {magic: 94}",
        )
        lower = candidate("train_magic_85_to_90", completion="skill: {magic: 90}")
        higher = candidate("train_magic_94_to_99", completion="skill: {magic: 99}")
        table = {
            "train_magic_85_to_90": {None: 39.3, "magic": 0.0},
            "train_magic_94_to_99": {None: 258.9, "magic": 145.4},
        }

        value = method_unlock_fraction(band, [lower, higher], hours_oracle(table))

        assert value == 0.0

    def test_a_grant_still_accelerates_a_grind_in_a_different_skill(self) -> None:
        """The other half of the rule — the skip is by skill, not a blanket exemption.

        Without this, "skip anything I overlap with" would quietly become "skip
        everything a skill-training candidate could ever accelerate", and A30's own worked
        example is a quest accelerating exactly such a grind.
        """
        band = candidate(
            "train_slayer",
            completion="skill: {slayer: 70}",
            grants_facts="skill: {slayer: 70}",
        )
        other = candidate("train_ranged", completion="skill: {ranged: 90}")

        value = method_unlock_fraction(
            band, [other], hours_oracle({"train_ranged": {None: 100.0, "slayer": 40.0}})
        )

        assert value == pytest.approx(0.6)

    def test_a_candidate_granting_no_facts_unlocks_no_method(self) -> None:
        """Zero, never unknown — :func:`leverage`'s reason, and the probe is never asked."""
        value = method_unlock_fraction(
            candidate("c", grants_facts=None),
            [candidate("other")],
            lambda *_args: pytest.fail("the probe must not be consulted"),
        )
        assert value == 0.0

    def test_a_candidate_is_never_measured_against_itself(self) -> None:
        """Its own grants trivially complete it, which would score every candidate 1.0."""
        alone = candidate("alone", grants_facts="unlock: x")
        value = method_unlock_fraction(
            alone, [alone], hours_oracle({"alone": {None: 100.0, "x": 0.0}})
        )
        assert value == 0.0

    def test_an_unsizable_candidate_contributes_nothing_either_way(self) -> None:
        """§8 returns ``None`` for a quest it cannot size; a ratio of absences is not 1.0."""
        quest = candidate("quest", grants_facts="unlock: x")
        table = {"unsizable": {None: None, "x": None}, "zero": {None: 0.0, "x": 0.0}}

        assert method_unlock_fraction(
            quest, [candidate("unsizable"), candidate("zero")], hours_oracle(table)
        ) == pytest.approx(0.0)

    def test_a_candidate_made_longer_scores_zero_rather_than_negative(self) -> None:
        """The clamp. A negative factor would be a domain error in ``ln``, not a low score."""
        quest = candidate("quest", grants_facts="unlock: x")
        value = method_unlock_fraction(
            quest, [candidate("other")], hours_oracle({"other": {None: 10.0, "x": 40.0}})
        )
        assert value == 0.0


class TestMethodUnlockDetailKeepsTheArgmax:
    """A30's maximum, with the identity and the two sizings it was computed from (§9.10).

    Every assertion here is really about one thing: retaining the identity must not disturb
    the number. This is the only place in the explanation work that touches a scoring
    factor, so a change of tie-break or of floor behaviour here reorders the ranked list.
    """

    def test_the_winner_is_the_candidate_the_maximum_came_from(self) -> None:
        quest = candidate("quest", grants_facts="unlock: bursting")
        table = {
            "shallow": {None: 100.0, "bursting": 80.0},
            "deep": {None: 113.0, "bursting": 16.0},
        }
        others = [candidate("shallow"), candidate("deep")]

        winner = method_unlock_detail(quest, others, hours_oracle(table))

        assert winner is not None
        assert winner.other_id == "deep"

    def test_the_winner_carries_the_two_sizings_the_reduction_was_computed_from(self) -> None:
        """*"cuts X from 113h to 16h"* is only sayable if both numbers survive the argmax."""
        quest = candidate("quest", grants_facts="unlock: bursting")
        winner = method_unlock_detail(
            quest, [candidate("grind")], hours_oracle({"grind": {None: 113.0, "bursting": 16.0}})
        )

        assert winner is not None
        assert (winner.hours_before, winner.hours_after) == (113.0, 16.0)

    def test_the_reduction_is_the_same_float_the_fraction_reports(self) -> None:
        """Not ``approx``. The fraction feeds ``ln`` in §9.4; an equal-looking float is not
        the same score, and a score that moves reorders §16.2's judgments."""
        quest = candidate("quest", grants_facts="unlock: bursting")
        others = [candidate("a"), candidate("b"), candidate("c")]
        table = {
            "a": {None: 113.0, "bursting": 16.0},
            "b": {None: 7.0, "bursting": 3.0},
            "c": {None: 100.0, "bursting": 99.0},
        }

        winner = method_unlock_detail(quest, others, hours_oracle(table))
        fraction = method_unlock_fraction(quest, others, hours_oracle(table))

        assert winner is not None
        assert winner.reduction == fraction

    def test_a_tie_is_won_by_the_first_candidate_in_iteration_order(self) -> None:
        """The strict ``>`` fixes this, and ``others`` arrives in the corpus's own order.

        A non-strict comparison would hand the tie to the *last* equal candidate instead.
        The factor value is identical either way, which is exactly why this needs its own
        test: the bug would be invisible in the ranking and visible only as a *Why* line
        naming a different grind on an unrelated content edit.
        """
        quest = candidate("quest", grants_facts="unlock: x")
        others = [candidate("first"), candidate("second")]
        table = {"first": {None: 100.0, "x": 50.0}, "second": {None: 40.0, "x": 20.0}}

        winner = method_unlock_detail(quest, others, hours_oracle(table))

        assert winner is not None
        assert winner.other_id == "first"

    def test_a_candidate_that_reduces_nothing_has_no_winner(self) -> None:
        """``None``, not a winner holding ``0.0`` — the *Why* line must have nothing to say
        rather than something to say about nothing."""
        quest = candidate("quest", grants_facts="unlock: x")
        table = {"other": {None: 100.0, "x": 100.0}}

        assert method_unlock_detail(quest, [candidate("other")], hours_oracle(table)) is None
        assert method_unlock_fraction(quest, [candidate("other")], hours_oracle(table)) == 0.0

    def test_a_candidate_granting_no_facts_has_no_winner(self) -> None:
        assert (
            method_unlock_detail(
                candidate("c", grants_facts=None),
                [candidate("other")],
                lambda *_args: pytest.fail("the probe must not be consulted"),
            )
            is None
        )

    def test_the_scores_pass_normalizes_exactly_as_the_map_does(self) -> None:
        """``method_unlock_map`` is now a view onto this; the two must not drift apart."""
        big = candidate("big", grants_facts="unlock: big")
        small = candidate("small", grants_facts="unlock: small")
        others = [candidate("grind")]
        table = {"grind": {None: 100.0, "big": 20.0, "small": 60.0}}

        result = method_unlock_scores([big, small], others, hours_oracle(table))

        assert result.normalized == method_unlock_map([big, small], others, hours_oracle(table))
        assert result.winners["big"] is not None
        assert result.winners["big"].other_id == "grind"


class TestMethodUnlockNormalization:
    """A30 borrows :func:`leverage`'s normalization exactly, and must keep borrowing it."""

    def test_the_best_candidate_scores_one(self) -> None:
        assert method_unlock(0.86, 0.86) == pytest.approx(1.0)

    def test_the_rest_scale_against_it(self) -> None:
        assert method_unlock(0.43, 0.86) == pytest.approx(0.5)

    def test_a_candidate_unlocking_no_faster_method_scores_zero(self) -> None:
        """Floored at ε by the scorer, not here — a genuine zero must survive to §6.10."""
        assert method_unlock(0.0, 0.86) == 0.0

    def test_when_nothing_unlocks_a_faster_method_the_factor_does_not_discriminate(self) -> None:
        assert method_unlock(0.0, 0.0) == 0.0

    def test_the_map_normalizes_within_the_set(self) -> None:
        big = candidate("big", grants_facts="unlock: big")
        small = candidate("small", grants_facts="unlock: small")
        inert = candidate("inert", grants_facts="unlock: inert")
        others = [candidate("grind")]
        table = {"grind": {None: 100.0, "big": 20.0, "small": 60.0}}

        scores = method_unlock_map([big, small, inert], others, hours_oracle(table))

        assert scores["big"] == pytest.approx(1.0)
        assert scores["small"] == pytest.approx(0.5)
        assert scores["inert"] == 0.0

    def test_the_measured_set_may_be_wider_than_the_scored_set(self) -> None:
        """A blocked candidate cannot rank but can certainly be made cheaper (A30).

        The engine passes every *open* candidate as ``others`` while scoring only the
        unblocked ones, because unblocking a 113-hour grind *and* making it a 16-hour one is
        the largest form of the effect the factor exists to see.
        """
        quest = candidate("quest", grants_facts="unlock: x")
        table = {"blocked_grind": {None: 100.0, "x": 10.0}}

        scores = method_unlock_map([quest], [candidate("blocked_grind")], hours_oracle(table))

        assert scores["quest"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# proximity (§9.4, §10.6, A3)
# ---------------------------------------------------------------------------


class TestSkillTrainingProximity:
    """§10.6 — `1 − remaining_xp / span_xp` for `kind: skill_training`."""

    def test_progress_along_the_curve(self, content: Content) -> None:
        near = candidate(kind=CandidateKind.SKILL_TRAINING, completion="skill: {magic: 94}")
        state = PlayerState(player_id=1, skills=skills(magic=87))

        # 8600 xp of the 9300 the target needs, on the synthetic curve.
        assert proximity(near, state, content, always(Tri.UNSATISFIED), linear_xp) == pytest.approx(
            8600 / 9300
        )

    def test_the_closer_target_scores_higher_for_the_same_account(self, content: Content) -> None:
        """§16.2 — of two otherwise identical candidates, the closer one ranks higher.
        This is the invariant the v0.1 formula inverted (§9.4)."""
        state = PlayerState(player_id=1, skills=skills(magic=87))
        to_94 = candidate("a", kind=CandidateKind.SKILL_TRAINING, completion="skill: {magic: 94}")
        to_99 = candidate("b", kind=CandidateKind.SKILL_TRAINING, completion="skill: {magic: 99}")

        evaluate = always(Tri.UNSATISFIED)
        assert proximity(to_94, state, content, evaluate, linear_xp) > proximity(
            to_99, state, content, evaluate, linear_xp
        )

    def test_an_unranked_skill_falls_back_to_its_level_never_to_zero_xp(
        self, content: Content
    ) -> None:
        """G5 — `xp IS NULL` means unranked, which is not the same as no progress."""
        unranked = PlayerState(
            player_id=1,
            skills={
                "magic": SkillState(level=87, xp=None, source=Source.HISCORES, observed_at=NOW)
            },
        )
        target = candidate(kind=CandidateKind.SKILL_TRAINING, completion="skill: {magic: 94}")

        assert proximity(
            target, unranked, content, always(Tri.UNSATISFIED), linear_xp
        ) == pytest.approx(8600 / 9300)

    def test_a_never_observed_skill_is_the_whole_way_away(self, content: Content) -> None:
        target = candidate(kind=CandidateKind.SKILL_TRAINING, completion="skill: {magic: 94}")
        assert proximity(
            target, PlayerState(player_id=1), content, always(Tri.UNKNOWN), linear_xp
        ) == pytest.approx(0.0)

    def test_several_skill_targets_take_the_most_distant(self, content: Content) -> None:
        """Averaging would let a nearly-done skill mask one barely started."""
        both = candidate(
            kind=CandidateKind.SKILL_TRAINING,
            completion="all_of: [{skill: {magic: 94}}, {skill: {defence: 94}}]",
        )
        state = PlayerState(player_id=1, skills=skills(magic=93, defence=50))

        assert proximity(both, state, content, always(Tri.UNSATISFIED), linear_xp) == pytest.approx(
            4900 / 9300
        )

    def test_proximity_is_capped_at_one_when_the_target_is_passed(self, content: Content) -> None:
        done = candidate(kind=CandidateKind.SKILL_TRAINING, completion="skill: {magic: 94}")
        state = PlayerState(player_id=1, skills=skills(magic=99))
        assert proximity(done, state, content, always(Tri.SATISFIED, 1, 1), linear_xp) == 1.0


class TestGeneralProximity:
    """§10.6, A3 — every other kind uses the `completion` predicate's unlock_fraction."""

    def test_uses_the_completion_unlock_fraction(self, content: Content) -> None:
        acquisition = candidate(kind=CandidateKind.ACQUISITION, completion="item: voidwaker")
        evaluate = always(Tri.UNSATISFIED, satisfied=1, total=2)

        assert proximity(
            acquisition, PlayerState(player_id=1), content, evaluate, linear_xp
        ) == pytest.approx(0.5)

    def test_unknown_leaves_stay_in_the_denominator(self, content: Content) -> None:
        """§6.9 — one satisfied, one unsatisfied and one unknown leaf reports 0.33, not
        0.50. Crediting unknowns would let an unobserved account look like it is
        progressing; dropping them would make it look *closer* than an observed one."""
        quest = candidate(kind=CandidateKind.QUEST, completion="quest: desert_treasure_i")
        evaluate = always(Tri.UNKNOWN, satisfied=1, total=3)

        assert proximity(
            quest, PlayerState(player_id=1), content, evaluate, linear_xp
        ) == pytest.approx(1 / 3)

    def test_a_skill_training_candidate_with_no_skill_target_falls_back(
        self, content: Content
    ) -> None:
        odd = candidate(kind=CandidateKind.SKILL_TRAINING, completion="unlock: something")
        evaluate = always(Tri.UNSATISFIED, satisfied=1, total=4)

        assert proximity(
            odd, PlayerState(player_id=1), content, evaluate, linear_xp
        ) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# completed (§16.2)
# ---------------------------------------------------------------------------


class TestCompleted:
    """§10.6 — `completion` evaluates `satisfied`. §16.2 — a completed candidate never
    ranks, and completion is tested *before* scoring rather than approximated by a low
    score."""

    def test_satisfied_completion_is_complete(self, content: Content) -> None:
        assert completed(candidate(), PlayerState(player_id=1), content, always(Tri.SATISFIED))

    def test_unsatisfied_completion_is_not(self, content: Content) -> None:
        assert not completed(
            candidate(), PlayerState(player_id=1), content, always(Tri.UNSATISFIED)
        )

    def test_unknown_completion_is_not_complete(self, content: Content) -> None:
        """ "We have never looked in your bank" is a reason to sync, not a reason to
        declare the Voidwaker bought (§4.5)."""
        assert not completed(candidate(), PlayerState(player_id=1), content, always(Tri.UNKNOWN))


# ---------------------------------------------------------------------------
# blocked and the gate (§9.4, G3)
# ---------------------------------------------------------------------------


class TestTheReadinessGate:
    def test_no_gate_means_ready(self, content: Content) -> None:
        free = candidate(requires=None)
        assert gate_value(free, PlayerState(player_id=1), content, always(Tri.UNKNOWN)) is (
            Tri.SATISFIED
        )
        assert not blocked(free, PlayerState(player_id=1), content, always(Tri.UNKNOWN))

    def test_an_unsatisfied_gate_blocks(self, content: Content) -> None:
        gated = candidate(requires="unlock: ancient_magicks")
        assert blocked(gated, PlayerState(player_id=1), content, always(Tri.UNSATISFIED))

    def test_a_satisfied_gate_does_not_block(self, content: Content) -> None:
        gated = candidate(requires="unlock: ancient_magicks")
        assert not blocked(gated, PlayerState(player_id=1), content, always(Tri.SATISFIED))


class TestAnUnknownGateIsNotBlocked:
    """§10.6, D11, G3 — *"A candidate whose `requires` evaluates `unknown` is not
    blocked."* It is unknown, and belongs with the capability unknowns: "sync this", not
    "do this". Collapsing unknown into blocked is the D8 error one layer out, and §16.2
    lists it precisely because `if gate is not Tri.SATISFIED` passes every other test.
    """

    def test_unknown_does_not_block(self, content: Content) -> None:
        gated = candidate(requires="item: voidwaker")
        assert not blocked(gated, PlayerState(player_id=1), content, always(Tri.UNKNOWN))

    def test_unknown_is_reported_as_unknown_not_as_readiness(self, content: Content) -> None:
        gated = candidate(requires="item: voidwaker")
        assert gate_value(gated, PlayerState(player_id=1), content, always(Tri.UNKNOWN)) is (
            Tri.UNKNOWN
        )

    def test_the_three_gate_values_are_all_distinguishable(self, content: Content) -> None:
        """Two booleans (`blocked`, `unknown_gate`) reconstructed from one `Tri` — and
        `Tri.__bool__` raises, so a derivation that reached for `if gate:` would fail
        here rather than silently treating unknown as ready."""
        gated = candidate(requires="item: voidwaker")
        seen = {
            value: gate_value(gated, PlayerState(player_id=1), content, always(value))
            for value in Tri
        }
        assert seen == {value: value for value in Tri}


# ---------------------------------------------------------------------------
# The step 4 seam
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractShapedResult:
    """Step 4's `EvalResult`, reproduced field for field from its frozen contract."""

    value: Tri
    blockers: tuple[object, ...]
    unknowns: tuple[object, ...]
    satisfied_leaves: int
    total_leaves: int


def contract_shaped_evaluate(
    requirement: Requirement, state: PlayerState, content: Content
) -> ContractShapedResult:
    """Positional, like step 4's `evaluate(requirement, state, content)`."""
    del requirement, state, content
    return ContractShapedResult(Tri.UNKNOWN, (), (), 1, 4)


class TestTheStep4Seam:
    """The derivations must accept the real evaluator structurally, with neither package
    importing the other."""

    def test_every_derivation_accepts_the_frozen_contract_shape(self, content: Content) -> None:
        subject = candidate(
            kind=CandidateKind.ACQUISITION,
            requires="item: voidwaker",
            completion="item: voidwaker",
        )
        state = PlayerState(player_id=1)

        assert not completed(subject, state, content, contract_shaped_evaluate)
        assert not blocked(subject, state, content, contract_shaped_evaluate)
        assert gate_value(subject, state, content, contract_shaped_evaluate) is Tri.UNKNOWN
        assert proximity(
            subject, state, content, contract_shaped_evaluate, linear_xp
        ) == pytest.approx(0.25)

    def test_the_module_does_not_import_the_progression_package(self) -> None:
        """Step 4 is built in parallel; a real import here would be a hard dependency on
        a package that does not exist yet, and a cycle once it does."""
        source = (
            Path(__file__).parent.parent.parent / "tracker" / "domain" / "candidates.py"
        ).read_text(encoding="utf-8")
        assert "import tracker.progression" not in source
        assert "from tracker.progression" not in source
