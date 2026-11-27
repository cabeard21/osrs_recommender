"""Service-side aggregation of optimizer progress into a weighted stage plan and ETA.

One :class:`RunProgress` exists per optimization attempt. It folds lane-tagged search
events into an overall fraction that never decreases, a per-stage checklist, per-lane
rows and a remaining-time estimate. Stage durations come from, in order of preference:
lanes already finished in this run, :class:`TimingModel` history for the request
shape, then static defaults.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from heapq import heapify, heapreplace
from math import ceil
from statistics import median
from threading import Lock
from time import monotonic
from typing import Any, TypeVar

from tracker.gear.progress import LANE_STAGES, STAGE_LABELS

# Relative lane-stage costs used until timings are measured. Trade-off frontiers
# dominate real runs (metric lane, diverse equipment and combat variants).
DEFAULT_STAGE_WEIGHTS = {
    "preparation": 0.03,
    "candidate_ranking": 0.07,
    "gear_search": 0.25,
    "refinement": 0.05,
    "frontiers": 0.60,
}
DEFAULT_SETUP_SHARE = 0.03
DEFAULT_MERGE_SHARE = 0.03
# Time interpolation never claims a stage is finished without the search saying so.
INTERPOLATION_CEILING = 0.9
RUNNING_CEILING = 0.99
MIN_LIVE_FRACTION = 0.05
MIN_LIVE_SECONDS = 1.5
ETA_SMOOTHING = 0.35
PROVISIONAL_LOW_FACTOR = 0.75
PROVISIONAL_HIGH_FACTOR = 1.4
PROVISIONAL_OVERRUN_SHARE = 0.25
MAX_REPORTED_LANES = 12
MAX_LABEL_LENGTH = 512
TIMING_ALPHA = 0.4
MAX_TIMING_SHAPES = 64
_TimingKey = TypeVar("_TimingKey", bound=Hashable)


class TimingModel:
    """Exponentially weighted per-shape stage durations; bounded, thread-safe, in memory."""

    def __init__(self) -> None:
        self._rows: dict[Hashable, dict[Hashable, float]] = {}
        self._lock = Lock()

    def expected(self, key: Hashable) -> dict[Hashable, float] | None:
        with self._lock:
            row = self._rows.get(key)
            return dict(row) if row is not None else None

    def record(self, key: Hashable, durations: Mapping[_TimingKey, float]) -> None:
        with self._lock:
            previous = self._rows.get(key)
            if previous is None:
                if len(self._rows) >= MAX_TIMING_SHAPES:
                    self._rows.pop(next(iter(self._rows)))
                self._rows[key] = dict(durations.items())
                return
            self._rows[key] = {
                name: TIMING_ALPHA * value + (1 - TIMING_ALPHA) * previous.get(name, value)
                for name, value in durations.items()
            }


@dataclass
class _Lane:
    label: str
    stage: int = -1
    reported: float = 0.0
    stage_started: float = 0.0
    complete: bool = False
    # True once the search itself reported a stage, so durations are measured.
    observed: bool = False
    counted: bool = False
    durations: dict[str, float] = field(default_factory=dict)
    key: tuple[tuple[str, ...], tuple[str, ...]] | None = None
    started: float | None = None
    worker_slot: int | None = None
    collecting: bool = False
    duration: float | None = None

    def advance(
        self, stage: int, fraction: float, now: float, stages: Sequence[str], *, counted: bool
    ) -> None:
        if self.complete or stage < self.stage:
            return
        self.observed = True
        if stage > self.stage:
            self._close(stage, now, stages)
            self.stage, self.reported, self.stage_started = stage, 0.0, now
            self.counted = False
        self.counted = self.counted or counted
        self.reported = max(self.reported, min(1.0, fraction))

    def finish(self, now: float, stages: Sequence[str]) -> None:
        if not self.complete:
            self._close(len(stages), now, stages)
            self.stage, self.complete = len(stages), True

    def _close(self, until: int, now: float, stages: Sequence[str]) -> None:
        if self.stage >= 0:
            self.durations[stages[self.stage]] = now - self.stage_started
        for skipped in range(self.stage + 1, min(until, len(stages))):
            self.durations.setdefault(stages[skipped], 0.0)


@dataclass(frozen=True)
class _Weights:
    stages: dict[str, float]
    stage_seconds: dict[str, float]
    lane_seconds: float
    setup: float
    merge: float
    setup_seconds: float
    merge_seconds: float
    # Durations were measured on lanes finished during this very run.
    in_run: bool


class RunProgress:
    """Thread-safe progress model for one optimization attempt."""

    def __init__(
        self,
        *,
        has_frontiers: bool,
        parallelism: int = 1,
        timing_key: Hashable = None,
        schedule_key: Hashable = None,
        model: TimingModel | None = None,
        fingerprint: str | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._stages = tuple(s for s in LANE_STAGES if has_frontiers or s != "frontiers")
        self._parallelism = max(1, parallelism)
        self._key, self._model, self._fingerprint = timing_key, model, fingerprint
        self._expected = model.expected(timing_key) if model is not None else None
        self._schedule_key = ("schedule", schedule_key if schedule_key is not None else timing_key)
        self._schedule = (model.expected(self._schedule_key) or {}) if model is not None else {}
        self._clock = clock
        self._started = clock()
        self._lanes = [_Lane("Search")]
        self._setup_ended: float | None = None
        self._merge_started: float | None = None
        self._merge_done = False
        self._merge_ended: float | None = None
        self._managed = False
        self._outcome: str | None = None
        self._ended: float | None = None
        self._overall = 0.0
        self._eta: tuple[float, float] | None = None
        self._lock = Lock()

    # Event intake -----------------------------------------------------------------

    def handle(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self._outcome is not None:
                return
            now = self._clock()
            events = event["events"] if event.get("phase") == "worker_update" else [event]
            for item in events:
                self._handle(item, now)

    def _handle(self, event: dict[str, Any], now: float) -> None:
        plan = event.get("plan")
        if isinstance(plan, dict) and isinstance(plan.get("lanes"), list) and plan["lanes"]:
            self._lanes = [_Lane(str(label)[:MAX_LABEL_LENGTH]) for label in plan["lanes"]]
            keys = plan.get("lane_keys")
            self._managed = keys is not None
            if keys is not None:
                for planned_lane, (styles, potions) in zip(self._lanes, keys, strict=True):
                    planned_lane.key = (tuple(styles), tuple(potions))
        if not self._managed:
            self._legacy_counts(event, now)
        phase, lane = event.get("phase"), event.get("lane")
        if phase == "merge" and self._merge_started is None:
            self._merge_started = now
        elif phase == "complete" and not self._merge_done:
            self._merge_done, self._merge_ended = True, now
        if isinstance(lane, int) and 0 <= lane < len(self._lanes):
            self._lane_event(self._lanes[lane], event, now)
        elif lane is None and len(self._lanes) == 1 and not self._managed:
            self._lane_event(self._lanes[0], event, now)

    def _legacy_counts(self, event: dict[str, Any], now: float) -> None:
        """Accept profile counters from callers that do not tag lanes."""
        total = event.get("total_profiles")
        if isinstance(total, int) and 0 < total != len(self._lanes) and "plan" not in event:
            self._lanes = [
                self._lanes[i] if i < len(self._lanes) else _Lane(f"Profile {i + 1}")
                for i in range(total)
            ]
        completed = event.get("completed_profiles")
        if isinstance(completed, int) and "lane" not in event:
            for lane in self._lanes[: max(0, completed)]:
                lane.finish(now, self._stages)

    def _lane_event(self, lane: _Lane, event: dict[str, Any], now: float) -> None:
        if lane.complete:
            return
        phase = event.get("phase")
        if phase == "lane_started":
            if lane.started is None:
                lane.started = event.get("started_at", now)
                lane.worker_slot = event.get("worker_slot")
                if self._setup_ended is None or lane.started < self._setup_ended:
                    self._setup_ended = lane.started
                lane.advance(0, 0.0, lane.started, self._stages, counted=False)
        elif phase == "lane_collecting":
            lane.collecting = True
        elif phase in self._stages and not lane.collecting:
            if self._setup_ended is None:
                self._setup_ended = now
            total = event.get("stage_total") or 0
            done = event.get("stage_done") or 0
            counted = isinstance(total, int) and total > 0
            fraction = done / total if counted else 0.0
            lane.advance(self._stages.index(phase), fraction, now, self._stages, counted=counted)
        if event.get("lane_status") == "complete":
            started = event.get("started_at", lane.started)
            if started is None:
                started = now
            if self._setup_ended is None or started < self._setup_ended:
                self._setup_ended = started
            lane.duration = event.get("duration_seconds")
            if lane.duration is None and lane.started is not None:
                lane.duration = now - lane.started
            lane.finish(now, self._stages)

    def finish(self, *, succeeded: bool) -> None:
        with self._lock:
            if self._outcome is not None:
                return
            now = self._clock()
            self._outcome, self._ended = ("complete" if succeeded else "failed"), now
            if not succeeded:
                return
            for lane in self._lanes:
                lane.finish(now, self._stages)
            if self._model is not None:
                if self._managed:
                    self._record_schedule(now)
                else:
                    self._model.record(self._key, self._measured(now))

    def _record_schedule(self, now: float) -> None:
        assert self._model is not None
        timings: dict[Hashable, float] = {
            lane.key: lane.duration
            for lane in self._lanes
            if lane.key is not None and lane.duration is not None and lane.duration > 0
        }
        if self._merge_started is not None:
            end = self._merge_ended if self._merge_ended is not None else now
            timings["merge"] = end - self._merge_started
        if self._setup_ended is not None:
            timings["setup"] = max(0.0, self._setup_ended - self._started)
        self._model.record(self._schedule_key, timings)

    def _measured(self, now: float) -> dict[str, float]:
        lanes_started = self._setup_ended or now
        merge_start = self._merge_started or now
        durations = {
            "setup": lanes_started - self._started,
            "merge": (now - merge_start) if len(self._lanes) > 1 else 0.0,
        }
        observed = [lane for lane in self._lanes if lane.observed] or self._lanes
        for stage in self._stages:
            values = [lane.durations.get(stage, 0.0) for lane in observed]
            durations[stage] = sum(values) / len(values)
        return durations

    # Snapshot ---------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self._ended if self._ended is not None else self._clock()
            elapsed = now - self._started
            weights = self._weights()
            fractions = [self._lane_fraction(lane, weights, now) for lane in self._lanes]
            self._overall = max(self._overall, self._overall_fraction(weights, fractions, now))
            phase = self._phase()
            multi = len(self._lanes) > 1
            snapshot: dict[str, Any] = {
                "phase": phase,
                "label": self._label(phase),
                "completed": sum(lane.complete for lane in self._lanes) if multi else 0,
                "total": len(self._lanes) if multi else 0,
                "elapsed_seconds": elapsed,
                "fraction": round(self._overall, 4),
                "eta_seconds": (
                    self._schedule_eta(now)
                    if self._managed
                    else self._eta_seconds(weights, fractions, elapsed, now)
                ),
                "stages": self._stage_rows(weights, now),
                "scenario_fingerprint": self._fingerprint,
            }
            if self._managed and snapshot["eta_seconds"] is None:
                search_range = self._search_eta_range(now)
                if search_range is not None:
                    snapshot["search_eta_range_seconds"] = search_range
            if multi:
                rows = [
                    self._lane_row(index, lane, f)
                    for index, (lane, f) in enumerate(zip(self._lanes, fractions, strict=True))
                ]
                counts = dict.fromkeys(("complete", "running", "pending"), 0)
                if self._managed:
                    counts["collecting"] = 0
                for row in rows:
                    counts[row["status"]] += 1
                snapshot["lane_counts"] = counts
                # Few searches: show every row. Many: show only the ones running now.
                if self._managed or len(rows) > MAX_REPORTED_LANES:
                    rows = [row for row in rows if row["status"] == "running"]
                snapshot["lanes"] = rows[:MAX_REPORTED_LANES]
            return snapshot

    def _label(self, phase: str) -> str:
        if len(self._lanes) > 1 and phase in self._stages:
            return f"Running {len(self._lanes)} searches"
        return STAGE_LABELS.get(phase, phase.replace("_", " ").capitalize())

    def _stage_seconds(self) -> tuple[dict[str, float], bool]:
        """Prefer stage timings of lanes finished in this run over shape history."""
        finished = [lane for lane in self._lanes if lane.complete and lane.observed]
        if finished:
            measured = {
                s: sum(lane.durations.get(s, 0.0) for lane in finished) / len(finished)
                for s in self._stages
            }
            if sum(measured.values()) > 0:
                return measured, True
        expected = self._expected or {}
        return {s: expected.get(s, 0.0) for s in self._stages}, False

    def _weights(self) -> _Weights:
        lanes = len(self._lanes)
        stage_seconds, in_run = self._stage_seconds()
        lane_seconds = sum(stage_seconds.values())
        if lane_seconds > 0:
            expected = self._expected or {}
            setup = expected.get("setup", 0.0)
            merge = expected.get("merge", 0.0) if lanes > 1 else 0.0
            waves = ceil(lanes / min(self._parallelism, lanes))
            total = setup + lane_seconds * waves + merge
            return _Weights(
                stages={s: value / lane_seconds for s, value in stage_seconds.items()},
                stage_seconds=stage_seconds,
                lane_seconds=lane_seconds,
                setup=setup / total,
                merge=merge / total,
                setup_seconds=setup,
                merge_seconds=merge,
                in_run=in_run,
            )
        raw = {s: DEFAULT_STAGE_WEIGHTS[s] for s in self._stages}
        scale = sum(raw.values())
        return _Weights(
            stages={s: value / scale for s, value in raw.items()},
            stage_seconds={},
            lane_seconds=0.0,
            setup=DEFAULT_SETUP_SHARE,
            merge=DEFAULT_MERGE_SHARE if lanes > 1 else 0.0,
            setup_seconds=0.0,
            merge_seconds=0.0,
            in_run=False,
        )

    def _stage_fraction(self, lane: _Lane, weights: _Weights, now: float) -> float:
        """Prefer measured work; interpolate only when a stage has no counters."""
        if lane.counted:
            return lane.reported
        expected = weights.stage_seconds.get(self._stages[lane.stage], 0.0)
        if expected <= 0:
            return lane.reported
        interpolated = min(INTERPOLATION_CEILING, (now - lane.stage_started) / expected)
        return max(lane.reported, interpolated)

    def _lane_fraction(self, lane: _Lane, weights: _Weights, now: float) -> float:
        if lane.complete:
            return 1.0
        if lane.stage < 0:
            return 0.0
        before = sum(weights.stages[s] for s in self._stages[: lane.stage])
        current = weights.stages[self._stages[lane.stage]]
        return before + current * self._stage_fraction(lane, weights, now)

    def _overall_fraction(self, weights: _Weights, lanes: list[float], now: float) -> float:
        if self._outcome == "complete":
            return 1.0
        if self._setup_ended is not None:
            setup = 1.0
        elif weights.setup_seconds > 0:
            setup = min(INTERPOLATION_CEILING, (now - self._started) / weights.setup_seconds)
        else:
            setup = 0.0
        merge = 1.0 if self._merge_done else (0.5 if self._merge_started is not None else 0.0)
        lane_weight = 1.0 - weights.setup - weights.merge
        value = weights.setup * setup + lane_weight * sum(lanes) / len(lanes)
        return min(RUNNING_CEILING, value + weights.merge * merge)

    def _work_remaining(self, weights: _Weights, lanes: list[float]) -> float | None:
        """Wall seconds left from known lane durations, shared across the worker pool."""
        if weights.lane_seconds <= 0:
            return None
        left = [(1.0 - fraction) * weights.lane_seconds for fraction in lanes if fraction < 1]
        lane_wall = 0.0
        if left:
            workers = min(self._parallelism, len(left))
            lane_wall = max(sum(left) / workers, max(left))
        setup = 0.0 if self._setup_ended is not None else weights.setup_seconds
        merge = 0.0 if self._merge_done else weights.merge_seconds
        return setup + lane_wall + merge

    def _schedule_eta(self, now: float) -> float | None:
        if self._outcome == "complete":
            return 0.0
        if self._outcome or self._merge_done:
            return None
        merge = self._schedule.get("merge")
        if merge is None:
            return None
        if self._merge_started is not None:
            left = merge - (now - self._merge_started)
            return round(left, 1) if left > 0 else None
        setup_left = 0.0
        if self._setup_ended is None:
            setup = self._schedule.get("setup")
            if setup is None or setup <= now - self._started:
                return None
            setup_left = setup - (now - self._started)

        samples = self._completed_durations()
        remaining = []
        for lane in self._lanes:
            if lane.complete or lane.key is None:
                continue
            duration = self._schedule.get(lane.key)
            group = samples.get(lane.key[0], [])
            if duration is None:
                if len(group) < 2:
                    return None
                duration = median(group)
            age = now - lane.started if lane.started is not None else 0.0
            left = duration - age
            if left <= 0:
                return None
            remaining.append((lane, left))

        return round(setup_left + self._project_worker_queue(remaining) + merge, 1)

    def _completed_durations(self) -> dict[tuple[str, ...], list[float]]:
        samples: dict[tuple[str, ...], list[float]] = {}
        for lane in self._lanes:
            if lane.key is not None and lane.duration is not None and lane.duration > 0:
                samples.setdefault(lane.key[0], []).append(lane.duration)
        return samples

    def _search_eta_range(self, now: float) -> list[float] | None:
        """Estimate branch work before a full-run ETA can be calibrated."""
        if self._outcome or self._merge_started is not None:
            return None
        samples = self._completed_durations()
        groups = {lane.key[0] for lane in self._lanes if lane.key is not None}
        # Early waves can be much cheaper than later assignments. Wait until
        # most of the distinct style assignments have finished a job.
        if not samples or 3 * len(samples) < 2 * len(groups):
            return None
        observed = [value for durations in samples.values() for value in durations]
        typical = median(observed)
        by_first_style: dict[str, list[float]] = {}
        for styles, durations in samples.items():
            by_first_style.setdefault(styles[0], []).extend(durations)
        unfinished = [lane for lane in self._lanes if not lane.complete and lane.key is not None]
        if not unfinished:
            return None
        ages = [now - lane.started if lane.started is not None else 0.0 for lane in unfinished]
        slow = max(*observed, *ages)
        lower, upper = [], []
        for lane, age in zip(unfinished, ages, strict=True):
            assert lane.key is not None
            history = self._schedule.get(lane.key)
            peers = samples.get(lane.key[0])
            if history is not None:
                low, high = history, history
            elif peers:
                low, high = median(peers), max(peers)
            else:
                related = by_first_style.get(lane.key[0][0])
                low = median(related) if related else typical
                high = max(related) if related else slow
            lower.append((lane, max(0.0, PROVISIONAL_LOW_FACTOR * low - age)))
            upper.append(
                (
                    lane,
                    max(1.0, PROVISIONAL_HIGH_FACTOR * high - age, age * PROVISIONAL_OVERRUN_SHARE),
                )
            )
        return [round(self._project_worker_queue(bounds), 1) for bounds in (lower, upper)]

    def _project_worker_queue(self, remaining: Sequence[tuple[_Lane, float]]) -> float:
        active: list[float] = []
        queued: list[float] = []
        collecting: list[float] = []
        latest: dict[int, tuple[float, float]] = {}
        for lane, left in remaining:
            if lane.collecting:
                collecting.append(left)
            if lane.started is None:
                queued.append(left)
            elif lane.worker_slot is not None:
                prior = latest.get(lane.worker_slot)
                if prior is None or lane.started >= prior[0]:
                    latest[lane.worker_slot] = (lane.started, left)
            elif not lane.collecting:
                active.append(left)

        active.extend(left for _, left in latest.values())
        workers = active + [0.0] * max(0, self._parallelism - len(active))
        heapify(workers)
        for duration in queued:
            heapreplace(workers, workers[0] + duration)
        return max([*workers, *collecting])

    def _eta_seconds(
        self, weights: _Weights, lanes: list[float], elapsed: float, now: float
    ) -> float | None:
        if self._outcome is not None:
            return 0.0 if self._outcome == "complete" else None
        fraction = self._overall
        work = self._work_remaining(weights, lanes)
        live = (
            elapsed / fraction - elapsed
            if fraction >= MIN_LIVE_FRACTION and elapsed >= MIN_LIVE_SECONDS
            else None
        )
        if work is not None and live is not None and not weights.in_run:
            # Shape history may be stale; trust this run more as it progresses.
            remaining: float | None = (1 - fraction) * work + fraction * live
        else:
            remaining = work if work is not None else live
        if remaining is None:
            return None
        remaining = max(1.0, remaining)
        if self._eta is not None:
            previous, at = self._eta
            carried = max(1.0, previous - (now - at))
            remaining = ETA_SMOOTHING * remaining + (1 - ETA_SMOOTHING) * carried
        self._eta = (remaining, now)
        return round(remaining, 1)

    def _phase(self) -> str:
        if self._outcome is not None:
            return self._outcome
        if self._merge_started is not None:
            return "merge"
        active = [lane.stage for lane in self._lanes if not lane.complete and lane.stage >= 0]
        if active:
            return self._stages[min(active)]
        if all(lane.complete for lane in self._lanes):
            return "merge" if len(self._lanes) > 1 else self._stages[-1]
        return "preparation"

    def _lane_row(self, index: int, lane: _Lane, fraction: float) -> dict[str, Any]:
        if lane.complete:
            status = "complete"
        elif self._outcome:
            status = "pending"
        elif self._managed and lane.collecting:
            status = "collecting"
        else:
            started = lane.started is not None if self._managed else lane.stage >= 0
            status = "running" if started else "pending"
        stage = self._stages[lane.stage] if 0 <= lane.stage < len(self._stages) else None
        return {
            "lane_id": index,
            "label": lane.label,
            "status": status,
            "stage": stage,
            "stage_label": STAGE_LABELS[stage] if stage else None,
            "fraction": round(fraction, 4),
            "stage_fraction": (
                round(lane.reported, 4) if lane.counted and 0 < lane.reported < 1 else None
            ),
        }

    def _stage_rows(self, weights: _Weights, now: float) -> list[dict[str, Any]]:
        rows = []
        for index, stage in enumerate(self._stages):
            parts = [
                1.0
                if lane.complete or lane.stage > index
                else self._stage_fraction(lane, weights, now)
                if lane.stage == index
                else 0.0
                for lane in self._lanes
            ]
            active = any(lane.stage == index and not lane.complete for lane in self._lanes)
            rows.append(self._row(stage, sum(parts) / len(parts), active))
        if len(self._lanes) > 1:
            merge = 1.0 if self._merge_done or self._outcome == "complete" else 0.0
            rows.append(self._row("merge", merge, self._merge_started is not None))
        return rows

    def _row(self, stage: str, fraction: float, active: bool) -> dict[str, Any]:
        if self._outcome == "complete" or fraction >= 1:
            status = "complete"
        elif active:
            status = "active"
        else:
            status = "pending"
        return {
            "id": stage,
            "label": STAGE_LABELS[stage],
            "status": status,
            "fraction": round(1.0 if status == "complete" else fraction, 4),
        }
