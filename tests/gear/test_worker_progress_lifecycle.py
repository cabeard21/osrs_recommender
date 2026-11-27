"""Progress follows the current slot owner until the worker returns its result."""

import multiprocessing

from tracker.gear.progress import SlotReader, SlotWriter, WorkerSlots, for_lane, lane_label


def test_successor_displaces_previous_owner_before_its_future_arrives():
    slots = WorkerSlots(multiprocessing.get_context("spawn"), 1)
    reader = SlotReader(slots)
    first = SlotWriter(slots, 0, 3)
    assert [e["phase"] for e in reader.events()] == ["lane_started", "preparation"]

    # The optimizer reports finish before materializing the result in the worker.
    first({"phase": "lane_complete", "lane_status": "complete"})
    assert reader.events() == []
    first.returning()
    successor = SlotWriter(slots, 0, 6)
    successor({"phase": "candidate_ranking", "stage_done": 0, "stage_total": 1000})

    events = reader.events()
    assert [(e["phase"], e["lane"]) for e in events] == [
        ("lane_collecting", 3),
        ("lane_started", 6),
        ("candidate_ranking", 6),
    ]
    assert events[1]["started_at"] == successor.started_at
    assert events[1]["worker_slot"] == 0
    assert reader.events() == []


def test_torn_slot_read_keeps_previous_owner_and_collection_is_emitted_once():
    slots = WorkerSlots(multiprocessing.get_context("spawn"), 1)
    reader = SlotReader(slots)
    writer = SlotWriter(slots, 0, 2)
    reader.events()
    slots._values[0] += 1
    assert reader.events() == []
    slots._values[0] += 1

    writer.returning()
    assert reader.events() == [{"phase": "lane_collecting", "lane": 2}]
    SlotWriter(slots, 0, 3)
    assert [(e["phase"], e["lane"]) for e in reader.events()] == [
        ("lane_started", 3),
        ("preparation", 3),
    ]


def test_spawned_workers_record_pickup_through_receipt_without_exposing_it_in_results():
    from tests.gear.test_parallel import inputs
    from tracker.gear.parallel import AutoProcessPool

    snapshot, request, catalog, content, prices, now = inputs()
    updates = []
    pool = AutoProcessPool(2)
    try:
        pool.start(content, catalog)
        results = pool.run(
            snapshot, request, catalog, content, prices, now, progress=updates.append
        )
    finally:
        pool.close()
    completed = [
        event
        for update in updates
        for event in update["events"]
        if event["phase"] == "lane_complete"
    ]
    assert sorted(event["lane"] for event in completed) == [0, 1, 2]
    assert all(event["started_at"] > 0 and event["duration_seconds"] > 0 for event in completed)
    assert all("_progress_pickup" not in row for _, row in results)


def test_serial_lane_forwards_stages_and_defers_optimizer_finish():
    events = []
    progress = for_lane(events.append, 2, include_finish=False)
    assert progress is not None
    progress({"phase": "frontiers", "stage_done": 1000, "stage_total": 1000})
    progress({"phase": "lane_complete", "lane_status": "complete"})
    assert events == [{"phase": "frontiers", "stage_done": 1000, "stage_total": 1000, "lane": 2}]


def test_full_handoff_labels_distinguish_the_potion_profiles():
    discipline = "role-1=ranged/role-2=magic"
    potions = ("divine_magic", "divine_ranging")
    two = lane_label(discipline, potions)
    three = lane_label(discipline, (*potions, "divine_super_combat"))
    assert two.endswith("Divine magic, Divine ranging")
    assert three.endswith("Divine magic, Divine ranging, Divine super combat")
