"""Frontier variants retain exact results while postponing rich reports."""

import json

import pytest

from tests.gear.test_prayer_search_efficiency import scenario, search
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.frontier import _combat_variants
from tracker.gear.optimizer import _solution_key, optimize
from tracker.gear.prayers import PrayerPolicy
from tracker.gear.variant_reporting import active, lazy_variants, materialize


def inputs(style="ranged", priority="balanced_defence", joint=False):
    args = list(
        scenario(
            style,
            PrayerPolicy(
                mode="optimize", allowed_ids=("steel_skin", "eagle_eye", "ultimate_strength")
            ),
        )
    )
    role = args[1].roles[0]
    if style == "magic":
        role = role.model_copy(
            update={
                "combat_options": role.combat_options.model_copy(update={"spells": ("powered:3",)})
            }
        )
    roles = (role, role.model_copy(update={"id": "b", "weight": 2})) if joint else (role,)
    args[1] = args[1].model_copy(update={"roles": roles, "secondary_priority": priority})
    return args


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["balanced_defence", "accuracy", "ranged_defence_roll"])
@pytest.mark.parametrize("joint", [False, True])
def test_complete_frontier_variant_parity(style, priority, joint):
    args = inputs(style, priority, joint)
    expected = optimize(*args, _complete_frontiers=True, _running_frontier=True)
    with lazy_variants():
        actual = optimize(*args, _complete_frontiers=True, _running_frontier=True)
    assert without_observations(actual) == without_observations(expected)
    # Public reports must contain only ordinary serializable values.
    json.dumps(actual)


def test_variant_waits_until_exact_tie_or_publication(monkeypatch):
    args = inputs()
    instance = search(args)
    seed = instance.solution({"a": {"weapon": 2}}, None)
    assert seed is not None
    calls = []
    original = instance.evaluate

    def evaluate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(instance, "evaluate", evaluate)
    with lazy_variants():
        variants = _combat_variants(instance, seed, lambda: True)
        row = next(variants)
        assert not calls
        key = _solution_key(row)
        assert not calls
        # Comparing a different primary score never demands rich tie data.
        assert (key[0] - 1, *key[1:]) < key
        assert not calls
        full = materialize(row)
        assert calls == [1]
        assert materialize(row) is full
        assert json.dumps(full["loadouts"], sort_keys=True) == key[-1]
        variants.close()


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["balanced_defence", "ranged_defence_roll"])
def test_compact_variant_report_boundary_avoids_nested_solution(monkeypatch, style, priority):
    import tracker.gear.compact_solutions as solutions
    from tracker.gear.execution_profile import execution_context
    from tracker.gear.variant_reporting import CompactVariant

    args = inputs(style, priority, joint=True)
    weapon = {"slash": 1, "ranged": 2, "magic": 3}[style]
    assignment = {"a": {"weapon": weapon}, "b": {"weapon": weapon}}
    reference = search(args)
    reference.running_prices, reference.running_at = args[4:]
    expected_seed = reference.solution(assignment, None)
    expected = list(_combat_variants(reference, expected_seed, lambda: True))
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        instance.running_prices, instance.running_at = args[4:]
        seed = instance.solution(assignment, None)
        assert isinstance(seed, solutions.CompactSolution)
        materialize(seed)

        def unexpected(*args, **kwargs):
            pytest.fail("Explicit rich report boundary constructed a nested compact solution")

        monkeypatch.setattr(solutions, "compact_solution", unexpected)
        with lazy_variants():
            rows = list(_combat_variants(instance, seed, lambda: True))
        assert rows and all(isinstance(row, CompactVariant) for row in rows)
        for row, full in zip(rows, expected, strict=True):
            # The exact tie is also an explicit rich-report boundary.
            assert _solution_key(row)[-1] == json.dumps(full["loadouts"], sort_keys=True)
            assert materialize(row) == full
        assert instance.compact_states
        assert not getattr(instance, "_compact_solution_bypass", False)


def test_compact_variant_report_boundary_honors_cancellation():
    from tracker.gear.execution_profile import execution_context

    args = inputs()
    with execution_context("combined", args[1], factored_evaluation=True, compact_states=True):
        instance = search(args)
        seed = instance.solution({"a": {"weapon": 2}}, None)
        materialize(seed)
        with lazy_variants():
            variants = _combat_variants(instance, seed, lambda: True)
            row = next(variants)
            variants.close()
        instance.cancelled = lambda: True
        with pytest.raises(ValueError, match="optimization_cancelled"):
            materialize(row)
        instance.cancelled = None
        assert materialize(row)["loadouts"]


