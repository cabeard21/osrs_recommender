"""Benchmark the frozen joint case through the desktop FastAPI route and archive publisher.

First use tools.benchmark_native_hot_loops freeze. Run this module in both the reference
and candidate checkouts with the same frozen JSON, worker count, and release builds.
The clock and input source are frozen. The in-process HTTP client measures the real
route including request validation, baseline projection, archive publication, and JSON.
Use --save-raw to also fingerprint full unsampled groups after the first timed response.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tools.benchmark_gear_desktop import load_frozen_case
from tools.benchmark_native_hot_loops import (
    complete_digest,
    desktop_service,
    digest,
    frontier_digest,
    write_json,
)
from tracker.api import gear_optimizations as route
from tracker.gear import objective_store
from tracker.gear.discipline_assignments import branch_requests


def lane_observations(search: dict[str, Any], assignments: Iterable[str]) -> list[dict[str, Any]]:
    profiles = search.get("potion_selection", {}).get("profiles", [])
    if not profiles:
        return []
    branches = search.get("discipline_assignment_selection", {}).get("branches", {})
    if branches:
        # Production appends each assignment's fixed potion lanes in branch order.
        names = [
            name
            for name in assignments
            for _ in range(branches[name]["potion_selection"]["branch_count"])
        ]
    else:
        names = [row["discipline"] for row in profiles]
    return [
        {
            "lane": lane,
            "assignment": assignment,
            "selected_ids": row["selected_ids"],
            "seconds": row["search"].get("timings_seconds", {}),
            "objective_frontier": row["search"].get("objective_frontier", {}),
        }
        for lane, (assignment, row) in enumerate(zip(names, profiles, strict=True))
    ]


@contextmanager
def heartbeat(service: Any, identity: str) -> Iterator[None]:
    cutoff = Event()
    fields = ("elapsed_seconds", "phase", "completed", "total", "fraction", "lanes")

    def report() -> None:
        while not cutoff.wait(30):
            progress = service.optimization_progress(identity) or {}
            print(json.dumps({key: progress.get(key) for key in fields}), flush=True)

    reporter = Thread(target=report, daemon=True)
    reporter.start()
    try:
        yield
    finally:
        cutoff.set()
        reporter.join()


def timed_request(case: Any, mode: str, service: Any, save_raw: bool) -> tuple[dict, dict, dict]:
    identity = str(uuid4())
    phases = {}
    raw_result = {}
    optimize = service.optimize
    close_archives = objective_store.close_result_archives
    publish = service.objective_store.publish_result

    def timed_publish(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        stored = publish(*args, **kwargs)
        phases["archive_publication"] = perf_counter() - started
        return stored

    def timed_optimize(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        result = optimize(*args, **kwargs)
        phases.update(result["search"].get("timings_seconds", {}))
        phases["optimizer"] = perf_counter() - started
        if save_raw:
            raw_result.update(result)
        return result

    def close_after_digest(payload: Any) -> None:
        # The route wraps the result but shares its exact final archive groups. Keep
        # those alive until the HTTP timer stops. Branch and temporary cleanup still runs.
        if (
            raw_result
            and isinstance(payload, Mapping)
            and payload.get("objective_frontiers") is raw_result["objective_frontiers"]
        ):
            return
        close_archives(payload)

    app = FastAPI()
    app.include_router(route.router)
    app.state.gear_service = service
    app.state.gear_data_source = SimpleNamespace(load=lambda: (case.snapshot, case.prices))
    body = {**case.request.model_dump(mode="json"), "optimization_mode": mode}
    frozen_clock = SimpleNamespace(now=case.at.astimezone)
    try:
        with (
            heartbeat(service, identity),
            TestClient(app) as client,
            patch.object(route, "datetime", frozen_clock),
            patch.object(service, "optimize", timed_optimize),
            patch.object(service.objective_store, "publish_result", timed_publish),
            patch.object(objective_store, "close_result_archives", close_after_digest),
        ):
            started = perf_counter()
            reply = client.post(f"/ui-api/gear/optimizations?progress_id={identity}", json=body)
            phases["service"] = perf_counter() - started
            reply.raise_for_status()
        return phases, reply.json()["result"], frontier_digest(raw_result) if save_raw else {}
    finally:
        close_archives(raw_result)


def observe(
    case: Any,
    provenance: dict[str, Any],
    service: Any,
    build_hash: str,
    workers: int,
    output: Path,
    raw_output: Path | None,
) -> None:
    phases, result, raw = timed_request(
        case, provenance["optimization_mode"], service, raw_output is not None
    )
    if raw_output is not None:
        write_json(raw_output, {"inputs_sha256": provenance["inputs_sha256"], "raw": raw})
    phases["response_and_publication"] = phases["service"] - phases["optimizer"]
    print(json.dumps(phases), flush=True)
    write_json(
        output,
        {
            "inputs_sha256": provenance["inputs_sha256"],
            "native_build_sha256": build_hash,
            "workers": workers,
            "memory": None,
            "seconds": phases,
            "lanes": lane_observations(
                result["search"], (name for name, _ in branch_requests(case.request))
            ),
            "native": service.native_diagnostics,
            "published": frontier_digest(result),
            "full_archive": complete_digest(service.objective_store, result["run_id"]),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--observations", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--save-raw", action="store_true")
    args = parser.parse_args()
    if args.observations < 1 or not 1 <= args.workers <= 6:
        parser.error("Use positive observations and one to six desktop workers")
    raw_output = args.output / "raw.json" if args.save_raw else None
    outputs = [args.output / f"{number}.json" for number in range(args.observations)]
    if any(path.exists() for path in outputs) or (raw_output and raw_output.exists()):
        parser.error("Observation output already exists")
    case, provenance = load_frozen_case(args.frozen)
    with desktop_service(case, args.workers) as (service, build):
        try:
            for number, output in enumerate(outputs):
                observe(
                    case,
                    provenance,
                    service,
                    digest(build),
                    args.workers,
                    output,
                    raw_output if number == 0 else None,
                )
        finally:
            service.close_objective_store()


if __name__ == "__main__":
    main()
