"""Kleene combinator truth tables (§9.1).

Every table is checked twice: entry by entry against the specification transcribed by
hand, and exhaustively over every arity-1..3 input against a reference implementation
written from §9.1's prose rather than from ``tri.py``. If the two ever disagree, one of
them is a transcription error — which is the only kind of bug a truth table can have.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tracker.domain.types import Tri
from tracker.progression.tri import (
    AND_TABLE,
    NOT_TABLE,
    OR_TABLE,
    and_all,
    at_least,
    negate,
    or_any,
)

SAT = Tri.SATISFIED
UNSAT = Tri.UNSATISFIED
UNK = Tri.UNKNOWN

ALL = (SAT, UNSAT, UNK)
tri_values = st.sampled_from(ALL)


def combinations(size: int) -> list[tuple[Tri, ...]]:
    return list(itertools.product(ALL, repeat=size))


# --- reference implementations, transcribed from §9.1's prose ---------------


def reference_all_of(values: Sequence[Tri]) -> Tri:
    """*"unsatisfied if any child is unsatisfied; else unknown if any child is unknown;
    else satisfied"*."""
    if any(value is UNSAT for value in values):
        return UNSAT
    if any(value is UNK for value in values):
        return UNK
    return SAT


def reference_any_of(values: Sequence[Tri]) -> Tri:
    """*"satisfied if any child is satisfied; else unknown if any child is unknown; else
    unsatisfied"*."""
    if any(value is SAT for value in values):
        return SAT
    if any(value is UNK for value in values):
        return UNK
    return UNSAT


def reference_at_least(values: Sequence[Tri], n: int) -> Tri:
    """*"satisfied if count(satisfied) ≥ n; unsatisfied if count(satisfied) +
    count(unknown) < n; else unknown"*."""
    satisfied = sum(1 for value in values if value is SAT)
    unknown = sum(1 for value in values if value is UNK)
    if satisfied >= n:
        return SAT
    if satisfied + unknown < n:
        return UNSAT
    return UNK


class TestAndAll:
    """``all_of`` — Kleene conjunction (§9.1)."""

    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [
            (SAT, SAT, SAT),
            (SAT, UNSAT, UNSAT),
            (SAT, UNK, UNK),
            (UNSAT, SAT, UNSAT),
            (UNSAT, UNSAT, UNSAT),
            (UNSAT, UNK, UNSAT),
            (UNK, SAT, UNK),
            (UNK, UNSAT, UNSAT),
            (UNK, UNK, UNK),
        ],
    )
    def test_every_entry_of_the_binary_table(self, left: Tri, right: Tri, expected: Tri) -> None:
        assert AND_TABLE[left, right] is expected
        assert and_all([left, right]) is expected

    @pytest.mark.parametrize("size", [1, 2, 3])
    def test_exhaustive_against_the_specification(self, size: int) -> None:
        for values in combinations(size):
            assert and_all(values) is reference_all_of(values), values

    def test_a_definite_unsatisfied_beats_sibling_unknowns(self) -> None:
        """§9.1: *"a definite unsatisfied in an all_of short-circuits to unsatisfied even
        when siblings are unknown, because the requirement genuinely cannot be met."*"""
        assert and_all([UNK, UNSAT, UNK]) is UNSAT

    @pytest.mark.parametrize("values", [(UNSAT, UNK), (UNK, UNSAT)])
    def test_the_result_does_not_depend_on_child_order(self, values: tuple[Tri, ...]) -> None:
        assert and_all(values) is UNSAT

    def test_the_empty_conjunction_is_satisfied(self) -> None:
        """Vacuous truth — the answer a capability with no `requires` needs."""
        assert and_all([]) is SAT