def test_full_variants_preserve_order_and_reduce_reporting(monkeypatch):
    args = inputs()
    role = (
        args[1]
        .roles[0]
        .model_copy(update={"prayers": PrayerPolicy(mode="optimize", allowed_ids=("sharp_eye",))})
    )
    args[1] = args[1].model_copy(update={"roles": (role,)})
    instance = search(args)
    seed = instance.solution({"a": {"weapon": 2}}, None)
    assert seed is not None
    expected = list(_combat_variants(instance, seed, lambda: True))
    calls = []
    original = instance.evaluate

    def evaluate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(instance, "evaluate", evaluate)
    with lazy_variants():
        actual = list(_combat_variants(instance, seed, lambda: True))
        assert len(calls) < len(expected)
        assert [materialize(row) for row in actual] == expected


def test_nested_context_and_exception_cleanup():
    assert not active()
    with lazy_variants():
        with pytest.raises(RuntimeError), lazy_variants():
            raise RuntimeError("stop")
        assert active()
    assert not active()


def test_cancellation_during_variant_generation_recovers(monkeypatch):
    from tracker.gear import frontier

    cancelled = False
    original = frontier.compact_variant

    def cancel_after_score(*args, **kwargs):
        nonlocal cancelled
        result = original(*args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(frontier, "compact_variant", cancel_after_score)
    with pytest.raises(ValueError, match="optimization_cancelled"), lazy_variants():
        optimize(*inputs(), cancelled=lambda: cancelled, _complete_frontiers=True)
    assert cancelled
    assert not active()


def test_cancellation_before_materialization_does_not_cache_partial_report():
    args = inputs()
    instance = search(args)
    cancelled = False
    instance.cancelled = lambda: cancelled
    seed = instance.solution({"a": {"weapon": 2}}, None)
    assert seed is not None
    with pytest.raises(ValueError, match="optimization_cancelled"), lazy_variants():
        variants = _combat_variants(instance, seed, lambda: True)
        row = next(variants)
        variants.close()
        cancelled = True
        materialize(row)
    assert not active()
    cancelled = False
    full = materialize(row)
    assert full["loadouts"]["a"]["performance"]["supported"]
    assert row == full and full == row
    assert row != {}


def test_new_deferred_refinement_results_are_hydrated_before_hashing(monkeypatch):
    from tracker.gear import finalist_refinement
    from tracker.gear.variant_reporting import CompactVariant

    args = inputs("magic")
    reference = optimize(*args, _complete_frontiers=True, _running_frontier=True)
    original = finalist_refinement.refine_finalist
    produced = []

    def defer_new_candidate(*args, **kwargs):
        row, work = original(*args, **kwargs)
        full = materialize(row)
        loadouts = {
            rid: {
                **loadout,
                "running_cost": {
                    key: value
                    for key, value in loadout["running_cost"].items()
                    if key not in {"resources", "charging_alternatives", "reasons"}
                },
            }
            for rid, loadout in full["loadouts"].items()
        }
        produced.append(1)
        return CompactVariant({**full, "loadouts": loadouts}, lambda: full), work

    monkeypatch.setattr(finalist_refinement, "refine_finalist", defer_new_candidate)
    actual = optimize(*args, _complete_frontiers=True, _running_frontier=True)
    assert produced
    # This includes published frontier IDs, which hash the complete loadout reports.
    assert without_observations(actual) == without_observations(reference)


def test_compact_equality_reuses_descriptors_and_rejects_scalar_mismatches(monkeypatch):
    from tracker.gear import variant_reporting

    args = inputs()
    instance = search(args)
    full = instance.solution({"a": {"weapon": 2}}, None)
    assert full is not None

    def unexpected():
        pytest.fail("Clearly unequal variants must not expand rich reports")

    first = variant_reporting.CompactVariant(full, unexpected)
    slower = variant_reporting.CompactVariant({**full, "score": full["score"] - 1}, unexpected)
    different = {
        **full,
        "loadouts": {
            "a": {**full["loadouts"]["a"], "selected_prayer_ids": ["sharp_eye"]},
        },
    }
    other = variant_reporting.CompactVariant(different, unexpected)

    def rekey(*args):
        pytest.fail("Already prepared variant descriptors must be reused")

    monkeypatch.setattr(variant_reporting, "candidate_identity", rekey)
    assert first == first
    assert first != slower
    assert first != other


def test_equal_numeric_descriptors_still_compare_complete_reports():
    from tracker.gear.variant_reporting import CompactVariant

    instance = search(inputs())
    full = instance.solution({"a": {"weapon": 2}}, None)
    assert full is not None
    calls = []

    def report(value):
        calls.append(1)
        return value

    first = CompactVariant(full, lambda: report(full))
    changed = {**full, "extra_report_fact": "different"}
    other = CompactVariant(full, lambda: report(changed))
    assert first != other
    assert calls == [1, 1]


def _without_cyclic_gc():
    import gc
    from contextlib import contextmanager

    @contextmanager
    def disabled():
        enabled = gc.isenabled()
        gc.disable()
        try:
            yield
        finally:
            if enabled:
                gc.enable()

    return disabled()


def _lifetime_values():
    return {
        "score": 1.0,
        "loadouts": {
            "a": {
                "equipment": {"weapon": 1},
                "combat_option": None,
                "selected_prayer_ids": [],
            }
        },
    }


def test_discarded_variant_is_reclaimed_without_cyclic_gc():
    import weakref

    from tracker.gear.variant_reporting import CompactVariant

    values = _lifetime_values()
    with _without_cyclic_gc():
        row = CompactVariant(values, lambda: values)
        reference = weakref.ref(row)
        del row
        assert reference() is None


def test_materialized_variant_releases_captured_search_and_keeps_report():
    import weakref

    from tracker.gear.variant_reporting import CompactVariant

    class SearchSentinel:
        pass

    values = _lifetime_values()
    search = SearchSentinel()
    reference = weakref.ref(search)
    row = CompactVariant(values, lambda captured=search: {**values, "captured": bool(captured)})
    del search
    with _without_cyclic_gc():
        assert reference() is not None
        full = row.materialize()
        assert reference() is None
        assert full == {**values, "captured": True}
        assert row.materialize() is full


def test_materialization_failure_retains_factory_until_successful_retry():
    import weakref

    from tracker.gear.variant_reporting import CompactVariant

    class SearchSentinel:
        pass

    values = _lifetime_values()
    search = SearchSentinel()
    reference = weakref.ref(search)
    calls = []

    def report(captured=search):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("optimization_cancelled")
        return {**values, "captured": bool(captured)}

    row = CompactVariant(values, report)
    del search, report
    with _without_cyclic_gc():
        with pytest.raises(ValueError, match="optimization_cancelled"):
            row.materialize()
        assert reference() is not None
        assert row.materialize()["captured"] is True
        assert reference() is None
        assert calls == [1, 1]


def test_resolved_tie_releases_candidate_while_exact_text_remains_reusable():
    import weakref

    from tracker.gear.variant_reporting import CompactVariant, loadout_tie

    values = _lifetime_values()
    expected = json.dumps(values["loadouts"], sort_keys=True)
    with _without_cyclic_gc():
        row = CompactVariant(values, lambda: values)
        reference = weakref.ref(row)
        tie = loadout_tie(row)
        del row
        assert reference() is not None
        assert tie == expected
        assert reference() is None
        assert tie == expected and expected == tie
        assert not tie < expected
        assert not expected < tie


def test_tie_serialization_failure_keeps_callback_until_successful_retry():
    import weakref

    from tracker.gear.variant_reporting import _ReportTie

    class SearchSentinel:
        pass

    search = SearchSentinel()
    reference = weakref.ref(search)
    calls = []

    def report(captured=search):
        calls.append(1)
        return {"loadouts": object() if len(calls) == 1 else {"captured": bool(captured)}}

    tie = _ReportTie(report)
    del search, report
    with _without_cyclic_gc():
        with pytest.raises(TypeError):
            tie.text()
        assert reference() is not None
        expected = '{"captured": true}'
        assert tie.text() == expected
        assert reference() is None
        assert tie.text() == expected
        assert calls == [1, 1]


@pytest.mark.parametrize("changed", ["score", "secondary_value"])
def test_plain_unequal_variant_reads_only_relevant_score_prefix(changed):
    from tracker.gear.variant_reporting import CompactVariant

    values = {**_lifetime_values(), "secondary_value": 2.0}
    reads = []
    allowed = ["score"] if changed == "score" else ["score", "secondary_value"]

    class ObservedDict(dict):
        def get(self, key, default=None):
            reads.append(key)
            assert key in allowed, "Unequal scores must not read irrelevant scalar fields"
            return super().get(key, default)

    def unexpected():
        pytest.fail("Unequal numeric scores must not construct rich reports")

    row = CompactVariant(values, unexpected)
    other = ObservedDict({**values, changed: values[changed] + 1})
    assert row != other
    assert reads == allowed


@pytest.mark.parametrize("nan_field", ["score", "secondary_value"])
def test_plain_variant_prefix_retains_same_object_nan_equality(nan_field):
    from tracker.gear.variant_reporting import CompactVariant

    values = {**_lifetime_values(), "secondary_value": 2.0, nan_field: float("nan")}
    row = CompactVariant(values, lambda: values)
    other = dict(values)
    # Dict and tuple equality both accept identical element objects before ==.
    assert row == other and other == row
    assert row != {**other, nan_field: float("nan")}


def test_plain_variant_prefix_keeps_missing_key_distinct_from_explicit_none():
    from tracker.gear.variant_reporting import CompactVariant

    values = {**_lifetime_values(), "secondary_value": None}
    row = CompactVariant(values, lambda: values)
    other = {key: value for key, value in values.items() if key != "secondary_value"}
    assert row != other and other != row
