"""§9.3's blending, §9.4/§9.5's scorer, and §9.10's generated reason line."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tracker.content.loader import Content
from tracker.content.schema import ScoringProfile
from tracker.domain.candidates import advances_value, pvp_value
from tracker.domain.types import FactorContribution, GpSensitivity, RoadmapSelection
from tracker.recommendations.blending import effective_capability_weights
from tracker.recommendations.reasons import headroom, reason
from tracker.recommendations.scoring import (
    FACTOR_NAMES,
    cost_decay,
    effort_decay,
    kappa_for,
    score,
)

#: §4.3's worked selection, which §9.3's table is computed under.
WORKED_SELECTION = RoadmapSelection({"main_nh": 0.75, "anti_pk": 0.25})

PERFECT = dict.fromkeys(FACTOR_NAMES, 1.0)


class TestBlending:
    """§9.3 — one capability-weight map, convex by construction (D3)."""

    def test_reproduces_the_worked_table(self, seed_content: Content) -> None:
        """The two rows §9.3 computes by hand, from the shipped roadmaps."""
        weights = effective_capability_weights(WORKED_SELECTION, seed_content)

        assert weights["ice_barrage_nh"] == pytest.approx(0.90)
        assert weights["vengeance_pvp"] == pytest.approx(0.375)

    def test_a_shared_capability_blends_rather_than_accumulates(
        self, seed_content: Content
    ) -> None:
        """§9.3's headline case: ``0.75(1.0) + 0.25(0.6) = 0.90``, never ``1.6``.

        ``ice_barrage_nh`` is weighted by both shipped roadmaps, so a summing implementation
        exceeds 1.0 here — and every other factor is normalized to (0,1].
        """
        weights = effective_capability_weights(WORKED_SELECTION, seed_content)

        assert weights["ice_barrage_nh"] <= 1.0

    def test_selection_weights_are_normalized_at_read_time(self, seed_content: Content) -> None:
        """Doubling every selection weight changes nothing — they are shares, not amounts."""
        once = effective_capability_weights(WORKED_SELECTION, seed_content)
        twice = effective_capability_weights(
            RoadmapSelection({"main_nh": 1.5, "anti_pk": 0.5}), seed_content
        )

        assert once == pytest.approx(dict(twice))

    def test_an_empty_selection_weights_nothing(self, seed_content: Content) -> None:
        assert effective_capability_weights(RoadmapSelection({}), seed_content) == {}

    @given(
        main=st.floats(min_value=0.0, max_value=100.0),
        anti=st.floats(min_value=0.0, max_value=100.0),
    )
    def test_blending_is_convex_for_any_selection(
        self, seed_content: Content, main: float, anti: float
    ) -> None:
        """Property: every blended weight lands in [0,1] whatever the user selects.

        This is the guarantee §9.3 leans on to skip a second normalization pass, so it is
        asserted over arbitrary selections rather than over the one worked example.
        """
        weights = effective_capability_weights(
            RoadmapSelection({"main_nh": main, "anti_pk": anti}), seed_content
        )

        assert all(0.0 <= weight <= 1.0 for weight in weights.values())


class TestPvpValue:
    """§9.3, A2 — blend first, then take the **maximum** over ``advances``."""

    def test_reproduces_the_worked_candidate_value(self, seed_content: Content) -> None:
        weights = effective_capability_weights(WORKED_SELECTION, seed_content)

        assert pvp_value(seed_content.candidates["train_magic_87_to_94"], weights) == pytest.approx(
            0.90
        )

    def test_a_multi_capability_candidate_takes_the_max_not_the_sum(
        self, seed_content: Content
    ) -> None:
        """``buy_voidwaker`` advances two capabilities; summed they exceed either alone.

        The corpus authors that candidate as this test's subject (see
        ``content/candidates/acquisitions.yaml``): breadth must not substitute for
        relevance, which is also §9.8's rule for refresher group size (D11).
        """
        weights = effective_capability_weights(WORKED_SELECTION, seed_content)
        candidate = seed_content.candidates["buy_voidwaker"]

        terms = [
            weights.get(capability_id, 0.0) * contribution
            for capability_id, contribution in candidate.advances.items()
        ]

        assert pvp_value(candidate, weights) == pytest.approx(max(terms))
        assert pvp_value(candidate, weights) < sum(terms)

    def test_a_candidate_advancing_nothing_scores_zero(self, seed_content: Content) -> None:
        """``train_woodcutting`` declares an empty ``advances`` map and must say so.

        Zero, not ε: the floor belongs to the scorer, so what is *derived* here stays an
        honest statement about the content (§10.8).
        """
        weights = effective_capability_weights(WORKED_SELECTION, seed_content)

        assert pvp_value(seed_content.candidates["train_woodcutting"], weights) == 0.0

    def test_the_bare_map_form_agrees_with_the_candidate_form(self, seed_content: Content) -> None:
        """Refreshers are scored through ``advances_value`` and must use the same rule."""
        weights = effective_capability_weights(WORKED_SELECTION, seed_content)
        candidate = seed_content.candidates["buy_voidwaker"]

        assert advances_value(candidate.advances, weights) == pvp_value(candidate, weights)


class TestScaleConstants:
    """§9.6 — τ and κ, and what happens when a magnitude is unknown."""

    def test_kappa_follows_the_gp_sensitivity_preference(self, profile: ScoringProfile) -> None:
        assert kappa_for(GpSensitivity.HIGH, profile) < kappa_for(GpSensitivity.NORMAL, profile)
        assert kappa_for(GpSensitivity.NORMAL, profile) < kappa_for(GpSensitivity.LOW, profile)

    def test_cost_decay_reproduces_the_worked_table(self, profile: ScoringProfile) -> None:
        """§9.6's table: a 10M purchase reads 0.29 / 0.61 / 0.82 across the three presets."""
        assert cost_decay(10_000_000, profile.kappa_gp.high) == pytest.approx(0.29, abs=0.01)
        assert cost_decay(10_000_000, profile.kappa_gp.normal) == pytest.approx(0.61, abs=0.01)
        assert cost_decay(10_000_000, profile.kappa_gp.low) == pytest.approx(0.82, abs=0.01)

    def test_one_kappa_of_cost_scores_the_e_inverse_anchor(self, profile: ScoringProfile) -> None:
        """§9.6: *"κ is the purchase size at which cost becomes a strong negative"*."""
        assert cost_decay(profile.kappa_gp.normal, profile.kappa_gp.normal) == pytest.approx(
            math.exp(-1)
        )

    def test_a_free_candidate_scores_a_perfect_cost_factor(self, profile: ScoringProfile) -> None:
        assert cost_decay(0, profile.kappa_gp.normal) == 1.0

    def test_unknown_hours_are_charged_the_authored_scale_not_zero(
        self, profile: ScoringProfile
    ) -> None:
        """The A8 defect, one candidate kind over.

        A quest has no skill target and no session length, so §8 sizes it ``None``. Read as
        zero that would score ``exp(0) = 1.0`` — a *perfect* effort mark for the candidate
        whose effort is least known — and the list would fill with quests.
        """
        assert effort_decay(None, profile) < 1.0
        assert effort_decay(None, profile) == pytest.approx(
            math.exp(-profile.unknown_effort_hours / profile.tau_hours)
        )

    def test_unknown_cost_is_charged_one_kappa_not_zero(self, profile: ScoringProfile) -> None:
        """The GP half of the same gap, and why it needs no field of its own."""
        kappa = profile.kappa_gp.normal

        assert cost_decay(None, kappa) == pytest.approx(math.exp(-1))
        assert cost_decay(None, kappa) < cost_decay(0, kappa)

    def test_the_unknown_charge_is_authored_and_therefore_tunable(
        self, make_profile: Callable[..., ScoringProfile]
    ) -> None:
        """§10.8 — moving the knob moves the answer, with no code change."""
        lenient = make_profile(unknown_effort_hours=1.0)
        harsh = make_profile(unknown_effort_hours=40.0)

        assert effort_decay(None, lenient) > effort_decay(None, harsh)

    def test_effort_decay_is_monotone_in_hours(self, profile: ScoringProfile) -> None:
        assert effort_decay(1.0, profile) > effort_decay(5.0, profile)
        assert effort_decay(5.0, profile) > effort_decay(50.0, profile)


