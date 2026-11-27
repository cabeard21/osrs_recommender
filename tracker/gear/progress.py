"""Search-side progress reporting: lane-local stages, in-stage counters and worker slots.

Progress is telemetry only. Reporters emit plain dict events through a callback and
never influence search order, budgets or results. Without a callback every method is
a cheap no-op, so hot loops may call them unconditionally.

Event vocabulary (all keys optional except ``phase``):

* ``phase`` - a lane stage from :data:`LANE_STAGES`, or a run-level marker such as
  ``merge`` or ``complete``. Lane lifecycle phases are ``lane_started``,
  ``lane_collecting`` and ``lane_complete``.
* ``stage_done`` / ``stage_total`` - integer progress inside the current stage.
* ``lane`` - which independent search (Auto discipline or potion profile) this is.
* ``lane_status`` - ``"complete"`` on successful lane receipt.
* ``plan`` - labels and compatible timing keys for the independent searches.
* ``worker_update`` - a batch of slot and future events observed together.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import monotonic, perf_counter
from typing import Any

Emit = Callable[[dict[str, Any]], None]

LANE_STAGES: tuple[str, ...] = (
    "preparation",
    "candidate_ranking",
    "gear_search",
    "refinement",
    "frontiers",
)
STAGE_LABELS: dict[str, str] = {
    "setup": "Preparing search",
    "preparation": "Preparing account facts",
    "candidate_ranking": "Ranking candidate items",
    "gear_search": "Searching gear combinations",
    "refinement": "Refining finalists",
    "frontiers": "Exploring trade-offs",
    "merge": "Combining results",
    "complete": "Complete",
    "failed": "Stopped",
}
# Fine enough for a smooth bar; coarse enough that throttled integers rarely repeat.
STAGE_SCALE = 1000
REPORT_INTERVAL_SECONDS = 0.1
# Hot loops call the reporter every this-many nodes (a power of two minus one mask).
NODE_REPORT_MASK = 1023
_LANE_LABEL_LIMIT = 512
_SLOT_STAGES = frozenset({"candidate_ranking", "gear_search"})


class StageReporter:
    """Throttled, monotonic in-stage progress for one ``optimize()`` lane."""

    __slots__ = ("_clock", "_emit", "_interval", "_last_done", "_last_sent", "_phase", "_segment")

    def __init__(
        self,
        emit: Emit | None = None,
        *,
        clock: Callable[[], float] = perf_counter,
        interval: float = REPORT_INTERVAL_SECONDS,
    ) -> None:
        self._emit = emit
        self._clock = clock
        self._interval = interval
        self._phase: str | None = None
        self._segment = (0, 1)
        self._last_done = 0
        self._last_sent = float("-inf")

    @property
    def active(self) -> bool:
        return self._emit is not None

    def stage(self, phase: str, **extra: Any) -> None:
        """Enter a stage; always emitted so stage transitions are never throttled away."""
        if self._emit is None:
            return  # The shared no-op reporter stays stateless.
        self._phase, self._segment, self._last_done = phase, (0, 1), 0
        self._send(0, extra)

    def segment(self, index: int, count: int) -> None:
        """Divide the current stage into ``count`` equal parts and enter part ``index``."""
        if self._emit is None:
            return
        count = max(1, count)
        self._segment = (min(max(0, index), count - 1), count)
        self.fraction(0.0)

    def fraction(self, value: float) -> None:
        """Report completion of the current segment; never moves backwards."""
        if self._emit is None or self._phase is None:
            return
        index, count = self._segment
        clamped = min(1.0, max(0.0, value))
        done = int(STAGE_SCALE * (index + clamped) / count)
        if done <= self._last_done:
            return
        if self._clock() - self._last_sent < self._interval:
            return
        self._last_done = done
        self._send(done, {})

    def slots(self, value: float) -> None:
        """Slot-loop progress; frontier passes reuse these loops but measure node budgets."""
        if self._phase in _SLOT_STAGES:
            self.fraction(value)

    def finish(self) -> None:
        if self._emit is not None:
            self._emit({"phase": "lane_complete", "lane_status": "complete"})

    def _send(self, done: int, extra: dict[str, Any]) -> None:
        if self._emit is None or self._phase is None:
            return
        self._last_sent = self._clock()
        self._emit({"phase": self._phase, "stage_done": done, "stage_total": STAGE_SCALE, **extra})


NULL_REPORTER = StageReporter()


def for_lane(emit: Emit | None, lane: int, *, include_finish: bool = True) -> Emit | None:
    """Tag a lane's events, optionally leaving completion to its caller."""
    if emit is None:
        return None

    def tagged(event: dict[str, Any]) -> None:
        if include_finish or event.get("lane_status") != "complete":
            emit({**event, "lane": lane})

    return tagged


