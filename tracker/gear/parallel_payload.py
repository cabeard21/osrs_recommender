"""Detached, validated facts for local spawned Gear workers; no database access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.errors import ContentLocation
from tracker.content.loader import Content
from tracker.content.schema import Item, Quest, Skill
from tracker.estimation.prices import PriceRecord
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.data_source import AccountFacts
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _catalog_payload(catalog: EquipmentCatalog) -> dict[str, Any]:
    return {
        "items": {i: item.model_dump(mode="json") for i, item in catalog.items.items()},
        "revision": catalog.revision,
        "community_items": dict(catalog.community_items),
        "community_provenance": catalog.community_provenance,
        "community_assumptions": dict(catalog.community_assumptions),
        "verified_catalog": _catalog_payload(catalog.verified_catalog)
        if catalog.verified_catalog is not None
        else None,
    }


def _catalog(data: dict[str, Any]) -> EquipmentCatalog:
    return EquipmentCatalog(
        items={
            int(i): EquipmentDefinition.model_validate(item) for i, item in data["items"].items()
        },
        revision=data["revision"],
        community_items={int(i): row for i, row in data["community_items"].items()},
        community_provenance=data["community_provenance"],
        community_assumptions={
            int(i): tuple(row) for i, row in data["community_assumptions"].items()
        },
        verified_catalog=_catalog(data["verified_catalog"]) if data["verified_catalog"] else None,
    )


def context_payload(content: Content, catalog: EquipmentCatalog) -> tuple[dict[str, Any], str]:
    payload: dict[str, Any] = {
        "content": {
            field: {
                key: model.model_dump(mode="json") for key, model in getattr(content, field).items()
            }
            for field in ("skills", "quests", "items")
        },
        "locations": [
            [kind, key, str(location.file) if location.file else None, location.line, location.path]
            for (kind, key), location in sorted(content.locations.items())
        ],
        "catalog": _catalog_payload(catalog),
    }
    for key, item in content.items.items():
        if item.requires is not None:
            payload["content"]["items"][key]["requires"] = item.requires.to_yaml()
    # JSON detaches nested community metadata too; no caller-owned maps cross IPC.
    detached = json.loads(json.dumps(payload, allow_nan=False))
    return detached, _digest(detached)


def decode_context(payload: dict[str, Any], identity: str) -> tuple[Content, EquipmentCatalog]:
    if _digest(payload) != identity:
        raise ValueError("optimizer_worker_context_mismatch")
    content = Content(
        skills={
            key: Skill.model_validate(value) for key, value in payload["content"]["skills"].items()
        },
        quests={
            key: Quest.model_validate(value) for key, value in payload["content"]["quests"].items()
        },
        items={
            key: Item.model_validate(value) for key, value in payload["content"]["items"].items()
        },
        locations={
            (kind, key): ContentLocation(Path(file) if file else None, line, path)
            for kind, key, file, line, path in payload["locations"]
        },
    )
    return content, _catalog(payload["catalog"])


@dataclass(frozen=True, slots=True)
class WorkerPrice:
    item_id: int
    high_price_gp: int | None
    high_trade_at: datetime | None
    low_price_gp: int | None
    low_trade_at: datetime | None
    fetched_at: datetime
    source: str
    provider: str


def job_payload(
    snapshot: AccountSnapshot,
    request: OptimizationRequest,
    prices: Mapping[int, PriceRecord],
    now: datetime,
    identity: str,
) -> dict[str, Any]:
    return {
        "context_id": identity,
        "snapshot_id": snapshot.fingerprint,
        "account": AccountFacts.from_snapshot(snapshot).model_dump(mode="json"),
        # BrowserOptimizationRequest adds transport-only fields such as mode;
        # workers reconstruct the authoritative base request, not the HTTP DTO.
        "request": request.model_dump(mode="json", include=set(OptimizationRequest.model_fields)),
        "at": now.isoformat(),
        "prices": {
            i: {
                field: getattr(record, field)
                for field in (
                    "item_id",
                    "high_price_gp",
                    "high_trade_at",
                    "low_price_gp",
                    "low_trade_at",
                    "fetched_at",
                    "source",
                )
            }
            | {"provider": getattr(record, "provider", "")}
            for i, record in prices.items()
        },
    }


def decode_job(
    payload: dict[str, Any],
    identity: str,
) -> tuple[AccountSnapshot, OptimizationRequest, dict[int, PriceRecord], datetime]:
    if payload["context_id"] != identity:
        raise ValueError("optimizer_worker_context_mismatch")
    snapshot = AccountFacts.model_validate(payload["account"]).snapshot()
    if snapshot.fingerprint != payload["snapshot_id"]:
        raise ValueError("optimizer_worker_fingerprint_mismatch")
    prices: dict[int, PriceRecord] = {
        int(i): WorkerPrice(**row) for i, row in payload["prices"].items()
    }
    if any(i != row.item_id for i, row in prices.items()):
        raise ValueError("optimizer_worker_price_mismatch")
    return (
        snapshot,
        OptimizationRequest.model_validate(payload["request"]),
        prices,
        datetime.fromisoformat(payload["at"]),
    )
