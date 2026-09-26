"""Three-valued requirement logic keeps missing facts uncertain."""

from __future__ import annotations

import pytest

from tracker.domain.tri import and_all, at_least, negate, or_any
from tracker.domain.types import Tri

SAT = Tri.SATISFIED
NO = Tri.UNSATISFIED
UNK = Tri.UNKNOWN


@pytest.mark.parametrize(
    ("left", "right", "conjunction", "disjunction"),
    [
        (SAT, SAT, SAT, SAT),
        (SAT, NO, NO, SAT),
        (SAT, UNK, UNK, SAT),
        (NO, SAT, NO, SAT),
        (NO, NO, NO, NO),
        (NO, UNK, NO, UNK),
        (UNK, SAT, UNK, SAT),
        (UNK, NO, NO, UNK),
        (UNK, UNK, UNK, UNK),
    ],
)
def test_binary_truth_tables(left: Tri, right: Tri, conjunction: Tri, disjunction: Tri) -> None:
    assert and_all((left, right)) is conjunction
    assert or_any((left, right)) is disjunction


def test_unknown_is_preserved_by_negation_and_thresholds() -> None:
    assert negate(SAT) is NO
    assert negate(NO) is SAT
    assert negate(UNK) is UNK
    assert at_least((SAT, UNK, NO), 2) is UNK
    assert at_least((SAT, NO, NO), 2) is NO
    assert at_least((SAT, SAT, UNK), 2) is SAT
