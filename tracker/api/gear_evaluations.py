"""Exact fixed-loadout comparisons over one frozen, single-role browser scenario."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from threading import Event
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import model_validator

from tracker.api.gear_optimizations import (
    BrowserOptimizationRequest,
    Purchase,
    consume,
    error,
    same_origin,
    validate_scenario,
)
from tracker.api.gear_ui import DTO, GearRoute, ItemResponse, no_cache, resources
from tracker.content.schema import ItemSlot
from tracker.gear.facts import hypothetical_snapshot
from tracker.gear.models import CombatPerformance
from tracker.gear.optimizer import ItemId

router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


class EquipmentEvaluationRequest(DTO):
    scenario: BrowserOptimizationRequest
    baseline_loadouts: dict[str, dict[ItemSlot, ItemId]]
    proposed_loadouts: dict[str, dict[ItemSlot, ItemId]]

    @model_validator(mode="after")
    def exact_role(self) -> EquipmentEvaluationRequest:
        expected = {self.scenario.roles[0].id}
        if set(self.baseline_loadouts) != expected or set(self.proposed_loadouts) != expected:
            raise ValueError("Both fixed configurations must contain exactly the submitted role")
        return self


class EvaluationReason(DTO):
    path: str
    message: str


class FixedEvaluation(DTO):
    status: Literal["valid", "invalid", "unsupported"]
    equipment: dict[ItemSlot, int]
    performance: CombatPerformance | None
    reasons: list[EvaluationReason]
    purchase_cost_gp: int | None
    purchases: list[Purchase]
    assumed_item_ids: list[int]


class EquipmentChange(DTO):
    slot: ItemSlot
    baseline_item_id: int | None
    proposed_item_id: int | None


class EvaluationDeltas(DTO):
    dps: float
    max_hit: int
    accuracy: float
    attack_interval: float
    purchase_cost_gp: int
    equipment_changes: list[EquipmentChange]
    added_purchase_ids: list[int]
    removed_purchase_ids: list[int]


class EquipmentEvaluationResponse(DTO):
    api_version: Literal["gear-ui-v1"] = "gear-ui-v1"
    evaluated_at: datetime
    scenario: BrowserOptimizationRequest
    scenario_fingerprint: str
    snapshot_id: str
    catalog_version: str
    model_version: str
    assumptions_fingerprint: str
    price_revision: str
    items: list[ItemResponse]
    baseline: FixedEvaluation
    proposed: FixedEvaluation
    deltas: EvaluationDeltas | None


def calculate_evaluation(
    snapshot: Any, gear: Any, prices: Any, body: EquipmentEvaluationRequest, stopped: Event
) -> EquipmentEvaluationResponse:
    if stopped.is_set():
        raise ValueError("evaluation_cancelled")
    now = datetime.now(UTC)
    scenario = body.scenario
    validate_scenario(scenario, gear, snapshot)
    catalog = gear.equipment_catalog()
    role_id = scenario.roles[0].id
    for field, loadouts in (
        ("baseline_loadouts", body.baseline_loadouts),
        ("proposed_loadouts", body.proposed_loadouts),
    ):
        for slot, item_id in loadouts[role_id].items():
            if item_id not in catalog.items:
                raise error(
                    "invalid_request", "Unknown physical item ID", field=f"{field}.{role_id}.{slot}"
                )
            if catalog.items[item_id].slot != slot:
                raise error(
                    "invalid_request",
                    f"Physical item {item_id} does not occupy {slot}",
                    field=f"{field}.{role_id}.{slot}",
                )
    result = gear.evaluate(
        snapshot,
        scenario,
        body.baseline_loadouts[role_id],
        body.proposed_loadouts[role_id],
        price_records=prices,
        now=now,
        cancelled=stopped.is_set,
    )
    projected = hypothetical_snapshot(
        snapshot, scenario.skill_overrides, scenario.quest_overrides, now
    )
    referenced = set(body.baseline_loadouts[role_id].values()) | set(
        body.proposed_loadouts[role_id].values()
    )
    assumptions = {
        "skills": dict(scenario.skill_overrides),
        "quests": dict(scenario.quest_overrides),
        "assumed_item_ids": scenario.assumed_item_ids,
    }
    return EquipmentEvaluationResponse(
        evaluated_at=now,
        scenario=scenario,
        scenario_fingerprint=hashlib.sha256(
            json.dumps(
                scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        snapshot_id=snapshot.fingerprint,
        catalog_version=catalog.revision,
        model_version="normal-attacks-v1",
        assumptions_fingerprint=hashlib.sha256(
            json.dumps(assumptions, sort_keys=True).encode()
        ).hexdigest(),
        price_revision=hashlib.sha256(
            json.dumps({k: str(v) for k, v in sorted(prices.items())}, sort_keys=True).encode()
        ).hexdigest(),
        items=[
            gear.physical_item(projected, i, price_records=prices, now=now)
            for i in sorted(referenced)
        ],
        **result,
    )


@router.post("/evaluations", response_model=EquipmentEvaluationResponse)
async def evaluations(
    request: Request, body: EquipmentEvaluationRequest
) -> EquipmentEvaluationResponse:
    same_origin(request)
    snapshot, gear, prices = await asyncio.to_thread(resources, request)
    if snapshot is None:
        raise error("account_unavailable", "Synchronize an account before evaluating", 409)
    if snapshot.fingerprint != body.scenario.expected_snapshot_id:
        raise error(
            "snapshot_changed",
            "Account observations changed; refresh and rerun",
            409,
            "scenario.expected_snapshot_id",
        )
    stopped = Event()
    worker = asyncio.create_task(
        asyncio.to_thread(calculate_evaluation, snapshot, gear, prices, body, stopped)
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
            raise error(
                "snapshot_changed",
                "Account observations changed during evaluation; refresh and rerun",
                409,
                "scenario.expected_snapshot_id",
            )
        return result
    except asyncio.CancelledError:
        stopped.set()
        worker.add_done_callback(consume)
        raise
    except ValueError as exc:
        message = str(exc)
        if message.startswith("optimizer_busy"):
            raise error(
                "optimizer_busy", "Another equipment calculation is running; retry shortly", 503
            ) from exc
        if message.startswith("evaluation_cancelled"):
            raise error("evaluation_cancelled", "Evaluation cancelled", 499) from exc
        raise error("invalid_request", message) from exc