class TestScorer:
    """§9.4/§9.5 — the weighted geometric mean, evaluated additively in log space."""

    def test_a_perfect_candidate_scores_one(self, profile: ScoringProfile) -> None:
        raw, factors = score(PERFECT, profile)

        assert raw == pytest.approx(1.0)
        assert all(entry.log_contribution == pytest.approx(0.0) for entry in factors.values())

    def test_the_log_contributions_sum_to_the_log_score(self, profile: ScoringProfile) -> None:
        """§9.5's whole claim: the parts are additive, and they add up to the whole."""
        values = {
            "pvp_value": 0.9,
            "leverage": 0.5,
            "proximity": 0.3,
            "effort_decay": 0.6,
            "cost_decay": 0.8,
        }
        raw, factors = score(values, profile)

        total = sum(entry.log_contribution for entry in factors.values())
        assert math.log(raw) == pytest.approx(total)

    def test_it_agrees_with_the_product_form(self, profile: ScoringProfile) -> None:
        """§9.5: *"mathematically identical"* — asserted, not assumed."""
        values = {
            "pvp_value": 0.9,
            "leverage": 0.5,
            "proximity": 0.3,
            "effort_decay": 0.6,
            "cost_decay": 0.8,
        }
        raw, _ = score(values, profile)

        product = math.prod(values[name] ** getattr(profile.weights, name) for name in FACTOR_NAMES)
        assert raw == pytest.approx(product)

    def test_a_zero_factor_is_floored_rather_than_annihilating(
        self, profile: ScoringProfile
    ) -> None:
        """§9.4's ε: *"so no single term can annihilate a score"* — and so ``ln(0)`` never
        happens, which would raise rather than merely mis-rank."""
        raw, _ = score({**PERFECT, "leverage": 0.0}, profile)

        assert raw > 0.0
        assert raw == pytest.approx(profile.epsilon**profile.weights.leverage)

    def test_the_persisted_value_is_the_derived_one_not_the_floored_one(
        self, profile: ScoringProfile
    ) -> None:
        """§6.10 keeps both halves. A persisted 0.0 records that the candidate advances
        nothing; a persisted ε would record a tuning constant and lose the fact."""
        _, factors = score({**PERFECT, "pvp_value": 0.0}, profile)

        assert factors["pvp_value"].value == 0.0
        assert factors["pvp_value"].log_contribution == pytest.approx(
            profile.weights.pvp_value * math.log(profile.epsilon)
        )

    def test_every_factor_carries_its_weight(self, profile: ScoringProfile) -> None:
        _, factors = score(PERFECT, profile)

        for name in FACTOR_NAMES:
            assert factors[name].weight == getattr(profile.weights, name)

    def test_a_missing_factor_is_an_error_not_a_default(self, profile: ScoringProfile) -> None:
        """Omitting a term *raises* the score, since every log contribution is ≤ 0 — so a
        default would make a gap look like a strength."""
        with pytest.raises(KeyError, match="missing"):
            score({name: 1.0 for name in FACTOR_NAMES if name != "cost_decay"}, profile)

    def test_raising_one_factor_never_lowers_the_score(self, profile: ScoringProfile) -> None:
        """Monotonicity in every argument — the property §16.2's pairwise judgments assume."""
        base, _ = score({**PERFECT, "proximity": 0.4}, profile)
        better, _ = score({**PERFECT, "proximity": 0.8}, profile)

        assert better > base