class TestOrAny:
    """``any_of`` — Kleene disjunction (§9.1)."""

    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [
            (SAT, SAT, SAT),
            (SAT, UNSAT, SAT),
            (SAT, UNK, SAT),
            (UNSAT, SAT, SAT),
            (UNSAT, UNSAT, UNSAT),
            (UNSAT, UNK, UNK),
            (UNK, SAT, SAT),
            (UNK, UNSAT, UNK),
            (UNK, UNK, UNK),
        ],
    )
    def test_every_entry_of_the_binary_table(self, left: Tri, right: Tri, expected: Tri) -> None:
        assert OR_TABLE[left, right] is expected
        assert or_any([left, right]) is expected

    @pytest.mark.parametrize("size", [1, 2, 3])
    def test_exhaustive_against_the_specification(self, size: int) -> None:
        for values in combinations(size):
            assert or_any(values) is reference_any_of(values), values

    def test_a_definite_satisfied_wins_outright(self) -> None:
        """§9.1: *"a definite satisfied in an any_of wins outright."*"""
        assert or_any([UNK, SAT, UNSAT]) is SAT

    @pytest.mark.parametrize("values", [(UNK, SAT), (SAT, UNK)])
    def test_the_result_does_not_depend_on_child_order(self, values: tuple[Tri, ...]) -> None:
        assert or_any(values) is SAT

    def test_unsatisfied_beside_unknown_is_unknown_not_unsatisfied(self) -> None:
        """The row that would collapse if `unknown` were treated as `false`."""
        assert or_any([UNSAT, UNK]) is UNK

    def test_the_empty_disjunction_is_unsatisfied(self) -> None:
        assert or_any([]) is UNSAT


class TestNegate:
    """``not`` — swaps the definite values; ``unknown`` is a fixed point (§9.1)."""

    @pytest.mark.parametrize(("value", "expected"), [(SAT, UNSAT), (UNSAT, SAT), (UNK, UNK)])
    def test_every_entry(self, value: Tri, expected: Tri) -> None:
        assert NOT_TABLE[value] is expected
        assert negate(value) is expected

    @pytest.mark.parametrize("value", ALL)
    def test_double_negation_is_identity(self, value: Tri) -> None:
        assert negate(negate(value)) is value


class TestAtLeast:
    """``at_least: {n, of: [...]}`` (§9.1)."""

    @pytest.mark.parametrize("size", [1, 2, 3])
    def test_exhaustive_against_the_specification(self, size: int) -> None:
        for values in combinations(size):
            for n in range(1, size + 1):
                assert at_least(values, n) is reference_at_least(values, n), (values, n)

    def test_satisfied_when_enough_children_are_satisfied(self) -> None:
        assert at_least([SAT, SAT, UNSAT], 2) is SAT

    def test_unsatisfied_when_even_the_unknowns_could_not_close_the_gap(self) -> None:
        assert at_least([SAT, UNSAT, UNSAT], 2) is UNSAT

    def test_unknown_when_the_unknowns_could_still_close_the_gap(self) -> None:
        """The middle row: counting unknowns as failures here is the D8 collapse."""
        assert at_least([SAT, UNK, UNSAT], 2) is UNK

    def test_unknowns_alone_can_carry_the_result_to_unknown(self) -> None:
        assert at_least([UNK, UNK], 2) is UNK

    def test_n_of_one_matches_any_of(self) -> None:
        for values in combinations(3):
            assert at_least(values, 1) is or_any(values)

    def test_n_equal_to_the_child_count_matches_all_of(self) -> None:
        for values in combinations(3):
            assert at_least(values, len(values)) is and_all(values)


class TestKleeneAlgebra:
    """Properties §9.1 relies on without stating: the folds are order-independent."""

    @given(left=tri_values, right=tri_values)
    def test_conjunction_commutes(self, left: Tri, right: Tri) -> None:
        assert and_all([left, right]) is and_all([right, left])

    @given(left=tri_values, right=tri_values)
    def test_disjunction_commutes(self, left: Tri, right: Tri) -> None:
        assert or_any([left, right]) is or_any([right, left])

    @given(a=tri_values, b=tri_values, c=tri_values)
    def test_conjunction_associates(self, a: Tri, b: Tri, c: Tri) -> None:
        assert and_all([and_all([a, b]), c]) is and_all([a, and_all([b, c])])

    @given(a=tri_values, b=tri_values, c=tri_values)
    def test_de_morgan(self, a: Tri, b: Tri, c: Tri) -> None:
        """``not(a and b and c) == (not a) or (not b) or (not c)`` holds in Kleene logic."""
        assert negate(and_all([a, b, c])) is or_any([negate(a), negate(b), negate(c)])


class TestNoCombinatorCoercesToBool:
    """``Tri.__bool__`` raises, so any hidden ``if value:`` here would fail loudly (§9.1)."""

    @pytest.mark.parametrize("values", combinations(2))
    def test_every_input_pair_passes_through_every_combinator(
        self, values: tuple[Tri, ...]
    ) -> None:
        and_all(values)
        or_any(values)
        at_least(values, 1)
        for value in values:
            negate(value)
