"""Option capture resumes at the same ordinal across native and Python screening."""

import sys
from types import SimpleNamespace
from weakref import ref

import pytest

from tests.gear.test_optimizer import NOW
from tracker.gear.optimizer import OptimizationRequest, RoleConfig
from tracker.gear.vector_option_product import PackedOptionsCache, remaining_product
from tracker.gear.vector_options import OptionVariant
from tracker.gear.vector_search import VectorSearch


@pytest.fixture
def capture_engine(monkeypatch):
    engines = []

    def create(*, cost=False, feasible=True, native=True):
        if native:
            pytest.importorskip("tracker.gear.native._frontier")
        roles = tuple(RoleConfig(id=rid, style="slash") for rid in ("a", "b"))
        request = OptimizationRequest(
            roles=roles,
            max_swaps=1,
            objectives=[{"kind": "gp_per_damage" if cost else "prayer_bonus"}],
        )
        progress = []
        engine = VectorSearch(
            SimpleNamespace(
                request=request,
                native_context=object() if native else None,
                running_prices={},
                running_at=NOW,
                items={},
                facts={},
                cancelled=None,
                reporter=SimpleNamespace(fraction=progress.append),
            )
        )
        engines.append(engine)
        variants = {
            role.id: tuple(OptionVariant(i, None, {}, (10.0, 0.0)) for i in options)
            for role, options in zip(roles, ((0, 1), (2, 3, 4)), strict=True)
        }
        monkeypatch.setattr("tracker.gear.vector_search.loadout_problems", lambda *_: ())
        engine.options.variants = lambda _, role: variants[role.id]
        engine.options.numeric_feasibility = lambda *_, **__: (
            SimpleNamespace(maximum_actions=1) if feasible else None
        )
        reported = []
        engine.options.solution = lambda _, opts: tuple(o.configured for o in opts)
        engine.offer = reported.append
        return engine, {"a": {}, "b": {}}, reported, progress

    yield create
    for engine in engines:
        for archive in engine.archives.values():
            archive.close()


def test_joint_capture_charges_only_consumed_rows_and_resumes_uncharged(capture_engine):
    engine, gear, reports, progress = capture_engine()
    engine.nodes = 1023
    engine.phase_limit = 1026
    engine.capture(gear)
    assert engine.native_option_screened == engine.option_attempts == engine.complete_attempts == 3
    assert engine.nodes == 1026
    assert progress == [0.65 * 1024 / engine.limit]
    engine.capture(gear, charge=False)
    engine.capture(gear, charge=False)
    assert engine.nodes == 1026
    assert engine.native_option_screened == engine.native_option_attempts == 6
    assert reports == [(0, 2), (0, 3), (0, 4), (1, 2), (1, 3), (1, 4)]


def test_joint_index_loss_resumes_without_duplicate_admission(capture_engine):
    engine, gear, reports, _ = capture_engine()

    def offer(selection):
        reports.append(selection)
        engine.archives[1]._native_index = None

    engine.offer = offer
    engine.capture(gear)
    assert engine.native_option_screened == 1
    assert engine.nodes == engine.native_option_attempts == engine.native_option_reports == 6
    assert reports == [(0, 2), (0, 3), (0, 4), (1, 2), (1, 3), (1, 4)]


def test_unpriced_baseline_tie_survives_and_updated_floor_screens_rest(capture_engine):
    engine, gear, reports, _ = capture_engine(cost=True)
    engine.baselines = {0: None, 1: {"score": 10.0}, None: {"score": 20.0}}

    def offer(selection):
        reports.append(selection)
        engine.baselines[1] = {"score": 11.0}

    engine.offer = offer
    engine.capture(gear)
    assert engine.native_option_screened == 6
    assert reports == [(0, 2)]


def test_nan_cap_baseline_cannot_rule_out_unpriced_option(capture_engine):
    engine, gear, reports, _ = capture_engine(cost=True)
    engine.baselines = {0: None, 1: {"score": 20.0}, None: {"score": float("nan")}}
    engine.capture(gear)
    assert engine.native_option_reports == len(reports) == 6


def test_cancellation_at_phase_boundary_keeps_prefix(capture_engine):
    engine, gear, reports, _ = capture_engine()
    engine.phase_limit = 2
    engine.search.cancelled = lambda: len(reports) == 2
    with pytest.raises(ValueError, match="optimization_cancelled"):
        engine.capture(gear)
    assert engine.seen.execute("SELECT cursor,complete FROM seen_assignments").fetchone() == (2, 0)
    assert engine.nodes == engine.native_option_screened == 2


def test_infeasible_assignment_never_screens_options(capture_engine):
    engine, gear, reports, _ = capture_engine(feasible=False)
    engine.capture(gear)
    assert engine.native_option_screened == engine.option_attempts == engine.nodes == 0
    assert reports == []


