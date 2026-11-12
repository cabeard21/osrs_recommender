"""Frozen arrow running-cost comparison transport."""

from __future__ import annotations

import asyncio
from threading import Event
from typing import Any

from fastapi import APIRouter, Depends, Request

from tracker.api.gear_evaluations import (
    EquipmentEvaluationRequest,
    FixedCombatOption,
    calculate_evaluation,
)
from tracker.api.gear_optimizations import BrowserOptimizationRequest, consume, error, same_origin
from tracker.api.gear_ui import DTO, GearRoute, no_cache, resources
from tracker.content.schema import ItemSlot
from tracker.gear.ammo import compare_arrows
from tracker.gear.optimizer import ItemId

router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


class AmmoComparisonRequest(DTO):
    scenario: BrowserOptimizationRequest
    loadout: dict[ItemSlot, ItemId]
    combat_option: FixedCombatOption


def calculate_comparison(
    snapshot: Any,
    gear: Any,
    prices: Any,
    body: AmmoComparisonRequest,
    stopped: Event,
) -> dict[str, Any]:
    if body.combat_option.attack_type not in {"light", "standard", "heavy"}:
        raise ValueError("Arrow comparison requires a ranged combat option")
    role = body.scenario.roles[0].id
    fixed = EquipmentEvaluationRequest(
        scenario=body.scenario,
        baseline_loadouts={role: body.loadout},
        proposed_loadouts={role: body.loadout},
        baseline_combat_options={role: body.combat_option},
        proposed_combat_options={role: body.combat_option},
    )
    baseline = calculate_evaluation(snapshot, gear, prices, fixed, stopped)
    points, limitations = compare_arrows(
        snapshot,
        gear,
        prices,
        body.scenario,
        {str(k): v for k, v in body.loadout.items()},
        body.combat_option.model_dump(),
        baseline.evaluated_at,
        stopped,
    )
    return {
        **baseline.model_dump(mode="json", exclude={"baseline", "proposed", "deltas"}),
        "points": points,
        "limitations": limitations,
        "cost_model_version": "arrow-running-cost-v1",
    }


@router.post("/ammo-comparisons")
async def ammo_comparisons(request: Request, body: AmmoComparisonRequest) -> dict[str, Any]:
    same_origin(request)
    snapshot, gear, prices = await asyncio.to_thread(resources, request)
    if snapshot is None:
        raise error("account_unavailable", "Synchronize an account before evaluating", 409)
    if snapshot.fingerprint != body.scenario.expected_snapshot_id:
        raise error("snapshot_changed", "Account observations changed; refresh and rerun", 409)
    stopped = Event()
    worker = asyncio.create_task(
        asyncio.to_thread(calculate_comparison, snapshot, gear, prices, body, stopped)
    )
    try:
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.05)
            if await request.is_disconnected():
                stopped.set()
                worker.add_done_callback(consume)
                raise error("evaluation_cancelled", "Evaluation cancelled", 499)
        result = worker.result()
        fresh, _, _ = await asyncio.to_thread(resources, request)
        if fresh is None or fresh.fingerprint != snapshot.fingerprint:
            raise error("snapshot_changed", "Account observations changed; refresh and rerun", 409)
        return result
    except asyncio.CancelledError:
        stopped.set()
        worker.add_done_callback(consume)
        raise
    except ValueError as exc:
        message = str(exc)
        if message.startswith("optimizer_busy"):
            raise error("optimizer_busy", "Another equipment calculation is running", 503) from exc
        raise error("invalid_request", message) from exc
