"""Reduced transition reuse retains directional and inventory context."""

from dataclasses import replace

from tests.gear.test_transition_cache import search_for
from tools.gear_retention_oracle import tiny_cases
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.execution_profile import execution_context
from tracker.gear.transitions import plan_transition


def test_reduced_cache_reuses_static_gear_and_outer_hits():
    case = next(row for row in tiny_cases() if row.name == "hands")
    with execution_context("combined", case.request, factored_evaluation=True, compact_states=True):
        search = search_for(case)
        for constant in (400, 401):
            source = (("head", constant), ("weapon", 100))
            goal = (("head", constant), ("shield", 30), ("weapon", 101))
            carried = frozenset({constant, 100, 101, 30})
            expected = plan_transition(
                dict(source), dict(goal), case.catalog.items, carried=carried
            )
            assert search._transition(source, goal, carried, 28) == expected
            assert search._transition(source, goal, carried, 28) == expected
        assert search._transition.cache_info().hits == 2
        assert search._transition_reduced.cache_info().misses == 1
        assert search._transition_reduced.cache_info().hits == 1
        assert search._transition_reduced.cache_info().maxsize == 1024
        search._transition.cache_clear()
        assert search._transition_reduced.cache_info().currsize == 0


def test_reduced_cache_contexts_and_generic_fallback():
    case = next(row for row in tiny_cases() if row.name == "hands")
    sources = ({"head": 100, "weapon": 100}, {"shield": 30, "weapon": 101}, {"custom": 30})
    destinations = ({"head": 100, "weapon": 101}, {"weapon": 100}, {})
    changed = replace(
        case,
        catalog=EquipmentCatalog(
            {
                **case.catalog.items,
                100: case.catalog.items[100].model_copy(update={"two_handed": False}),
            }
        ),
    )
    for owner in (case, changed):
        expected = [
            plan_transition(a, b, owner.catalog.items, carried=c, capacity=n)
            for a, b in zip(sources, destinations, strict=True)
            for c in (frozenset({100, 101, 30}), frozenset({100, 101, 30, 999}))
            for n in (0, 1, 2, 28)
        ]
        with execution_context(
            "combined", owner.request, factored_evaluation=True, compact_states=True
        ):
            search = search_for(owner)
            actual = [
                search._transition(tuple(sorted(a.items())), tuple(sorted(b.items())), c, n)
                for a, b in zip(sources, destinations, strict=True)
                for c in (frozenset({100, 101, 30}), frozenset({100, 101, 30, 999}))
                for n in (0, 1, 2, 28)
            ]
            assert actual == expected


def test_shared_transition_reports_are_copied_for_public_solutions():
    from tests.gear.test_factored_multi import multi_case
    from tests.gear.test_prayer_search_efficiency import search as make_search
    from tracker.gear.variant_reporting import materialize

    args = multi_case()
    assignments = [
        {"a": {"weapon": 1, "head": head}, "b": {"weapon": 2, "head": head}} for head in (10, 20)
    ]
    expected = make_search(args).solution(assignments[1], None)
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        search = make_search(args)
        first = search.solution(assignments[0], None)
        assert first is not None
        first = materialize(first)
        first["transitions"][0]["actions"].clear()
        second = search.solution(assignments[1], None)
        assert second is not None
        assert materialize(second) == expected
        assert search._transition_reduced.cache_info().hits >= 2


def test_transition_caches_release_without_cyclic_gc():
    import gc
    import weakref

    case = next(row for row in tiny_cases() if row.name == "hands")
    with execution_context("combined", case.request, factored_evaluation=True, compact_states=True):
        search = search_for(case)
        outer = weakref.ref(search._transition)
        inner = weakref.ref(search._transition_reduced)
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            del search
            assert outer() is None
            assert inner() is None
        finally:
            if was_enabled:
                gc.enable()