def test_cancelled_capture_remembers_consumed_prefix(capture_engine):
    engine, gear, reports, _ = capture_engine()
    engine.search.cancelled = lambda: len(reports) == 2
    with pytest.raises(ValueError, match="optimization_cancelled"):
        engine.capture(gear)
    assert engine.nodes == engine.native_option_screened == 2
    engine.search.cancelled = None
    engine.capture(gear)
    assert engine.nodes == engine.native_option_screened == 6
    assert reports == [(0, 2), (0, 3), (0, 4), (1, 2), (1, 3), (1, 4)]


def test_python_resume_seeks_directly_to_large_ordinal(capture_engine):
    options = (range(100_000),) * 4
    ordinal = 100_000**4 - 2
    assert list(remaining_product(options, ordinal)) == [
        (99_999, 99_999, 99_999, 99_998),
        (99_999,) * 4,
    ]
    assert not list(remaining_product(options, ordinal + 2))
    assert not list(remaining_product((range(2), ()), 2))
    engine, gear, _, _ = capture_engine(native=False)
    engine._remember_assignment(engine.identity(gear), ordinal, complete=False)
    stored = engine.seen.execute("SELECT cursor FROM seen_assignments").fetchone()[0]
    assert int(stored) == ordinal


@pytest.mark.parametrize("native", (False, True), ids=("python-only", "older-native-extension"))
def test_capture_without_option_extension_uses_reference(capture_engine, monkeypatch, native):
    engine, gear, reports, _ = capture_engine(native=native)
    if native:
        frontier = pytest.importorskip("tracker.gear.native._frontier")
        monkeypatch.delattr(frontier, "OptionProduct", raising=False)
    else:
        monkeypatch.setitem(sys.modules, "tracker.gear.native._frontier", None)
    engine.capture(gear)
    assert engine.native_option_screened == 0
    assert engine.option_attempts == 6
    assert reports == [(0, 2), (0, 3), (0, 4), (1, 2), (1, 3), (1, 4)]


def test_reference_after_nonfinite_row_charges_native_prefix_once(capture_engine):
    engine, gear, reports, _ = capture_engine()
    original = engine.options.variants
    valid, invalid, last = original({}, engine.search.request.roles[1])
    alternatives = (valid, OptionVariant(invalid.configured, None, {}, (float("nan"), 0.0)), last)
    engine.options.variants = lambda slots, role: (
        alternatives if role.id == "b" else original(slots, role)
    )
    # Only the first combination is safely dominated before the scanner sees NaN.
    for cap in (1, None):
        engine.archives[cap].native_candidate_index.insert("dominator", (20.0, 20.0))
    engine.capture(gear)
    assert engine.native_option_screened == 1
    assert engine.option_attempts == engine.nodes == 6
    assert reports[0] == (0, 3)
    assert len(reports) == len(set(reports))


def test_cancellation_at_reference_boundary_preserves_exact_cursor(capture_engine):
    engine, gear, reports, _ = capture_engine()

    def offer(selection):
        reports.append(selection)
        engine.archives[1]._native_index = None

    engine.offer = offer
    # The native scan offers ordinal 0. The next poll allows ordinal 1;
    # cancellation then stops immediately before ordinal 2.
    polls = iter((False, False, True))
    engine.search.cancelled = lambda: next(polls)
    with pytest.raises(ValueError, match="optimization_cancelled"):
        engine.capture(gear)
    assert engine.seen.execute("SELECT cursor,complete FROM seen_assignments").fetchone() == (2, 0)
    engine.search.cancelled = None
    engine.capture(gear)
    assert engine.nodes == engine.option_attempts == 6
    assert engine.native_option_screened == 1
    assert reports == [(0, 2), (0, 3), (0, 4), (1, 2), (1, 3), (1, 4)]


def test_role_cache_reuses_exact_tuple_and_releases_it_on_eviction(monkeypatch):
    frontier = pytest.importorskip("tracker.gear.native._frontier")
    cache = PackedOptionsCache()
    roles = (RoleConfig(id="a", style="slash"),)
    builds = []
    original = frontier.PackedRole

    def track(variants, *args):
        builds.append(id(variants))
        return original(variants, *args)

    monkeypatch.setattr(frontier, "PackedRole", track)

    class Marker:
        pass

    marker = Marker()
    held = ref(marker)
    variants = (OptionVariant(marker, None, {}, (0.0, 1.0)),)
    cache.product((variants,), roles, 2, None, None)
    cache.product((variants,), roles, 2, None, None)
    assert builds == [id(variants)]
    del variants, marker
    assert held() is not None
    for i in range(512):
        cache.product(((OptionVariant(i, None, {}, (0.0, 1.0)),),), roles, 2, None, None)
    assert held() is None
