"""Partial native vector expansion preserves Python attempt order and projections."""

from itertools import product

import pytest

from tests.gear.test_native_stages import ScoringContext, StageContext, stage_search
from tracker.gear.objectives import ObjectiveDescriptor
from tracker.gear.vector_options import VectorOptions


def prepare(search):
    search.request = search.request.model_copy(
        update={
            "secondary_priority": "default",
            "objectives": (
                ObjectiveDescriptor(kind="defence_roll", styles=("stab", "magic")),
                ObjectiveDescriptor(kind="prayer_bonus"),
            ),
        }
    )
    search.native_context = ScoringContext(search)
    return StageContext(search.native_context, search), VectorOptions(search)


def oracle(search, options, states, choices, slot, prefix=None):
    result = []
    for index, (state, item) in enumerate(product(states, choices)):
        if prefix is not None and index >= prefix:
            break
        candidate = {**state, **({slot: item} if item is not None else {})}
        if (
            not search.compatible(candidate)
            or any(i not in search.eligible for i in candidate.values())
            or search.cost(set(candidate.values())) > search.request.budget_gp
        ):
            continue
        projection = options.projection(
            candidate, search.request.roles, require_supported=slot not in {"weapon", "shield"}
        )
        if projection is not None:
            result.append((candidate, projection))
    return result


@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize("chunk", [1, 3, 1024])
@pytest.mark.parametrize(
    "slot,states,choices",
    [
        ("weapon", [{}, {"head": 201}], [None, 2, 10, 100]),
        ("shield", [{"weapon": 2}, {"weapon": 100}, {"weapon": 10, "head": 201}], [None, 300]),
        (
            "head",
            [{"weapon": 2}, {"weapon": 100}, {"weapon": 10, "shield": 300}],
            [None, 201, 202, 203],
        ),
    ],
)
def test_partial_vector_batches_match_python(multiple, chunk, slot, states, choices):
    with stage_search(multiple=multiple) as search:
        roles = tuple(
            role.model_copy(update={"weight": 0.1 if index == 0 else 0.3})
            for index, role in enumerate(search.request.roles)
        )
        search.request = search.request.model_copy(update={"roles": roles})
        context, options = prepare(search)
        expansion = context.begin_projection(
            states=states, choices=choices, slot=slot, roles=tuple(role.id for role in roles)
        )
        actual = []
        while not expansion.done:
            actual.extend(expansion.advance_projection(chunk))
        assert expansion.consumed == len(states) * len(choices)
        assert actual == oracle(search, options, states, choices, slot)


def test_partial_projection_preserves_exhausted_attempt_prefix():
    with stage_search() as search:
        context, options = prepare(search)
        states, choices, slot = [{"weapon": 2}, {"weapon": 100}], [None, 201, 202, 203], "head"
        expansion = context.begin_projection(
            states=states, choices=choices, slot=slot, roles=("z",)
        )
        assert expansion.advance_projection(5) == oracle(
            search, options, states, choices, slot, prefix=5
        )
        assert expansion.consumed == 5
        assert not expansion.done


def test_partial_projection_rejects_final_slot():
    with stage_search() as search:
        context, _ = prepare(search)
        with pytest.raises(ValueError, match="partial"):
            context.begin_projection(
                states=[{"weapon": 2}], choices=[None], slot="ring", roles=("z",)
            )


@pytest.mark.parametrize(
    "head_quote,expected", [((999, 10), [{"weapon": 2, "head": 201}]), ((1000, 10), [])]
)
def test_partial_projection_preserves_market_alias_overwrite_and_budget(
    monkeypatch, head_quote, expected
):
    from tracker.gear.compact_acquisition import AcquisitionFacts

    with stage_search() as search:
        quotes = dict.fromkeys(search.facts)
        quotes.update({2: (999, 100), 201: head_quote})
        monkeypatch.setattr(
            AcquisitionFacts,
            "from_facts",
            classmethod(lambda cls, facts, request: cls(quotes, frozenset())),
        )
        search.request = search.request.model_copy(update={"budget_gp": 10})
        context, _ = prepare(search)
        expansion = context.begin_projection(
            states=[{"weapon": 2}], choices=[None, 201], slot="head", roles=("z",)
        )
        rows = expansion.advance_projection(2)
        assert expansion.consumed == 2
        assert [row[0] for row in rows] == expected


def test_partial_projection_checks_eligible_items_before_scoring():
    with stage_search() as search:
        search.eligible = {key: item for key, item in search.eligible.items() if key != 201}
        context, _ = prepare(search)
        expansion = context.begin_projection(
            states=[{"weapon": 2}], choices=[201, 202], slot="head", roles=("z",)
        )
        assert [row[0] for row in expansion.advance_projection(2)] == [{"weapon": 2, "head": 202}]
