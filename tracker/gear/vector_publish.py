"""Complete vector frontier projection shared by concrete branch mergers."""

from __future__ import annotations

import json
from array import array
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from math import isfinite
from typing import Any, cast

from tracker.gear.vector_archive import VectorArchive, own_vector_archives, resource_tie

_MAX_PACKED_VALUES = 2_000_000
_MAX_PACKED_ROWS = 100_000


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ValueError("optimization_cancelled")


class FrontierPoints(Sequence[dict[str, Any]]):
    """Repeatable, picklable disk-backed points until publication consumes them."""

    def __init__(
        self,
        archive: VectorArchive,
        limit: int | None,
        id_prefix: str = "",
        maximum_loss_pct: float | None = None,
        baseline_dps: float | None = None,
    ) -> None:
        self.archive, self.limit, self.id_prefix = archive, limit, id_prefix
        self.maximum_loss_pct = maximum_loss_pct
        self.baseline_dps = archive.baseline_dps() if baseline_dps is None else baseline_dps

    @property
    def minimum_dps(self) -> float | None:
        if self.maximum_loss_pct is None:
            return None
        return self.baseline_dps * (1 - self.maximum_loss_pct / 100)

    def __len__(self) -> int:
        return self.archive.count(self.minimum_dps)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        baseline = self.baseline_dps
        for identity, row in self.archive.iter_identified_solutions(self.minimum_dps):
            yield {
                "id": f"{self.id_prefix}objective-{self.limit}-{identity[:24]}",
                "solution": row,
                "dps_loss": baseline - row["score"],
                "dps_loss_pct": 100 * (baseline - row["score"]) / baseline if baseline else None,
            }

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            return list(self)[index]
        if index < 0:
            index += len(self)
        for position, point in enumerate(self):
            if position == index:
                return point
        raise IndexError(index)

    def close(self) -> None:
        self.archive.close()


def filter_groups(
    groups: Iterable[dict[str, Any]], maximum_loss_pct: float
) -> list[dict[str, Any]]:
    """Apply a final global DPS floor without truncating concrete branch archives."""
    result = []
    for group in groups:
        points = group["points"]
        if isinstance(points, FrontierPoints):
            filtered: Any = FrontierPoints(
                points.archive,
                points.limit,
                points.id_prefix,
                maximum_loss_pct,
                group.get("baseline_dps"),
            )
        else:
            baseline = group.get("baseline_dps") or 0
            floor = baseline * (1 - maximum_loss_pct / 100)
            filtered = [point for point in points if point["solution"]["score"] >= floor]
        result.append({**group, "points": filtered})
    return result


def _compact_merge(
    sources: Sequence[FrontierPoints],
    caps: tuple[int | None, ...],
    objective_ids: tuple[str, ...],
    cancelled: Callable[[], bool] | None,
) -> VectorArchive | None:
    from tracker.gear.native import record
    from tracker.gear.native._frontier import pareto_indices

    dimensions = len(objective_ids) + 1
    source_rows: list[tuple[VectorArchive, int, str]] = []
    positions: dict[str, int] = {}
    values = array("d")
    for source, cap in zip(sources, caps, strict=True):
        for rowid, identity, *coordinates in source.archive.numeric_rows(source.minimum_dps, cap):
            if len(source_rows) % 1024 == 0:
                _check_cancelled(cancelled)
            previous = positions.get(identity)
            if previous is not None and values[previous : previous + dimensions] != array(
                "d", coordinates
            ):
                # Ordered replacement can revive or remove a previously compared vector.
                record("frontier_merge_reference", reason="conflicting_identity")
                return None
            if (
                len(source_rows) >= _MAX_PACKED_ROWS
                or len(values) + dimensions > _MAX_PACKED_VALUES
                or not all(map(isfinite, coordinates))
                or dimensions > 65
            ):
                record("fallback", reason="frontier_merge_numeric_capacity")
                return None
            positions[identity] = len(values)
            values.extend(coordinates)
            source_rows.append((source.archive, rowid, identity))

    def packed_vector(position: int) -> tuple[float, ...]:
        start = position * dimensions
        return tuple(values[start : start + dimensions])

    def tie_key(position: int) -> tuple[Any, ...]:
        archive, rowid, _ = source_rows[position]
        return resource_tie(json.loads(archive.raw_report(rowid)))

    winners: dict[tuple[float, ...], int] = {}
    for index, position in enumerate(pareto_indices(values, dimensions, cancelled)):
        if index % 1024 == 0:
            _check_cancelled(cancelled)
        vector = packed_vector(position)
        previous = winners.get(vector)
        if previous is None or tie_key(position) < tie_key(previous):
            winners[vector] = position

    def reports() -> Iterator[tuple[Any, ...]]:
        for index, (vector, position) in enumerate(winners.items()):
            if index % 1024 == 0:
                _check_cancelled(cancelled)
            archive, rowid, identity = source_rows[position]
            yield identity, *vector, archive.raw_report(rowid)

    archive = VectorArchive(objective_ids)
    try:
        archive.write_survivors(reports())
    except BaseException:
        archive.close()
        raise
    record("frontier_merge", candidates=len(source_rows), survivors=len(winners))
    return archive


@own_vector_archives
def publish_groups(
    archives: Mapping[int | None, Sequence[Sequence[dict[str, Any]]]],
    request: Any,
    *,
    id_prefix: str = "",
    baselines: Mapping[int | None, dict[str, Any]] | None = None,
    native_merge: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Publish every discovered nondominated point; presentation filtering happens later."""
    objective_ids = tuple(objective.id for objective in request.objectives or ())
    result = []
    max_actions: dict[VectorArchive, int] = {}
    merged: dict[tuple[Any, ...], VectorArchive] = {}
    for limit, sources in archives.items():
        _check_cancelled(cancelled)
        archive = None
        signature = None
        if native_merge and all(
            isinstance(source, FrontierPoints) and source.archive.objective_ids == objective_ids
            for source in sources
        ):
            disk_sources = cast(Sequence[FrontierPoints], sources)
            for points in disk_sources:
                if points.archive not in max_actions:
                    max_actions[points.archive] = points.archive.max_actions()
            caps = tuple(
                limit if limit is not None and max_actions[source.archive] > limit else None
                for source in disk_sources
            )
            signature = tuple(
                (source.archive.path, source.minimum_dps, cap)
                for source, cap in zip(disk_sources, caps, strict=True)
            )
            archive = merged.get(signature)
            if archive is None:
                if (
                    len(disk_sources) == 1
                    and caps == (None,)
                    and disk_sources[0].minimum_dps is None
                ):
                    archive = disk_sources[0].archive
                elif disk_sources:
                    archive = _compact_merge(disk_sources, caps, objective_ids, cancelled)
        if archive is None:
            archive = VectorArchive(objective_ids)
            for index, point in enumerate(point for source in sources for point in source):
                if index % 1024 == 0:
                    _check_cancelled(cancelled)
                candidate = point["solution"]
                if limit is None or candidate["maximum_actions"] <= limit:
                    archive.add(candidate)
        if signature is not None:
            merged[signature] = archive
        winner = (baselines or {}).get(limit)
        baseline = winner["score"] if winner is not None else archive.baseline_dps()
        result.append(
            {
                "swap_limit": limit,
                "baseline_dps": baseline,
                **({"baseline_solution": winner} if winner is not None else {}),
                "sampled": False,
                "points": FrontierPoints(archive, limit, id_prefix, baseline_dps=baseline),
            }
        )
    return result