class TestReasonGeneration:
    """§9.5, §9.10 — the *"Why"* line is read off the ranking, never authored."""

    def _factors(self, profile: ScoringProfile, **values: float) -> dict[str, FactorContribution]:
        _, factors = score({**PERFECT, **values}, profile)
        return factors

    def test_credits_are_positive_and_ordered_strongest_first(
        self, profile: ScoringProfile
    ) -> None:
        """§9.10 shows ``+0.61 · +0.44 · +0.30``: positive, and descending."""
        factors = self._factors(profile, leverage=0.5, proximity=0.2, cost_decay=0.05)
        line = reason(factors, profile)

        credits = [float(part.rsplit("+", 1)[1].rstrip(")")) for part in line.split(" · ")]
        assert credits == sorted(credits, reverse=True)
        assert all(credit > 0 for credit in credits)

    def test_it_names_three_factors(self, profile: ScoringProfile) -> None:
        factors = self._factors(profile, leverage=0.5, proximity=0.2, cost_decay=0.05)

        assert len(reason(factors, profile).split(" · ")) == 3

    def test_headroom_is_zero_at_the_floor(self, profile: ScoringProfile) -> None:
        """A factor at ε earned nothing above the worst case, so it is not a reason."""
        contribution = FactorContribution(
            name="leverage", value=0.0, weight=0.8, log_contribution=-3.7
        )

        assert headroom(contribution, profile) == pytest.approx(0.0)

    def test_a_candidate_at_the_floor_everywhere_gets_no_reason(
        self, profile: ScoringProfile
    ) -> None:
        """Silence beats invention. Manufacturing prose here is what §9.5 forbids."""
        _, factors = score(dict.fromkeys(FACTOR_NAMES, 0.0), profile)

        assert reason(factors, profile) == ""

    def test_a_detail_override_replaces_words_but_not_the_credit(
        self, profile: ScoringProfile
    ) -> None:
        """§9.10's *"unblocks 2 capabilities"* — the count is known where the counting was."""
        factors = self._factors(profile, leverage=0.9, proximity=0.1, cost_decay=0.1)

        generic = reason(factors, profile)
        specific = reason(factors, profile, details={"leverage": "unblocks 2 capabilities"})

        assert "unblocks 2 capabilities" in specific
        credit = f"(+{headroom(factors['leverage'], profile):.2f})"
        assert credit in generic and credit in specific

    def test_the_leading_reason_is_the_factor_that_actually_distinguishes(
        self, profile: ScoringProfile
    ) -> None:
        """The failure headroom exists to prevent.

        Ranked by raw log contribution, the "largest" term is whichever factor sits closest
        to 1.0 — so a candidate that merely happens to be free would report *"cheap"* as the
        reason it won, even when high PvP value is what put it on top.
        """
        factors = self._factors(profile, pvp_value=0.95, cost_decay=1.0, leverage=0.02)

        assert reason(factors, profile).startswith("high PvP value")
