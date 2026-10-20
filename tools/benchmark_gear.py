"""Profile a frozen Gear request without writes, refreshes, or network access.

Run from the repository root with Python's ``-m tools.benchmark_gear``. Inputs and
full responses can contain private account data; keep output in ignored .tmp/.
Stage timers are disjoint: fingerprint time is deducted from candidate/search time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import load_content
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.db.models import Player
from tracker.gear import optimizer
from tracker.gear.facts import equipment_fact
from tracker.gear.service import GearService


def benchmark(database: Path, request_path: Path, at: datetime, repeats: int) -> dict[str, Any]:
    engine = create_engine(f"sqlite:///file:{database.resolve().as_posix()}?mode=ro&uri=true")
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        player_id = session.scalar(select(Player.id).order_by(Player.id))
    if player_id is None:
        raise ValueError("Frozen database has no account")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    service = GearService(load_content())
    started = perf_counter()
    catalog = service.equipment_catalog()
    catalog_seconds = perf_counter() - started
    runs: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    for _ in range(repeats):
        timings: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        original_fingerprint = vars(AccountSnapshot)["fingerprint"].fget

        def measured(name, function, timings=timings, counts=counts):
            def wrapped(*args, **kwargs):
                started = perf_counter()
                fingerprint_before = timings["fingerprint"]
                try:
                    return function(*args, **kwargs)
                finally:
                    elapsed = perf_counter() - started
                    if name != "fingerprint":
                        elapsed -= timings["fingerprint"] - fingerprint_before
                    timings[name] += elapsed
                    counts[name] += 1

            return wrapped

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    AccountSnapshot,
                    "fingerprint",
                    property(measured("fingerprint", original_fingerprint)),
                )
            )
            stack.enter_context(
                patch.object(
                    optimizer,
                    "equipment_fact",
                    measured("candidate_facts", equipment_fact),
                )
            )
            stack.enter_context(
                patch.object(
                    optimizer._Search,
                    "candidate_pools",
                    measured("candidate_pools", optimizer._Search.candidate_pools),
                )
            )
            started = perf_counter()
            snapshot = AccountService(sessions).get_snapshot(player_id)
            timings["snapshot_construction"] = perf_counter() - started
            started = perf_counter()
            prices = DatabaseGearPrices(sessions).get_prices()
            timings["price_read"] = perf_counter() - started
            snapshot_id = snapshot.fingerprint
            fingerprint_before_search = timings["fingerprint"]

            def cancelled(account: AccountSnapshot = snapshot, expected: str = snapshot_id) -> bool:
                return account.fingerprint != expected

            started = perf_counter()
            # Deliberately reproduce the original UI callback in both versions.
            # This isolates immutable fingerprint reuse from callback capture changes.
            answer = service.optimize(
                snapshot,
                request,
                price_records=prices,
                now=at,
                cancelled=cancelled,
            )
            timings["optimization_total"] = perf_counter() - started
            timings["candidate_generation"] = (
                timings["candidate_facts"] + timings["candidate_pools"]
            )
            timings["search_and_response"] = (
                timings["optimization_total"]
                - timings["candidate_generation"]
                - (timings["fingerprint"] - fingerprint_before_search)
            )
            # NiceGUI construction measured independently from browser delivery/paint.
            from nicegui.client import Client
            from nicegui.page import page

            from tracker.ui.gear import _optimizer_results

            client = Client(page("/gear-benchmark"))
            try:
                started = perf_counter()
                with client:
                    _optimizer_results(
                        answer, {i: {"name": item.name} for i, item in catalog.items.items()}
                    )
                timings["nicegui_result_construction"] = perf_counter() - started
                counts["nicegui_elements"] = len(client.elements)
            finally:
                client.delete()
        canonical = json.dumps(answer, sort_keys=True, separators=(",", ":"))
        answers.append(answer)
        runs.append(
            {
                "seconds": dict(timings),
                "counts": dict(counts),
                "response_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            }
        )
    engine.dispose()
    if any(answer != answers[0] for answer in answers):
        raise AssertionError("Frozen request produced different results")
    return {
        "catalog_load_seconds": catalog_seconds,
        "evaluated_at": at.isoformat(),
        "snapshot_id": answers[0]["snapshot_id"],
        "runs": runs,
        "median_seconds": {
            key: statistics.median(run["seconds"][key] for run in runs)
            for key in runs[0]["seconds"]
        },
        "response": answers[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")
    result = benchmark(args.database, args.request, args.at, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "response"}, indent=2))


if __name__ == "__main__":
    main()
