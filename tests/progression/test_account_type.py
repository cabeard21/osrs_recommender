"""``account_type`` and ``members`` — the two leaves that *remove* options (Step 9).

An ironman cannot buy a Voidwaker at any price, so an ``acquisition`` candidate is not
merely expensive for them, it is impossible. Before this, no field anywhere in the schema
could say so and the app recommended purchases to every account alike.

The design decision worth testing, and the one this file mostly exists for, is that
``None`` means **nobody has said** — not "main". A default would assert the very fact whose
absence is the bug, and §4.5's rule (absence of evidence is not evidence) is what forbids
it. The consequence cuts both ways and both directions are asserted below: an unanswered
account still sees purchases, and an ironman who answers once stops seeing them.
"""

from __future__ import annotations

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import (
    AccountTypeLeaf,
    MembersLeaf,
    RequirementSyntaxError,
)
from tracker.content.requirements import parse as parse_requirement
from tracker.content.validate import load_and_validate
from tracker.domain.types import AccountType, PlayerState, Tri
from tracker.progression.evaluate import Evaluator

#: The gate every acquisition in the corpus now carries.
BUYABLE = {"any_of": [{"account_type": "main"}, {"account_type": "group"}]}


def _evaluator(requirement, state, content):
    """Adapt :class:`Evaluator` to the positional ``RequirementEvaluator`` protocol."""
    return Evaluator(state, content).evaluate(requirement)


@pytest.fixture(scope="module")
def corpus() -> Content:
    return load_and_validate()


def _evaluate(corpus: Content, requirement: object, **state: object) -> Tri:
    return (
        Evaluator(PlayerState(player_id=1, **state), corpus)
        .evaluate(parse_requirement(requirement))
        .value
    )


# ---------------------------------------------------------------------------
# The grammar (§10.2, §10.8)
# ---------------------------------------------------------------------------


def test_both_leaves_parse_from_their_yaml_spelling() -> None:
    assert parse_requirement({"account_type": "ironman"}) == AccountTypeLeaf(account_type="ironman")
    assert parse_requirement({"members": True}) == MembersLeaf(members=True)


def test_members_refuses_an_integer_that_yaml_would_have_coerced() -> None:
    """``members: 1`` must be a syntax error, not a silent truthy read.

    YAML reads ``yes`` as ``True`` but ``1`` as an integer. Accepting the latter would make
    ``members: 0`` a requirement that the account *not* be a member — a real requirement
    spelled by accident.
    """
    with pytest.raises(RequirementSyntaxError, match="true or false"):
        parse_requirement({"members": 1})


def test_a_round_trip_through_yaml_preserves_both_leaves() -> None:
    for spelling in ({"account_type": "group"}, {"members": False}):
        assert parse_requirement(spelling).to_yaml() == spelling


# ---------------------------------------------------------------------------
# Evaluation (§9.1, §4.5)
# ---------------------------------------------------------------------------


def test_an_unanswered_account_is_unknown_and_not_main(corpus: Content) -> None:
    """The whole point. ``None`` is a third state, not a synonym for the default."""
    assert _evaluate(corpus, BUYABLE) is Tri.UNKNOWN
    assert _evaluate(corpus, {"members": True}) is Tri.UNKNOWN


def test_a_matching_account_type_is_satisfied(corpus: Content) -> None:
    assert _evaluate(corpus, BUYABLE, account_type=AccountType.MAIN) is Tri.SATISFIED
    assert _evaluate(corpus, BUYABLE, account_type=AccountType.GROUP) is Tri.SATISFIED


def test_an_ironman_is_unsatisfied_not_unknown(corpus: Content) -> None:
    """Answering is what turns the gate from a question into a block."""
    for account_type in (AccountType.IRONMAN, AccountType.HARDCORE, AccountType.ULTIMATE):
        assert _evaluate(corpus, BUYABLE, account_type=account_type) is Tri.UNSATISFIED


def test_membership_evaluates_both_ways(corpus: Content) -> None:
    assert _evaluate(corpus, {"members": True}, members=True) is Tri.SATISFIED
    assert _evaluate(corpus, {"members": True}, members=False) is Tri.UNSATISFIED
    assert _evaluate(corpus, {"members": False}, members=False) is Tri.SATISFIED


def test_an_unknown_account_type_is_reported_as_an_unknown_leaf(corpus: Content) -> None:
    """It must reach the unknowns list, not vanish — §15 has to be able to ask.

    And it must *not* be reported as a blocker: "we have not asked" and "you cannot do
    this" are the distinction §4.5 exists to keep, all the way to the page.
    """
    result = Evaluator(PlayerState(player_id=1), corpus).evaluate(parse_requirement(BUYABLE))

    assert result.value is Tri.UNKNOWN
    assert {leaf.leaf_type for leaf in result.unknowns} == {"account_type"}
    assert result.blockers == ()


# ---------------------------------------------------------------------------
# What it does to the shipped corpus
# ---------------------------------------------------------------------------


def test_every_acquisition_in_the_corpus_gates_on_account_type(corpus: Content) -> None:
    """A purchase the Grand Exchange cannot serve is impossible, not merely expensive."""
    from tracker.content.requirements import iter_leaves
    from tracker.domain.types import CandidateKind

    acquisitions = [
        candidate
        for candidate in corpus.candidates.values()
        if candidate.kind is CandidateKind.ACQUISITION
    ]

    assert acquisitions, "the corpus has no acquisitions to check"
    for candidate in acquisitions:
        assert candidate.requires is not None, candidate.id
        gated = {
            leaf.account_type
            for leaf in iter_leaves(candidate.requires)
            if isinstance(leaf, AccountTypeLeaf)
        }
        assert gated == {"main", "group"}, candidate.id


def test_an_unanswered_account_still_sees_purchases(corpus: Content) -> None:
    """An unknown gate does not block (§10.6, G3), and that is deliberate.

    A main who never opened Settings must not silently lose every acquisition because the
    app is being careful. The cost of not guessing is borne as a question, not as a
    disappearance.
    """
    from tracker.domain.candidates import blocked

    state = PlayerState(player_id=1)
    assert blocked(corpus.candidates["buy_voidwaker"], state, corpus, _evaluator) is False


def test_an_ironman_stops_seeing_purchases(corpus: Content) -> None:
    """The bug this step exists to fix, asserted on the shipped corpus."""
    from tracker.domain.candidates import blocked

    state = PlayerState(player_id=1, account_type=AccountType.IRONMAN)
    assert blocked(corpus.candidates["buy_voidwaker"], state, corpus, _evaluator) is True
    assert blocked(corpus.candidates["buy_high_risk_gear"], state, corpus, _evaluator) is True
