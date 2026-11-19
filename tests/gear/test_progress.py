"""Optimizer progress: in-stage reporting, worker slots and the service-side tracker."""

import multiprocessing

import pytest

from tests.gear.test_auto_disciplines import context
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.optimizer import RoleConfig, optimize
from tracker.gear.progress import (
    STAGE_SCALE,
    SlotReader,
    SlotWriter,
    StageReporter,
    WorkerSlots,
    for_lane,
    lane_label,
)
from tracker.gear.progress_tracker import RunProgress, TimingModel
from tracker.gear.service import GearService


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def single(args=None):
    snapshot, request, catalog, content, prices, now = args or context()
    role = request.roles[0].model_copy(update={"allowed_disciplines": None})
    return snapshot, request.model_copy(update={"roles": (role,)}), catalog, content, prices, now


# Reporter -------------------------------------------------------------------------


def test_reporter_is_throttled_monotonic_and_segmented():
    clock, events = Clock(), []
    reporter = StageReporter(events.append, clock=clock, interval=0.1)
    reporter.stage("gear_search")
    reporter.segment(1, 2)  # Throttled: same instant as the stage event.
    clock.now = 0.2
    reporter.fraction(0.5)
    clock.now = 0.4
    reporter.fraction(0.25)  # Backwards inside the stage is ignored.
    assert [e["stage_done"] for e in events] == [0, 750]
    assert all(e["stage_total"] == STAGE_SCALE for e in events)
    reporter.stage("frontiers")
    reporter.slots(0.9)  # Slot loops are not frontier progress.
    assert events[-1] == {"phase": "frontiers", "stage_done": 0, "stage_total": STAGE_SCALE}


def test_null_reporter_and_lane_helpers():
    StageReporter().fraction(0.5)
    assert for_lane(None, 1) is None
    events = []
    for_lane(events.append, 2)({"phase": "merge"})
    assert events == [{"phase": "merge", "lane": 2}]
    assert lane_label("magic", ("super_strength",)) == "Magic · Super strength"
    assert lane_label(None, ()) == "No potions"
    assert lane_label(None) == "Search"


def test_optimize_reports_every_stage_with_increasing_counters():
    events = []
    optimize(*single(), progress=events.append)
    phases = [e["phase"] for e in events]
    for stage in ("preparation", "candidate_ranking", "gear_search", "refinement", "frontiers"):
        assert stage in phases
    assert phases[-1] == "lane_complete"
    searched = [e["stage_done"] for e in events if e["phase"] == "gear_search"]
    assert searched == sorted(searched)


def test_progress_does_not_change_results():
    from tests.gear.test_auto_disciplines import without_timings

    args = single()
    assert without_timings(optimize(*args, progress=lambda e: None)) == without_timings(
        optimize(*args)
    )


def test_frontier_progress_reserves_work_for_cleanup_and_finalists(monkeypatch):
    import tracker.gear.finalist_refinement as finalists
    import tracker.gear.frontier as frontier
    import tracker.gear.refinement as ammunition
    from tests.gear.test_finalist_refinement import scenario

    search, seed = scenario()
    events, observed = [], []
    reporter = StageReporter(events.append, interval=0)
    reporter.stage("frontiers")
    # Exercise the second outer segment, as used for running-cost trade-offs.
    reporter.segment(1, 2)
    search.reporter = reporter
    monkeypatch.setattr(type(search), "loadouts", lambda *args: [])
    monkeypatch.setattr(type(search), "joint_loadouts", lambda *args: [])
    monkeypatch.setattr(frontier, "_shared_assignments", lambda *args: [])

    def variants(local, row, tick):
        # Exhaust the expansion allowance before the separately budgeted cleanup.
        while tick():
            pass
        return []

    def clean(local, row, *args):
        observed.append(events[-1]["stage_done"])
        return row

    def refine(local, row, *, progress=None):
        observed.append(events[-1]["stage_done"])
        if progress:
            progress(0.5)
            observed.append(events[-1]["stage_done"])
        return row, {"evaluated_assignments": 1, "improvements": 0, "work_budget_exhausted": False}

    monkeypatch.setattr(frontier, "_combat_variants", variants)
    monkeypatch.setattr(ammunition, "refine_ammunition", clean)
    monkeypatch.setattr(finalists, "refine_finalist", refine)
    frontier.explore(search, [seed] * 9, seed, False)
    assert len(observed) == 3
    assert 500 < observed[0] < observed[1] < observed[2] < 1000
    assert observed[0] < 900  # Expansions cannot claim nearly all remaining work.
    assert events[-1]["stage_done"] == 1000


