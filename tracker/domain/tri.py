"""Kleene three-valued combinators for factual requirement evaluation.

§9.1 fixes the semantics of the four combinators of the §10.2 grammar:

* ``all_of`` — ``unsatisfied`` if any child is unsatisfied; else ``unknown`` if any child
  is unknown; else ``satisfied``.
* ``any_of`` — ``satisfied`` if any child is satisfied; else ``unknown`` if any child is
  unknown; else ``unsatisfied``.
* ``not`` — swaps satisfied ↔ unsatisfied; ``unknown`` maps to ``unknown``.
* ``at_least`` — ``satisfied`` if ``count(satisfied) ≥ n``; ``unsatisfied`` if
  ``count(satisfied) + count(unknown) < n``; else ``unknown``.

They are written here as **literal truth tables** rather than as conditionals. A
conditional chain over three values is where the §9.1 failure mode hides: a missing arm
falls through to the wrong default and no reader can see which of the nine cases is
absent. A nine-entry table can be checked against the specification by eye, and the tests
enumerate every entry.

The n-ary forms fold their binary table. That is sound because Kleene conjunction and
disjunction are associative and commutative, and it is what makes the §9.1 ordering
guarantees fall out rather than needing to be coded: ``AND(unsatisfied, unknown)`` is
``unsatisfied``, so a definite ``unsatisfied`` in an ``all_of`` beats sibling unknowns
whatever order the children arrive in.

**Nothing here short-circuits.** The evaluator must visit every child anyway to collect
blockers, unknowns and the leaf counts behind ``unlock_fraction`` (§6.9), so these
functions take already-evaluated values and short-circuiting would save nothing while
making the ordering guarantees depend on iteration order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from tracker.domain.types import Tri

_SAT = Tri.SATISFIED
_UNSAT = Tri.UNSATISFIED
_UNK = Tri.UNKNOWN

#: Kleene conjunction. ``unsatisfied`` absorbs — including over ``unknown``.
AND_TABLE: Mapping[tuple[Tri, Tri], Tri] = {
    (_SAT, _SAT): _SAT,
    (_SAT, _UNSAT): _UNSAT,
    (_SAT, _UNK): _UNK,
    (_UNSAT, _SAT): _UNSAT,
    (_UNSAT, _UNSAT): _UNSAT,
    (_UNSAT, _UNK): _UNSAT,
    (_UNK, _SAT): _UNK,
    (_UNK, _UNSAT): _UNSAT,
    (_UNK, _UNK): _UNK,
}

#: Kleene disjunction. ``satisfied`` absorbs — including over ``unknown``.
OR_TABLE: Mapping[tuple[Tri, Tri], Tri] = {
    (_SAT, _SAT): _SAT,
    (_SAT, _UNSAT): _SAT,
    (_SAT, _UNK): _SAT,
    (_UNSAT, _SAT): _SAT,
    (_UNSAT, _UNSAT): _UNSAT,
    (_UNSAT, _UNK): _UNK,
    (_UNK, _SAT): _SAT,
    (_UNK, _UNSAT): _UNK,
    (_UNK, _UNK): _UNK,
}

#: Negation. ``unknown`` is a fixed point — the absence of an observation is not
#: evidence of anything, negated or otherwise (§4.5).
NOT_TABLE: Mapping[Tri, Tri] = {
    _SAT: _UNSAT,
    _UNSAT: _SAT,
    _UNK: _UNK,
}


def and_all(values: Iterable[Tri]) -> Tri:
    """``all_of`` over any number of children (§9.1).

    The identity is ``satisfied``: an empty conjunction imposes no requirement. The
    grammar forbids an empty ``all_of`` (``children`` has ``min_length=1``), but a
    capability with no ``requires`` at all reaches the same place, and vacuous truth is
    the answer that composes.
    """
    result = _SAT
    for value in values:
        result = AND_TABLE[result, value]
    return result


def or_any(values: Iterable[Tri]) -> Tri:
    """``any_of`` over any number of children (§9.1).

    The identity is ``unsatisfied``: an empty disjunction offers no way to succeed.
    """
    result = _UNSAT
    for value in values:
        result = OR_TABLE[result, value]
    return result


def negate(value: Tri) -> Tri:
    """``not`` (§9.1). Swaps the definite values; ``unknown`` maps to ``unknown``."""
    return NOT_TABLE[value]


def at_least(values: Iterable[Tri], n: int) -> Tri:
    """``at_least: {n, of: [...]}`` (§9.1).

    The middle case is the one worth stating in words: when the satisfied children alone
    do not reach ``n`` but the satisfied *plus* the unknown ones would, the answer is
    ``unknown`` — the requirement could go either way once the missing observations
    arrive. Counting unknowns as failures there would be exactly the collapse D8 removed.
    """
    satisfied = 0
    unknown = 0
    for value in values:
        match value:
            case Tri.SATISFIED:
                satisfied += 1
            case Tri.UNKNOWN:
                unknown += 1
            case Tri.UNSATISFIED:
                pass
    if satisfied >= n:
        return _SAT
    if satisfied + unknown < n:
        return _UNSAT
    return _UNK