def lane_label(discipline: str | None, potion_ids: Sequence[str] | None = None) -> str:
    """Human label for a discipline assignment and/or a frozen potion profile."""
    if discipline and "=" in discipline:
        label = " / ".join(
            f"{role}: {style.capitalize()}"
            for role, style in (entry.split("=", 1) for entry in discipline.split("/"))
        )
    else:
        label = discipline.capitalize() if discipline else ""
    parts = [label] if label else []
    if potion_ids is not None:
        names = [key.replace("_", " ").capitalize() for key in potion_ids]
        parts.append(", ".join(names) if names else "No potions")
    return (" · ".join(parts) or "Search")[:_LANE_LABEL_LIMIT]


def lane_key(request: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Identity for timing a concrete lane independently of its display label."""
    return tuple(role.style for role in request.roles), tuple(sorted(request.potions.selected_ids))


class WorkerSlots:
    """Per-worker shared progress slots written lock-free by spawned children.

    Each child owns exactly one slot (its barrier index), so there is a single writer
    per slot. A sequence counter is made odd while a write is in flight; readers
    discard torn reads instead of locking, so a killed child cannot wedge the parent.
    """

    # Slot layout: sequence, lane + 1 (0 = idle), stage index, done, total, start.
    WIDTH = 6

    def __init__(self, context: Any, workers: int) -> None:
        self.workers = workers
        self._values = context.RawArray("d", workers * self.WIDTH)

    def write(
        self, slot: int, lane: int, stage: int, done: int, total: int, started_at: float
    ) -> None:
        base = slot * self.WIDTH
        values = self._values
        values[base] += 1
        values[base + 1] = lane + 1
        values[base + 2] = stage
        values[base + 3] = done
        values[base + 4] = total
        values[base + 5] = started_at
        values[base] += 1

    def clear(self) -> None:
        for slot in range(self.workers):
            base = slot * self.WIDTH
            self._values[base] += 1
            for offset in range(1, self.WIDTH):
                self._values[base + offset] = 0
            self._values[base] += 1

    def read(self) -> list[tuple[int, float, int, int, int, int, float]]:
        """Return consistent rows with slot identity and worker pickup timestamp."""
        rows = []
        for slot in range(self.workers):
            base = slot * self.WIDTH
            before = self._values[base]
            if int(before) % 2:
                continue
            lane, stage, done, total = (int(self._values[base + i]) for i in range(1, 5))
            started_at = self._values[base + 5]
            if self._values[base] != before or lane <= 0:
                continue
            rows.append((slot, before, lane - 1, stage, done, total, started_at))
        return rows


class SlotWriter:
    """Worker-side progress callback that publishes one lane's events to a slot."""

    def __init__(self, slots: WorkerSlots, slot: int, lane: int) -> None:
        self._slots, self._slot, self._lane = slots, slot, lane
        self.started_at = monotonic()
        slots.write(slot, lane, 0, 0, 0, self.started_at)

    def returning(self) -> None:
        """Mark the result ready for transfer after the worker's search returns."""
        self._slots.write(self._slot, self._lane, len(LANE_STAGES), 0, 0, self.started_at)

    def __call__(self, event: dict[str, Any]) -> None:
        phase = event.get("phase")
        if phase not in LANE_STAGES:
            return
        self._slots.write(
            self._slot,
            self._lane,
            LANE_STAGES.index(phase),
            int(event.get("stage_done", 0)),
            int(event.get("stage_total", 0)),
            self.started_at,
        )


class SlotReader:
    """Parent-side poller converting changed worker slots into lane-tagged events."""

    def __init__(self, slots: WorkerSlots) -> None:
        self._slots = slots
        self._seen: dict[int, tuple[float, int, bool]] = {}

    def events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for slot, sequence, lane, stage, done, total, started_at in self._slots.read():
            previous = self._seen.get(slot)
            if previous is not None and previous[0] == sequence:
                continue
            returning = stage >= len(LANE_STAGES)
            self._seen[slot] = (sequence, lane, returning)
            if previous is None or previous[1] != lane:
                if previous is not None and not previous[2]:
                    events.append({"phase": "lane_collecting", "lane": previous[1]})
                events.append(
                    {
                        "phase": "lane_started",
                        "lane": lane,
                        "started_at": started_at,
                        "worker_slot": slot,
                    }
                )
            if returning:
                events.append({"phase": "lane_collecting", "lane": lane})
                continue
            events.append(
                {
                    "phase": LANE_STAGES[stage],
                    "lane": lane,
                    "stage_done": done,
                    "stage_total": total,
                }
            )
        return events