@pytest.mark.parametrize("limit", [0, 4, 2048])
def test_finalist_progress_is_monotonic_and_preserves_results(limit):
    from tests.gear.test_finalist_refinement import scenario
    from tracker.gear.finalist_refinement import refine_finalist

    search, seed = scenario()
    fractions = []
    expected = refine_finalist(search, seed, limit=limit)
    actual = refine_finalist(search, seed, limit=limit, progress=fractions.append)
    assert actual == expected
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1


def test_finalist_reports_work_within_a_long_refinement(monkeypatch):
    import tracker.gear.finalist_refinement as finalists
    from tests.gear.test_finalist_refinement import scenario

    search, seed = scenario()
    fractions = []
    role = search.request.roles[0]
    monkeypatch.setattr(finalists, "_trials", lambda *_: ((role, {"weapon": i}) for i in range(65)))
    monkeypatch.setattr(finalists, "_trial", lambda *_: None)
    _, work = finalists.refine_finalist(search, seed, limit=64, progress=fractions.append)
    assert work["evaluated_assignments"] == 64
    assert work["work_budget_exhausted"]
    assert fractions == [1 / 64, 0.5, 1.0, 1.0]


def test_progress_preserves_secondary_frontier_and_skips_unselected_cost():
    from tests.gear.test_auto_disciplines import without_timings

    snapshot, request, *rest = single(context("ranged"))
    role = request.roles[0].model_copy(update={"style": "ranged"})
    request = request.model_copy(update={"roles": (role,), "secondary_priority": "prayer_bonus"})
    events = []
    measured = optimize(snapshot, request, *rest, progress=events.append)
    plain = optimize(snapshot, request, *rest)
    assert measured["secondary_frontiers"] and not measured["running_cost_frontiers"]
    assert without_timings(measured) == without_timings(plain)


# Worker slots ---------------------------------------------------------------------


def test_worker_slots_round_trip_lane_events_and_skip_completion():
    slots = WorkerSlots(multiprocessing.get_context("spawn"), 2)
    events = []
    reader = SlotReader(slots, events.append)
    writer = SlotWriter(slots, 1, lane=4)
    writer({"phase": "gear_search", "stage_done": 300, "stage_total": 1000})
    reader.poll()
    reader.poll()  # Unchanged sequence is not re-emitted.
    assert events == [{"phase": "gear_search", "lane": 4, "stage_done": 300, "stage_total": 1000}]
    writer({"phase": "lane_complete", "lane_status": "complete"})
    writer({"phase": "unknown"})
    reader.poll()
    assert len(events) == 1
    slots.clear()
    assert slots.read() == []


def test_spawned_workers_report_lane_stages_through_shared_memory():
    from tests.gear.test_parallel import inputs
    from tracker.gear.parallel import AutoProcessPool

    snapshot, request, catalog, content, prices, now = inputs()
    events = []
    pool = AutoProcessPool(2)
    try:
        pool.start(content, catalog)
        pool.run(snapshot, request, catalog, content, prices, now, progress=events.append)
    finally:
        pool.close()
    staged = {e["lane"] for e in events if "stage_total" in e}
    completed = sorted(e["lane"] for e in events if e.get("lane_status") == "complete")
    assert staged and staged <= {0, 1, 2}
    assert completed == [0, 1, 2]


# Tracker --------------------------------------------------------------------------


