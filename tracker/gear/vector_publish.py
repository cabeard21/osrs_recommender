"""Complete vector frontier projection shared by concrete branch mergers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from tracker.gear.vector_archive import VectorArchive, solution_identity


class FrontierPoints(Sequence[dict[str, Any]]):
    """Repeatable, picklable disk-backed points until publication consumes them."""

    def __init__(
        self,
        archive: VectorArchive,
        limit: int | None,
        id_prefix: str = "",
        maximum_loss_pct: float | None = None,
    ) -> None:
        self.archive, self.limit, self.id_prefix = archive, limit, id_prefix
        self.maximum_loss_pct = maximum_loss_pct

    @property
    def minimum_dps(self) -> float | None:
        if self.maximum_loss_pct is None:
            return None
        return self.archive.baseline_dps() * (1 - self.maximum_loss_pct / 100)

    def __len__(self) -> int:
        return self.archive.count(self.minimum_dps)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        baseline = self.archive.baseline_dps()
        for row in self.archive.iter_solutions(self.minimum_dps):
            yield {
                "id": f"{self.id_prefix}objective-{self.limit}-{solution_identity(row)[:24]}",
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
                points.archive, points.limit, points.id_prefix, maximum_loss_pct
            )
        else:
            baseline = group.get("baseline_dps") or 0
            floor = baseline * (1 - maximum_loss_pct / 100)
            filtered = [point for point in points if point["solution"]["score"] >= floor]
        result.append({**group, "points": filtered})
    return result


def publish_groups(
    archives: Mapping[int | None, Iterable[dict[str, Any]]], request: Any, *, id_prefix: str = ""
) -> list[dict[str, Any]]:
    """Publish every discovered nondominated point; presentation filtering happens later."""
    objective_ids = tuple(objective.id for objective in request.objectives or ())
    result = []
    for limit, candidates in archives.items():
        archive = VectorArchive(objective_ids)
        for candidate in candidates:
            if limit is None or candidate["maximum_actions"] <= limit:
                archive.add(candidate)
        baseline = archive.baseline_dps()
        result.append(
            {
                "swap_limit": limit,
                "baseline_dps": baseline,
                "sampled": False,
                "points": FrontierPoints(archive, limit, id_prefix),
            }
        )
    return result
