"""Read-only session objective archives under the existing private Gear boundary."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from tracker.api.gear_optimizations import error
from tracker.api.gear_ui import GearRoute, no_cache, resources
from tracker.gear.objective_store import RunUnavailable


def read_limit(request: Request) -> None:
    host = request.client.host if request.client is not None else "local"
    if not request.app.state.gear_service.objective_store.allow_read(host):
        raise error("rate_limited", "Too many result requests; try again shortly", 429)


router = APIRouter(
    prefix="/ui-api/gear/optimization-runs",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache), Depends(read_limit)],
    route_class=GearRoute,
)


@router.get("/{run_id}")
def metadata(request: Request, run_id: UUID):
    snapshot, gear, _ = resources(request)
    try:
        return gear.objective_store.metadata(str(run_id), player_id=snapshot.player_id)
    except RunUnavailable as exc:
        raise error("optimization_run_unavailable", str(exc), 410) from exc


@router.get("/{run_id}/frontiers/{group_id}/points")
def points(
    request: Request,
    run_id: UUID,
    group_id: Annotated[str, Path(max_length=128)],
    sort: str = Query(default="dps", max_length=256),
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
):
    snapshot, gear, _ = resources(request)
    try:
        return gear.objective_store.page(
            str(run_id),
            group_id,
            player_id=snapshot.player_id,
            sort=sort,
            direction=direction,
            limit=limit,
            cursor=cursor,
        )
    except RunUnavailable as exc:
        raise error("optimization_run_unavailable", str(exc), 410) from exc
    except ValueError as exc:
        raise error("invalid_request", str(exc), field="cursor" if cursor else "sort") from exc


@router.get("/{run_id}/solutions/{solution_id}")
def solution(request: Request, run_id: UUID, solution_id: Annotated[str, Path(max_length=128)]):
    snapshot, gear, _ = resources(request)
    try:
        return gear.objective_store.solution(str(run_id), solution_id, player_id=snapshot.player_id)
    except RunUnavailable as exc:
        raise error("optimization_run_unavailable", str(exc), 410) from exc
