import pytest

from tests.gear.test_prayer_search_efficiency import search
from tests.gear.test_variant_reporting import inputs
from tracker.gear.compact_solutions import compact_solution
from tracker.gear.variant_reporting import materialize


def test_solution_parity_and_interning():
    instance = search(inputs())
    assignment = {"a": {"weapon": 2}}
    expected = instance.solution(assignment, None)
    actual = compact_solution(instance, assignment, None)
    assert actual is compact_solution(instance, assignment, 0)
    assert materialize(actual) == materialize(expected)


def test_report_releases_factory():
    instance = search(inputs())
    actual = compact_solution(instance, {"a": {"weapon": 2}}, None)
    assert actual._report is not None
    materialize(actual)
    assert actual._report is None


def test_materialization_releases_execution_owner():
    import gc
    import weakref

    instance = search(inputs())
    reference = weakref.ref(instance)
    actual = compact_solution(instance, {"a": {"weapon": 2}}, None)
    materialize(actual)
    del instance
    gc.collect()
    assert reference() is None


def test_intern_pool_is_bounded_and_override_sensitive(monkeypatch):
    import tracker.gear.compact_solutions as module

    monkeypatch.setattr(module, "MAX_SOLUTIONS", 2)
    instance = search(inputs())
    assignment = {"a": {"weapon": 2}}
    first = compact_solution(instance, assignment, None)
    key = ("a", (("weapon", 2),))
    retained = [first]
    for marker in range(3):
        instance.option_cache[key] = {"__prayer_ids": [], "marker": marker}
        candidate = compact_solution(instance, assignment, None)
        assert candidate is not first
        retained.append(candidate)
    assert len(instance._compact_solution_pool[1]) == 2


def test_numeric_override_identity_preserves_json_distinctions():
    from tracker.gear.compact_solutions import _freeze

    assert _freeze({"dps": 0}) != _freeze({"dps": 0.0})
    assert _freeze({"dps": 0.0}) != _freeze({"dps": -0.0})


def test_constraints_record_is_immutable():
    from dataclasses import FrozenInstanceError

    import pytest

    instance = search(inputs())
    actual = compact_solution(instance, {"a": {"weapon": 2}}, None)
    with pytest.raises(FrozenInstanceError):
        actual.record.score = 0


def test_scope_cleans_pool_on_error_without_cyclic_gc():
    import pytest

    from tracker.gear.compact_solutions import solution_scope

    instance = search(inputs())
    with pytest.raises(ValueError), solution_scope():
        row = compact_solution(instance, {"a": {"weapon": 2}}, None)
        assert row is not None
        assert instance._compact_solution_pool[1]
        raise ValueError("cancelled")
    assert not hasattr(instance, "_compact_solution_pool")