def test_single_lane_progress_is_monotonic_and_completes():
    clock = Clock()
    run = RunProgress(has_frontiers=False, clock=clock)
    assert run.snapshot()["fraction"] == 0
    clock.now = 1
    run.handle({"phase": "gear_search", "stage_done": 500, "stage_total": 1000})
    halfway = run.snapshot()
    assert 0.3 < halfway["fraction"] < 0.7
    assert halfway["phase"] == "gear_search"
    assert halfway["label"] == "Searching gear combinations"
    assert [s["id"] for s in halfway["stages"]] == [
        "preparation",
        "candidate_ranking",
        "gear_search",
        "refinement",
    ]
    assert [s["status"] for s in halfway["stages"]] == ["complete", "complete", "active", "pending"]
    run.handle({"phase": "candidate_ranking", "stage_done": 0, "stage_total": 1000})
    assert run.snapshot()["fraction"] >= halfway["fraction"]
    clock.now = 2
    run.finish(succeeded=True)
    done = run.snapshot()
    assert (done["phase"], done["fraction"], done["eta_seconds"]) == ("complete", 1.0, 0.0)
    assert done["elapsed_seconds"] == 2
    assert "lanes" not in done


def test_plan_lanes_report_rows_merge_and_counts():
    run = RunProgress(has_frontiers=True, clock=Clock())
    run.handle({"phase": "preparation", "plan": {"lanes": ["Melee", "Ranged", "Magic"]}})
    run.handle({"phase": "frontiers", "lane": 1, "stage_done": 0, "stage_total": 1000})
    run.handle({"phase": "potion_search", "lane": 0, "lane_status": "complete"})
    run.handle({"phase": "gear_search", "lane": 9})  # Out of range lanes are ignored.
    snapshot = run.snapshot()
    assert (snapshot["completed"], snapshot["total"]) == (1, 3)
    assert [lane["status"] for lane in snapshot["lanes"]] == ["complete", "running", "pending"]
    assert snapshot["lanes"][1]["stage"] == "frontiers"
    assert snapshot["stages"][-1]["id"] == "merge"
    run.handle({"phase": "merge"})
    assert run.snapshot()["phase"] == "merge"


def test_many_parallel_lanes_report_running_rows_and_in_run_eta():
    """Auto x potion runs: 16 searches on 3 workers, as seen in the desktop app."""
    clock = Clock()
    run = RunProgress(has_frontiers=True, parallelism=3, clock=clock)
    run.handle({"phase": "preparation", "plan": {"lanes": [f"Profile {i}" for i in range(16)]}})
    for lane in range(3):  # Each search: 2s gear search, then 8s of frontiers.
        run.handle({"phase": "gear_search", "lane": lane})
    clock.now = 2
    for lane in range(3):
        run.handle({"phase": "frontiers", "lane": lane})
    clock.now = 10
    for lane in range(3):
        run.handle({"phase": "lane_complete", "lane": lane, "lane_status": "complete"})
        run.handle({"phase": "gear_search", "lane": lane + 3})
    snapshot = run.snapshot()
    assert snapshot["label"] == "Running 16 searches"
    assert snapshot["lane_counts"] == {"complete": 3, "running": 3, "pending": 10}
    assert [row["label"] for row in snapshot["lanes"]] == ["Profile 3", "Profile 4", "Profile 5"]
    assert snapshot["lanes"][0]["stage_label"] == "Searching gear combinations"
    # Thirteen 10s searches left on three workers, measured from this run.
    assert 40 < snapshot["eta_seconds"] < 47
    clock.now = 11  # Mid gear search, the bar advances with the measured durations.
    assert run.snapshot()["fraction"] > snapshot["fraction"]


def test_untagged_profile_counts_remain_supported():
    run = RunProgress(has_frontiers=False, clock=Clock())
    run.handle({"phase": "potion_search", "completed_profiles": 3, "total_profiles": 9})
    run.handle({"phase": "frontiers"})
    snapshot = run.snapshot()
    assert (snapshot["completed"], snapshot["total"]) == (3, 9)
    assert [lane["label"] for lane in snapshot["lanes"]][3:5] == ["Profile 4", "Profile 5"]


def test_failure_freezes_progress_without_learning():
    model = TimingModel()
    run = RunProgress(has_frontiers=False, timing_key="k", model=model, clock=Clock())
    run.finish(succeeded=False)
    run.handle({"phase": "gear_search", "stage_done": 1000, "stage_total": 1000})
    assert run.snapshot()["phase"] == "failed"
    assert run.snapshot()["eta_seconds"] is None
    assert model.expected("k") is None


