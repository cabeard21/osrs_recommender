"""Replay the 40-search planner handoff with a fake six-worker FIFO clock."""

from heapq import heappop, heappush

import pytest

from tracker.gear.progress_tracker import RunProgress, TimingModel

# Rounded worker search durations from the handoff, in submission order.
GROUPS = (
    (("melee", "melee"), (14.57, 14.80)),
    (("melee", "ranged"), (12.65, 12.07, 11.70, 12.20)),
    (("melee", "magic"), (11.18, 12.02, 11.63, 11.93)),
    (("ranged", "melee"), (157.65, 155.35, 168.99, 170.47)),
    (("ranged", "ranged"), (153.53, 151.50, 162.65, 171.66)),
    (
        ("ranged", "magic"),
        (306.98, 307.43, 286.42, 342.77, 313.33, 307.25, 290.19, 354.18),
    ),
    (("magic", "melee"), (243.20, 249.55, 240.74, 265.45)),
    (
        ("magic", "ranged"),
        (183.16, 189.00, 211.26, 219.79, 193.33, 235.44, 242.14, 225.97),
    ),
    (("magic", "magic"), (268.59, 299.33)),
)
WORKERS = 6
CHECKPOINT = 1031
MERGE_SECONDS = 9.98
POTIONS = {
    "magic": "divine_magic",
    "melee": "divine_super_combat",
    "ranged": "divine_ranging",
}


def lane_profiles(styles, count):
    # Both mixed Ranged/Magic groups in the handoff include super combat.
    potions = sorted({POTIONS[style] for style in styles})
    if count == 8:
        potions.append(POTIONS["melee"])
    return [
        (styles, tuple(potion for bit, potion in enumerate(potions) if mask & (1 << bit)))
        for mask in range(count)
    ]


def replay(model, *, duration_scale=1.0, checkpoint=CHECKPOINT):
    """Only deliver completed duration samples when the fake worker finishes."""
    lane_keys = [
        key for styles, durations in GROUPS for key in lane_profiles(styles, len(durations))
    ]
    times = [duration * duration_scale for _, durations in GROUPS for duration in durations]
    now = 0.0
    tracker = RunProgress(
        has_frontiers=True,
        parallelism=WORKERS,
        timing_key="handoff-replay",
        model=model,
        clock=lambda: now,
    )
    tracker.handle(
        {
            "phase": "preparation",
            "plan": {
                "lanes": ["/".join(styles) for styles, _ in lane_keys],
                "lane_keys": lane_keys,
            },
        }
    )
    events = []
    workers = [0.0] * WORKERS
    for lane, duration in enumerate(times):
        start = heappop(workers)
        end = start + duration
        heappush(workers, end)
        events.extend(
            (
                (start, 1, lane, {"phase": "lane_started", "lane": lane}),
                (
                    end,
                    0,
                    lane,
                    {
                        "phase": "lane_complete",
                        "lane": lane,
                        "lane_status": "complete",
                        "duration_seconds": duration,
                    },
                ),
            )
        )
    end = max(workers)
    snapshot = None
    for at, _, _, event in sorted(events):
        if snapshot is None and at > checkpoint:
            now = checkpoint
            snapshot = tracker.snapshot()
            assert tracker.snapshot() == snapshot
        now = at
        tracker.handle(event)
    tracker.handle({"phase": "merge"})
    now = end + MERGE_SECONDS * duration_scale
    tracker.handle({"phase": "complete"})
    tracker.finish(succeeded=True)
    return snapshot, now - checkpoint


@pytest.mark.parametrize("warm", [False, True])
def test_handoff_progress_at_the_screenshot_checkpoint(warm):
    model = TimingModel()
    if warm:
        replay(model, duration_scale=1.05)

    snapshot, remaining = replay(model)
    assert snapshot is not None
    assert snapshot["total"] == 40
    assert snapshot["lane_counts"] == {
        "complete": 33,
        "running": 6,
        "pending": 1,
        "collecting": 0,
    }
    assert [lane["lane_id"] for lane in snapshot["lanes"]] == list(range(33, 39))
    assert all(lane["stage_fraction"] is None for lane in snapshot["lanes"])
    assert remaining == pytest.approx(335.35, abs=0.1)
    if warm:
        assert snapshot["eta_seconds"] == pytest.approx(remaining, rel=0.20)
        assert "search_eta_range_seconds" not in snapshot
    else:
        assert snapshot["eta_seconds"] is None
        low, high = snapshot["search_eta_range_seconds"]
        assert 0 < low <= remaining - MERGE_SECONDS <= high
        assert high < remaining * 2


def test_cold_replay_waits_past_short_opening_wave_then_keeps_a_search_range():
    early, _ = replay(TimingModel(), checkpoint=60)
    assert early is not None and early["completed"] == 10
    assert "search_eta_range_seconds" not in early

    for checkpoint in (540, 780, 900, 1150, 1300):
        snapshot, remaining = replay(TimingModel(), checkpoint=checkpoint)
        assert snapshot is not None and snapshot["eta_seconds"] is None
        low, high = snapshot["search_eta_range_seconds"]
        assert low <= remaining - MERGE_SECONDS <= high