def test_rich_purchase_report_waits_for_publication(monkeypatch):
    import tracker.gear.optimizer as module

    instance = search(inputs())
    import tracker.gear.evaluation as evaluation

    original = evaluation.purchases
    calls = []

    def purchases(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(evaluation, "purchases", purchases)
    # Isolate reporting from the legacy constraint-cost helper in this direct test.
    monkeypatch.setattr(instance, "cost", lambda ids: 0)
    actual = compact_solution(instance, {"a": {"weapon": 2}}, None)
    assert not calls
    assert module._solution_key(actual) is module._solution_key(actual)
    materialize(actual)
    assert calls == [1]


def test_unmaterialized_scope_teardown_does_not_require_cyclic_gc():
    import gc
    import weakref

    from tracker.gear.compact_solutions import solution_scope

    enabled = gc.isenabled()
    gc.disable()
    try:
        with solution_scope():
            instance = search(inputs())
            reference = weakref.ref(instance)
            compact_solution(instance, {"a": {"weapon": 2}}, None)
            del instance
        assert reference() is None
    finally:
        if enabled:
            gc.enable()


def test_override_json_identity_is_order_independent_and_type_exact():
    from tracker.gear.compact_solutions import _override_identity

    assert _override_identity({"a": 2, "b": [1]}) == _override_identity({"b": [1], "a": 2})
    assert _override_identity({"dps": 0}) != _override_identity({"dps": 0.0})
    assert _override_identity({"dps": -0.0}) != _override_identity({"dps": 0.0})
    assert _override_identity({"supported": False}) != _override_identity({"supported": 0})


@pytest.mark.parametrize("style,weapon", [("slash", 1), ("ranged", 2), ("magic", 3)])
@pytest.mark.parametrize("costs", [False, True])
def test_record_expansion_matches_direct_legacy_report_exactly(style, weapon, costs):
    import json

    from tracker.gear.execution_profile import execution_context

    args = inputs(style, priority="ranged_defence_roll")
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        reference = search(args)
        candidate = search(args)
        reference._compact_solution_bypass = True
        if costs:
            reference.running_prices = candidate.running_prices = args[4]
            reference.running_at = candidate.running_at = args[5]
        assignment = {"a": {"weapon": weapon}}
        expected = reference.solution(assignment, None)
        actual = compact_solution(candidate, assignment, None)
        assert expected is not None and actual is not None
        assert json.dumps(materialize(actual), sort_keys=True) == json.dumps(
            materialize(expected), sort_keys=True
        )


def test_cap_rejection_stops_transitions_and_does_not_poison_unrestricted(monkeypatch):
    from tests.gear.test_factored_multi import multi_case
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        assignment = {"a": {"weapon": 1}, "b": {"weapon": 2}}
        original = instance._transition
        calls = []

        def transition(*args):
            calls.append(args)
            return original(*args)

        monkeypatch.setattr(instance, "_transition", transition)
        assert compact_solution(instance, assignment, 0) is None
        assert len(calls) == 1
        assert not instance._compact_solution_pool[1]
        unrestricted = compact_solution(instance, assignment, None)
        assert unrestricted is not None
        assert unrestricted["maximum_actions"] > 0
        assert compact_solution(instance, assignment, 0) is None
        assert (
            compact_solution(instance, assignment, unrestricted["maximum_actions"]) is unrestricted
        )


def test_budget_rejection_remains_infeasible_across_caps(monkeypatch):
    from tests.gear.test_factored_multi import multi_case
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        assignment = {"a": {"weapon": 1}, "b": {"weapon": 2}}
        monkeypatch.setattr(instance, "cost", lambda ids: instance.request.budget_gp + 1)
        assert compact_solution(instance, assignment, 0) is None
        assert compact_solution(instance, assignment, None) is None
        assert compact_solution(instance, assignment, 3) is None
        assert all(row is None for row in instance._compact_solution_pool[1].values())


def test_role_report_pool_bounds_and_retries():
    from tracker.gear.compact_solutions import _RoleReportPool

    pool = _RoleReportPool(2)
    first = {"supported": True, "dps": 1.0}
    assert pool.report(("a",), lambda: first) is first
    assert pool.report(("a",), lambda: pytest.fail("hit recomputed")) is first
    pool.report(("b",), lambda: {"dps": 2.0})
    pool.report(("c",), lambda: {"dps": 3.0})
    assert len(pool.rows) == 2
    replacement = {"supported": True, "dps": 1.0}
    assert pool.report(("a",), lambda: replacement) is replacement

    def fail():
        raise ValueError("cancelled")

    with pytest.raises(ValueError):
        pool.report(("failure",), fail)
    assert ("failure",) not in pool.rows


def test_full_role_reports_shared_across_distinct_joint_solutions(monkeypatch):
    from tests.gear.test_factored_multi import multi_case
    from tracker.gear.execution_profile import execution_context
    from tracker.gear.optimizer import _Search

    args = multi_case()
    calls = []
    original = _Search.performance

    def performance(self, equipment, role):
        if getattr(self, "_compact_solution_bypass", False):
            calls.append((role.id, tuple(equipment.items())))
        return original(self, equipment, role)

    monkeypatch.setattr(_Search, "performance", performance)
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        a = {"weapon": 1, "head": 10}
        first = compact_solution(instance, {"a": a, "b": {"weapon": 2, "head": 20}}, None)
        second = compact_solution(instance, {"a": a, "b": {"weapon": 2}}, None)
        first_full, second_full = materialize(first), materialize(second)
        assert sum(role == "a" for role, _ in calls) == 1
        assert (
            first_full["loadouts"]["a"]["performance"]
            is second_full["loadouts"]["a"]["performance"]
        )
    assert not hasattr(instance, "_compact_role_reports")


def test_role_pool_owner_isolation_and_order_keys():
    from copy import copy

    from tests.gear.test_factored_multi import multi_case
    from tracker.gear.compact_solutions import _role_report_pool
    from tracker.gear.execution_profile import execution_context

    args = multi_case()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        first = compact_solution(
            instance, {"a": {"weapon": 1, "head": 10}, "b": {"weapon": 2}}, None
        )
        materialize(first)
        pool = _role_report_pool(instance)
        assert len(pool.rows) == 2
        second = compact_solution(
            instance, {"a": {"head": 10, "weapon": 1}, "b": {"weapon": 2}}, None
        )
        materialize(second)
        assert len(pool.rows) == 3
        copied = copy(instance)
        assert _role_report_pool(copied) is not pool


def test_role_pool_preserves_exact_seeded_override_reports():
    import json
    from copy import copy

    from tracker.gear.execution_profile import execution_context

    args = inputs()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        assignment = {"a": {"weapon": 2}}
        first = materialize(compact_solution(instance, assignment, None))
        key = ("a", (("weapon", 2),))
        override = {**first["loadouts"]["a"]["performance"], "limitations": ["seed override"]}
        instance.performance_cache[key] = override
        instance.option_cache[key] = {
            **first["loadouts"]["a"]["combat_option"],
            "__prayer_ids": ["steel_skin"],
        }
        reference = copy(instance)
        reference._compact_solution_bypass = True
        expected = reference.solution(assignment, None)
        actual = materialize(compact_solution(instance, assignment, None))
        assert actual["loadouts"]["a"]["performance"]["limitations"] == ["seed override"]
        assert actual["loadouts"]["a"]["selected_prayer_ids"] == ["steel_skin"]
        assert json.dumps(actual, sort_keys=True) == json.dumps(
            materialize(expected), sort_keys=True
        )


def test_rejected_solution_and_owner_release_without_cyclic_gc():
    import gc
    import weakref

    enabled = gc.isenabled()
    gc.disable()
    try:
        instance = search(inputs())
        row = compact_solution(instance, {"a": {"weapon": 2}}, None)
        row_ref, owner_ref = weakref.ref(row), weakref.ref(instance)
        del row
        assert row_ref() is None
        assert not instance._compact_solution_pool[1]
        del instance
        assert owner_ref() is None
    finally:
        if enabled:
            gc.enable()


def test_weak_pool_dead_entry_misses_and_live_archive_reuses():
    from tracker.gear.compact_solutions import _SolutionPool

    instance = search(inputs())
    assignment = {"a": {"weapon": 2}}
    row = compact_solution(instance, assignment, None)
    pool = _SolutionPool(2)
    pool.add(("a",), row)
    assert pool.lookup(("a",)) == (True, row)
    archive = [row]
    del row
    assert pool.lookup(("a",))[1] is archive[0]
    assert compact_solution(instance, assignment, 0) is archive[0]
    archive.clear()
    assert pool.lookup(("a",)) == (False, None)


def test_weak_pool_negative_entries_are_bounded_and_callbacks_are_weak():
    import weakref

    from tracker.gear.compact_solutions import _SolutionPool

    pool = _SolutionPool(2)
    pool.add(("one",), None)
    pool.add(("two",), None)
    pool.add(("three",), None)
    assert len(pool) == 2
    assert pool.lookup(("one",)) == (False, None)
    assert pool.lookup(("two",)) == (True, None)
    instance = search(inputs())
    row = compact_solution(instance, {"a": {"weapon": 2}}, None)
    pool.add(("row",), row)
    reference = weakref.ref(pool)
    del pool
    assert reference() is None


def test_stale_weak_callback_does_not_remove_replacement():
    from tracker.gear.compact_solutions import _SolutionPool

    instance = search(inputs())
    first = compact_solution(instance, {"a": {"weapon": 2}}, None)
    second = compact_solution(search(inputs()), {"a": {"weapon": 2}}, None)
    assert first is not None and second is not None
    pool = _SolutionPool(1)
    pool.add(("key",), first)
    stale = pool.rows[("key",)]
    pool.add(("other",), second)
    pool.add(("key",), second)
    stale.__callback__(stale)
    assert pool.lookup(("key",))[1] is second


def test_dead_weak_reference_without_callback_is_a_miss():
    import weakref

    from tracker.gear.compact_solutions import _SolutionPool

    instance = search(inputs())
    row = compact_solution(instance, {"a": {"weapon": 2}}, None)
    pool = _SolutionPool(1)
    pool.rows[("dead",)] = weakref.ref(row)
    del row
    assert pool.lookup(("dead",)) == (False, None)
    assert not pool


def test_rank_survives_row_and_releases_owner_after_tie_resolution():
    import weakref

    from tracker.gear.optimizer import _solution_key

    instance = search(inputs())
    row = compact_solution(instance, {"a": {"weapon": 2}}, None)
    rank = _solution_key(row)
    row_ref, owner_ref = weakref.ref(row), weakref.ref(instance)
    del row, instance
    assert row_ref() is None
    assert owner_ref() is not None
    assert rank[-1].text()
    assert owner_ref() is None