def test_learned_timings_drive_weights_interpolation_and_eta():
    model, clock = TimingModel(), Clock()
    first = RunProgress(has_frontiers=False, timing_key="shape", model=model, clock=clock)
    clock.now = 1
    first.handle({"phase": "preparation"})
    clock.now = 2
    first.handle({"phase": "gear_search"})
    clock.now = 10
    first.finish(succeeded=True)
    learned = model.expected("shape")
    assert learned["setup"] == 1 and learned["gear_search"] == 8
    assert learned["preparation"] == 1 and learned["candidate_ranking"] == 0

    clock.now = 100
    second = RunProgress(has_frontiers=False, timing_key="shape", model=model, clock=clock)
    assert second.snapshot()["eta_seconds"] == 10
    second.handle({"phase": "gear_search"})
    clock.now = 102  # One second of setup, then 1/8 of the learned gear search.
    snapshot = second.snapshot()
    assert 0.2 < snapshot["fraction"] < 0.5
    assert snapshot["stages"][2]["fraction"] > 0
    assert 0 < snapshot["eta_seconds"] < 10


def test_real_frontier_counters_take_precedence_over_shorter_learned_timings():
    model, clock = TimingModel(), Clock()
    model.record("shape", {"gear_search": 1.0, "frontiers": 1.0})
    run = RunProgress(has_frontiers=True, timing_key="shape", model=model, clock=clock)
    run.handle({"phase": "frontiers", "stage_done": 650, "stage_total": 1000})
    before = run.snapshot()
    clock.now = 100
    run.handle({"phase": "frontiers"})  # A counterless update cannot erase real counters.
    assert run.snapshot()["fraction"] == before["fraction"]
    run.handle({"phase": "frontiers", "stage_done": 800, "stage_total": 1000})
    after = run.snapshot()
    assert after["fraction"] > before["fraction"]
    assert after["stages"][-1]["fraction"] == 0.8
    assert after["stages"][-1]["status"] == "active"


def test_counterless_stage_interpolates_after_a_counted_stage():
    model, clock = TimingModel(), Clock()
    model.record("shape", {"gear_search": 1.0, "frontiers": 10.0})
    run = RunProgress(has_frontiers=True, timing_key="shape", model=model, clock=clock)
    run.handle({"phase": "gear_search", "stage_done": 500, "stage_total": 1000})
    run.handle({"phase": "frontiers"})
    clock.now = 5
    assert run.snapshot()["stages"][-1]["fraction"] == 0.5


def test_timing_model_blends_and_bounds_shapes():
    model = TimingModel()
    model.record("a", {"gear_search": 10.0})
    model.record("a", {"gear_search": 0.0})
    assert model.expected("a") == {"gear_search": 6.0}
    for index in range(70):
        model.record(index, {"gear_search": 1.0})
    assert model.expected("a") is None


# Service --------------------------------------------------------------------------


def test_service_reports_stages_for_plain_runs():
    snapshot, request, catalog, content, prices, now = single()
    service = GearService(content)
    service._equipment = EquipmentCatalog(catalog.items)
    service.optimize(snapshot, request, price_records=prices, now=now, progress_identity="one")
    progress = service.optimization_progress("one")
    assert progress["phase"] == "complete" and progress["fraction"] == 1
    assert all(stage["status"] == "complete" for stage in progress["stages"])
    assert service.optimization_progress("two") is None
    service.optimize(snapshot, request, price_records=prices, now=now, progress_identity="two")
    assert service.optimization_progress("one") is None


def test_service_reports_auto_lanes_and_multi_role_runs():
    snapshot, request, catalog, content, prices, now = context()
    service = GearService(content)
    service._equipment = EquipmentCatalog(catalog.items)
    service.optimize(snapshot, request, price_records=prices, now=now, progress_identity="auto")
    progress = service.optimization_progress("auto")
    assert [lane["label"] for lane in progress["lanes"]] == ["Melee", "Ranged", "Magic"]
    assert progress["completed"] == progress["total"] == 3
    roles = (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="ranged"))
    multi = request.model_copy(update={"roles": roles, "max_swaps": 1})
    service.optimize(snapshot, multi, price_records=prices, now=now, progress_identity="multi")
    assert service.optimization_progress("multi")["fraction"] == 1
