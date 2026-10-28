"""Measure ordinary Gear coverage on one read-only frozen account image.

Run with ``python -m tools.measure_gear_coverage``. Each output directory contains
the complete audit plus local comparison evidence. Timings are observational;
catalog definitions in these artifacts are evidence, never a runtime data source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from tools.audit_gear_equipment import aware_time, code_identity, frozen_database
from tools.gear_audit_report import render_markdown
from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content, load_content
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.estimation.prices import PriceRecord
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.coverage_audit import as_of_prices, audit_snapshot, default_requests
from tracker.gear.optimizer import OptimizationRequest, optimize

PHASE_1_IDS = frozenset(
    {882, 886, 1387, 1077, 1125, 1165, 1201, 857, 1017, 2579, 3753, 3755, 6809, 10564, 10589, 21643}
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _measure_request(
    snapshot: AccountSnapshot,
    content: Content,
    catalog: EquipmentCatalog,
    prices: Mapping[int, PriceRecord],
    at: datetime,
    request: OptimizationRequest,
    repeats: int,
) -> dict[str, Any]:
    reference = optimize(snapshot, request, catalog, content, prices, at)
    identity = fingerprint(reference)
    seconds = []
    for _ in range(repeats):
        started = perf_counter()
        result = optimize(snapshot, request, catalog, content, prices, at)
        seconds.append(perf_counter() - started)
        if fingerprint(result) != identity:
            raise ValueError("Frozen optimizer produced nondeterministic responses")
    return {
        "request": request.model_dump(mode="json"),
        "warmup_runs": 1,
        "seconds": seconds,
        "median_seconds": statistics.median(seconds),
        "min_seconds": min(seconds),
        "max_seconds": max(seconds),
        "deterministic": True,
        "response_sha256": identity,
        "response": reference,
    }


def measure_snapshot(
    snapshot: AccountSnapshot,
    content: Content,
    catalog: EquipmentCatalog,
    prices: Mapping[int, PriceRecord],
    at: datetime,
    repeats: int = 5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use identical ordinary owned requests for audit and timed full optimization."""
    if repeats < 1 or isinstance(repeats, bool):
        raise ValueError("repeats must be positive")
    if at.tzinfo is None:
        raise ValueError("Evaluation time requires a timezone")
    requests = default_requests()
    historical = as_of_prices(prices, at)
    audit = audit_snapshot(snapshot, content, catalog, prices, at, requests)
    identity = {
        **code_identity(content),
        "measurement_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    audit["provenance"] = identity
    price_facts = {
        str(key): {
            k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(value).items()
        }
        for key, value in historical.items()
    }
    measurement = {
        "schema_version": 1,
        "snapshot_id": snapshot.fingerprint,
        "evaluated_at": at.isoformat(),
        "player_id": snapshot.player_id,
        "frozen_database_sha256": None,
        "catalog_revision": catalog.revision,
        "provenance": identity,
        "requests": [request.model_dump(mode="json") for request in requests],
        "prices_sha256": fingerprint(price_facts),
        "price_policy": audit["price_policy"],
        "current_account_summary": audit["current_account_summary"],
        "catalog_summary": audit["catalog_summary"],
        "scenarios": audit["scenarios"],
        "catalog_definitions": {
            str(key): item.model_dump(mode="json") for key, item in sorted(catalog.items.items())
        },
        "authored_items": {
            key: {"item_id": item.item_id, "sha256": fingerprint(item.model_dump(mode="json"))}
            for key, item in sorted(content.items.items())
        },
        "runs": [
            _measure_request(snapshot, content, catalog, historical, at, request, repeats)
            for request in requests
        ],
    }
    return audit, measurement


def measure_database(
    path: Path, player_id: int, at: datetime, repeats: int = 5
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read account and prices once from the same WAL-aware in-memory image."""
    if player_id < 1:
        raise ValueError("player_id must be positive")
    content = load_content()
    catalog = load_catalog(content)
    with frozen_database(path) as (sessions, image_hash):
        snapshot = AccountService(sessions).get_snapshot(player_id)
        prices = DatabaseGearPrices(sessions).get_prices()
        audit, measurement = measure_snapshot(snapshot, content, catalog, prices, at, repeats)
    provenance = {
        **audit["provenance"],
        "source_kind": "local_database_snapshot",
        "frozen_database_sha256": image_hash,
        "player_id": player_id,
        "measurement_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "container_scans": {
            key.value: {"scanned_at": value.scanned_at.isoformat(), "source": value.source}
            for key, value in sorted(snapshot.container_scans.items(), key=lambda p: p[0].value)
        },
        "history_limit": "Current persisted facts only; not historical catalog or price replay.",
    }
    return (
        {**audit, "provenance": provenance},
        {**measurement, "provenance": provenance, "frozen_database_sha256": image_hash},
    )


def _changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))


def _count_deltas(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: {"before": before[key], "after": value, "delta": value - before[key]}
        for key, value in after.items()
        if type(value) is int and type(before.get(key)) is int
    }


def compare_measurements(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Refuse drift in frozen inputs; expose any changes outside the review allowlist."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("Comparison requires measurement objects")
    for field in (
        "snapshot_id",
        "frozen_database_sha256",
        "evaluated_at",
        "player_id",
        "requests",
        "prices_sha256",
        "price_policy",
    ):
        if field not in before or field not in after:
            raise ValueError(f"Comparison field missing: {field}")
        if before[field] != after[field]:
            raise ValueError(f"Comparison input changed: {field}")
    for state in (before, after):
        if any(
            not isinstance(state.get(field), dict)
            for field in (
                "provenance",
                "catalog_definitions",
                "authored_items",
                "current_account_summary",
                "catalog_summary",
            )
        ) or not isinstance(state.get("runs"), list):
            raise ValueError("Comparison measurement structure is incomplete")
        if not isinstance(state["provenance"].get("source_file_sha256"), dict):
            raise ValueError("Comparison measurement source provenance is incomplete")
    if before["provenance"]["source_file_sha256"] != after["provenance"]["source_file_sha256"]:
        raise ValueError("Comparison input changed: pipeline source files")
    if not before["provenance"].get("measurement_source_sha256") or before["provenance"][
        "measurement_source_sha256"
    ] != after["provenance"].get("measurement_source_sha256"):
        raise ValueError("Comparison input changed: measurement source")
    changed = sorted(
        int(key) for key in _changed(before["catalog_definitions"], after["catalog_definitions"])
    )
    authored = _changed(before["authored_items"], after["authored_items"])
    unexpected_authored = [
        key
        for key in authored
        if any(
            state[key]["item_id"] not in PHASE_1_IDS
            for state in (before["authored_items"], after["authored_items"])
            if key in state
        )
    ]
    return {
        "changed_catalog_ids": changed,
        "unexpected_catalog_ids": sorted(set(changed) - PHASE_1_IDS),
        "changed_authored_ids": authored,
        "unexpected_authored_ids": unexpected_authored,
        "current_account": _count_deltas(
            before["current_account_summary"], after["current_account_summary"]
        ),
        "catalog": _count_deltas(before["catalog_summary"], after["catalog_summary"]),
        "runtime": [
            {
                "role": new["request"]["roles"][0]["id"],
                "before_median_seconds": old["median_seconds"],
                "after_median_seconds": new["median_seconds"],
                "ratio": new["median_seconds"] / old["median_seconds"]
                if old["median_seconds"]
                else None,
            }
            for old, new in zip(before["runs"], after["runs"], strict=True)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--player-id", type=int, required=True)
    parser.add_argument("--at", type=aware_time, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if args.player_id < 1 or args.repeats < 1:
        parser.error("--player-id and --repeats must be positive")
    inputs = {p.resolve() for p in (args.database, args.compare) if p}
    outputs = {
        name: args.output_dir / name for name in ("audit.json", "audit.md", "measurement.json")
    }
    if any(p.resolve() in inputs for p in outputs.values()):
        parser.error("Output must not overwrite an input")
    try:
        prior = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
        audit, measurement = measure_database(args.database, args.player_id, args.at, args.repeats)
        if prior is not None:
            measurement = {**measurement, "comparison": compare_measurements(prior, measurement)}
        rendered = {
            "audit.json": json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n",
            "audit.md": render_markdown(audit),
            "measurement.json": json.dumps(measurement, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, text in rendered.items():
            outputs[name].write_text(text, encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Measurement failed: {exc}\n")
    except SQLAlchemyError as exc:
        parser.exit(
            1,
            f"Measurement failed: database schema/data could not be read ({type(exc).__name__})\n",
        )
    print(json.dumps({name: str(path) for name, path in outputs.items()}))


if __name__ == "__main__":
    main()
