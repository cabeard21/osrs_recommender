"""Bounded read-only potion decay measurements for selected configurations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from threading import Event
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator

from tracker.api.gear_evaluations import FixedCombatOption
from tracker.api.gear_optimizations import (
    BrowserOptimizationRequest,
    consume,
    error,
    same_origin,
    validate_scenario,
)
from tracker.api.gear_ui import DTO, GearRoute, no_cache, resources
from tracker.content.schema import ItemSlot
from tracker.gear.combat import MODEL_VERSION
from tracker.gear.optimizer import ItemId
from tracker.gear.potions import PotionPolicy
from tracker.gear.prayers import PrayerPolicy

router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


class TimelineLoadout(DTO):
    equipment: dict[ItemSlot, ItemId]
    combat_option: FixedCombatOption
    selected_prayer_ids: tuple[str, ...] = ()


class PotionTimelineRequest(DTO):
    scenario: BrowserOptimizationRequest
    selected_potion_ids: tuple[str, ...] = Field(max_length=16)
    loadouts: dict[str, TimelineLoadout]
    expected_catalog_version: str = Field(min_length=1, max_length=128)
    expected_model_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def fixed_selection(self):
        PotionPolicy(mode="fixed", selected_ids=self.selected_potion_ids)
        policy = self.scenario.potions
        if policy.mode == "optimize":
            if not set(self.selected_potion_ids) <= set(policy.allowed_ids):
                raise ValueError("Selected potions must belong to the scenario allowlist")
        elif set(self.selected_potion_ids) != set(policy.selected_ids):
            raise ValueError("Selected potions must match the scenario setup")
        ordinary = {r.id for r in self.scenario.roles if r.style != "special"}
        if set(self.loadouts) != ordinary:
            raise ValueError("Loadouts must contain exactly the scored ordinary roles")
        for role in self.scenario.roles:
            if role.id not in ordinary:
                continue
            ids = self.loadouts[role.id].selected_prayer_ids
            PrayerPolicy(mode="fixed", selected_ids=ids)
            if role.prayers.mode == "optimize":
                if not set(ids) <= set(role.prayers.allowed_ids):
                    raise ValueError("Selected prayers must belong to the scenario allowlist")
            elif set(ids) != set(role.prayers.selected_ids):
                raise ValueError("Selected prayers must match the scenario setup")
        return self


class RoleMeasurement(DTO):
    dps: float | None
    secondary_value: float | None
    reasons: list[str]


class TimelineMeasurement(DTO):
    time_seconds: int
    levels: dict[str, int]
    dps: float | None
    secondary_value: float | None
    roles: dict[str, RoleMeasurement]


class PotionTimelineResponse(DTO):
    snapshot_id: str
    catalog_version: str
    model_version: str
    decay_model_version: Literal["potion-decay-v1"] = "potion-decay-v1"
    configuration_fingerprint: str
    secondary_priority: str
    baseline: TimelineMeasurement
    samples: list[TimelineMeasurement]


def calculate_timeline(snapshot, gear, prices, body: PotionTimelineRequest, stopped: Event):
    from tracker.gear.combat_options import CombatOption
    from tracker.gear.evaluation import (
        evaluate_configurations,
        resolve_bolt_context,
        resolve_tome_context,
    )
    from tracker.gear.facts import hypothetical_snapshot
    from tracker.gear.npcs import resolve_request
    from tracker.gear.potion_timeline import decay_levels, event_times, measure
    from tracker.gear.scoring import prepare_equipment
    from tracker.gear.support import project_catalog

    if not gear._optimization_lock.acquire(blocking=False):
        raise ValueError("optimizer_busy")
    try:
        now = datetime.now(UTC)
        catalog = gear.equipment_catalog()
        if (
            catalog.revision != body.expected_catalog_version
            or MODEL_VERSION != body.expected_model_version
        ):
            raise error("model_changed", "Combat model or catalog changed; rerun optimization", 409)
        validate_scenario(body.scenario, gear, snapshot)
        request = resolve_request(
            body.scenario.model_copy(
                update={
                    "potions": PotionPolicy(mode="fixed", selected_ids=body.selected_potion_ids)
                }
            )
        )
        projected = hypothetical_snapshot(
            snapshot, request.skill_overrides, request.quest_overrides, now
        )
        base = {k: v.level for k, v in projected.skills.items()}
        items = project_catalog(catalog, request.support_policy).items
        roles, prepared = [], {}
        for role in request.roles:
            if role.style == "special":
                continue
            row = body.loadouts[role.id]
            role = role.model_copy(
                update={
                    "prayers": PrayerPolicy(mode="fixed", selected_ids=row.selected_prayer_ids),
                    "active_prayer_ids": row.selected_prayer_ids,
                }
            )
            single = request.model_copy(
                update={
                    "roles": (role,),
                    "transitions": (),
                    "ordered_roles": (),
                    "loop": False,
                    "base_role": role.id,
                }
            )
            selected = row.combat_option.model_dump()
            equipment: dict[str, int] = dict(row.equipment.items())
            checked = evaluate_configurations(
                snapshot,
                single,
                equipment,
                equipment,
                catalog,
                gear.content,
                prices,
                now,
                baseline_combat_option=selected,
                proposed_combat_option=selected,
            )["proposed"]
            if checked["status"] != "valid":
                raise ValueError(
                    "Invalid selected configuration: "
                    + "; ".join(r["message"] for r in checked["reasons"])
                )
            option = CombatOption(**selected)
            configured = resolve_tome_context(
                resolve_bolt_context(role, snapshot), request.fire_tome_pages
            ).model_copy(
                update={
                    "style": option.style,
                    "stance": option.stance,
                    "spell": option.spell or role.spell,
                    "powered_attack": option.powered_attack,
                    "allowed_disciplines": None,
                    "combat_options": None,
                }
            )
            roles.append(configured)
            prepared[role.id] = prepare_equipment(
                {slot: items[i] for slot, i in row.equipment.items()}
            )

        measurements = {}

        def at(seconds, levels):
            if stopped.is_set():
                raise ValueError("evaluation_cancelled")
            effective = (
                {**levels, "_base_magic": base.get("magic", 0)}
                if levels.get("magic") != base.get("magic")
                else levels
            )
            key = tuple(sorted(effective.items()))
            if key not in measurements:
                measurements[key] = measure(
                    0, effective, roles, prepared, request.secondary_priority
                )
            return {**measurements[key], "time_seconds": seconds}

        return PotionTimelineResponse(
            snapshot_id=snapshot.fingerprint,
            catalog_version=catalog.revision,
            model_version=MODEL_VERSION,
            configuration_fingerprint=hashlib.sha256(
                json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest(),
            secondary_priority=request.secondary_priority,
            baseline=at(0, base),
            samples=[
                at(t, decay_levels(base, body.selected_potion_ids, t))
                for t in event_times(base, body.selected_potion_ids)
            ],
        )
    finally:
        gear._optimization_lock.release()


@router.post("/potion-timelines", response_model=PotionTimelineResponse)
async def potion_timelines(request: Request, body: PotionTimelineRequest):
    same_origin(request)
    snapshot, gear, prices = await asyncio.to_thread(resources, request)
    if snapshot is None or snapshot.fingerprint != body.scenario.expected_snapshot_id:
        raise error("snapshot_changed", "Refresh account facts and rerun optimization", 409)
    stopped = Event()
    worker = asyncio.create_task(
        asyncio.to_thread(calculate_timeline, snapshot, gear, prices, body, stopped)
    )
    try:
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.05)
            if await request.is_disconnected():
                stopped.set()
                worker.add_done_callback(consume)
                raise error("evaluation_cancelled", "Timeline cancelled", 499)
        result = worker.result()
        fresh, _, _ = await asyncio.to_thread(resources, request)
        if fresh is None or fresh.fingerprint != snapshot.fingerprint:
            raise error(
                "snapshot_changed", "Account changed during evaluation; rerun optimization", 409
            )
        return result
    except asyncio.CancelledError:
        stopped.set()
        worker.add_done_callback(consume)
        raise
    except ValueError as exc:
        if str(exc).startswith("optimizer_busy"):
            raise error(
                "optimizer_busy", "Another equipment calculation is running; retry shortly", 503
            ) from exc
        if str(exc).startswith("evaluation_cancelled"):
            raise error("evaluation_cancelled", "Timeline cancelled", 499) from exc
        raise error("invalid_request", str(exc)) from exc
