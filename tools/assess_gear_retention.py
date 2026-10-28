"""Offline research runner; never imported by the production optimizer.

Run from a separate CLI process. Experimental patching is serial and scoped to
that process. Raw account evidence belongs in ignored .tmp directories.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

STRATEGIES = ("baseline", "all", "pareto", "diversity", "shared", "refinement", "targeted")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def semantic_response(response: dict[str, Any]) -> dict[str, Any]:
    """Exclude only the two explicitly measured wall-clock fields from equality."""
    result = copy.deepcopy(response)
    result.get("research", {}).pop("refinement_duration_seconds", None)
    result.get("search", {}).get("targeted_head_refinement", {}).pop("duration_seconds", None)
    return result


def _refinement_seconds(response: dict[str, Any]) -> float:
    targeted = response.get("search", {}).get("targeted_head_refinement")
    if targeted is not None:
        return float(targeted["duration_seconds"])
    return float(response.get("research", {}).get("refinement_duration_seconds", 0.0))


def compare(response: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    """Positive gap means damage missed; feasibility is compared separately."""
    gaps = []
    feasibility = []
    details: list[dict[str, Any] | None] = []
    for actual, expected in zip(response["curve"], oracle["curve"], strict=True):
        solution = actual["solution"]
        score = expected["score"]
        feasibility.append((solution is not None) == (score is not None))
        gaps.append(None if solution is None or score is None else score - solution["score"])
        if solution is not None and score is not None and "loadouts" in expected:
            details.append(
                {
                    "same_equipment": {r: v["equipment"] for r, v in solution["loadouts"].items()}
                    == expected["loadouts"],
                    "max_hits": {
                        r: v["performance"].get("max_hit") for r, v in solution["loadouts"].items()
                    },
                    "oracle_max_hits": expected["max_hits"],
                    "metric_deltas": {
                        k: solution[k] - expected[k]
                        for k in ("purchase_cost_gp", "maximum_actions", "max_gear_inventory_slots")
                    },
                    "same_carried_union": solution["carried_item_ids"]
                    == expected["carried_item_ids"],
                    "same_purchase_union": sorted(p["item_id"] for p in solution["purchases"])
                    == expected["purchased_item_ids"],
                }
            )
        else:
            details.append(None)
    actual, expected = response["unrestricted"], oracle["unrestricted"]
    return {
        "score_gaps": gaps,
        "feasibility_matches": feasibility,
        "curve_details": details,
        "unrestricted_gap": expected["score"] - actual["score"]
        if actual is not None and expected is not None
        else None,
    }


def measure(
    case: Any, strategy: str, repeats: int, runner: Callable[..., Any] | None = None
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if runner is None:
        from tools.gear_retention_strategies import run

        runner = run
    reference = runner(case, strategy)
    fingerprint = digest(semantic_response(reference))
    seconds = []
    refinement_seconds = []
    for _ in range(repeats):
        started = perf_counter()
        result = runner(case, strategy)
        seconds.append(perf_counter() - started)
        refinement_seconds.append(_refinement_seconds(result))
        if digest(semantic_response(result)) != fingerprint:
            raise ValueError("Frozen research run produced nondeterministic responses")
    return {
        "warmup_runs": 1,
        "seconds": seconds,
        "median_seconds": statistics.median(seconds),
        "min_seconds": min(seconds),
        "max_seconds": max(seconds),
        "refinement_seconds": refinement_seconds,
        "median_refinement_seconds": statistics.median(refinement_seconds),
        "min_refinement_seconds": min(refinement_seconds),
        "max_refinement_seconds": max(refinement_seconds),
        "response_sha256": fingerprint,
        "response_sha256_excludes": [
            "research.refinement_duration_seconds",
            "search.targeted_head_refinement.duration_seconds",
        ],
        "response": reference,
    }


def account_cases(database: Path, player_id: int, at: datetime) -> tuple[list[Any], dict[str, Any]]:
    from tools.audit_gear_equipment import frozen_database
    from tools.gear_retention_oracle import Case
    from tracker.accounts.service import AccountService
    from tracker.content.loader import load_content
    from tracker.db.gear_prices import DatabaseGearPrices
    from tracker.gear.catalog import load_catalog
    from tracker.gear.coverage_audit import as_of_prices, audit_snapshot, default_requests

    if player_id < 1 or at.tzinfo is None:
        raise ValueError("positive player ID and timezone-aware evaluation time required")
    content = load_content()
    catalog = load_catalog(content)
    paths = [database, Path(str(database) + "-wal")]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}
    with frozen_database(database) as (sessions, image_hash):
        snapshot = AccountService(sessions).get_snapshot(player_id)
        prices = as_of_prices(DatabaseGearPrices(sessions).get_prices(), at)
        audit = audit_snapshot(snapshot, content, catalog, prices, at, default_requests())
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}
    if before != after:
        raise ValueError("source database/WAL changed during frozen capture")
    omitted = [
        {
            "item_id": row["item_id"],
            "roles": [
                role["role_id"]
                for role in row["scenario_results"]
                if role["initial_eligible"] and role["candidate_retention"] == "omitted"
            ],
        }
        for row in audit["items"]
        if any(
            r["initial_eligible"] and r["candidate_retention"] == "omitted"
            for r in row["scenario_results"]
        )
    ]
    cases = [
        Case(f"account-{r.roles[0].id}", snapshot, r, catalog, content, prices, at)
        for r in default_requests()
    ]
    return cases, {
        "source_hashes": before,
        "source_unchanged_after_capture": True,
        "frozen_database_sha256": image_hash,
        "snapshot_id": snapshot.fingerprint,
        "prices_sha256": digest(
            {
                str(k): {
                    key: value.isoformat() if isinstance(value, datetime) else value
                    for key, value in asdict(v).items()
                }
                for k, v in prices.items()
            }
        ),
        "omitted": omitted,
    }


def provenance() -> dict[str, Any]:
    paths = [
        *Path("tracker/gear").glob("*.py"),
        *Path("tools").glob("*retention*.py"),
        Path("content/equipment/catalog.json"),
        Path("content/equipment/manifest.json"),
        *Path("content/items").glob("*.yaml"),
    ]
    return {
        str(p).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tiny", action="store_true")
    source.add_argument("--database", type=Path)
    parser.add_argument("--player-id", type=int, default=1)
    parser.add_argument("--at", default="2026-10-19T22:05:44+00:00")
    parser.add_argument("--case", action="append")
    parser.add_argument("--strategy", choices=STRATEGIES, action="append")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.output.exists():
        raise FileExistsError(args.output)
    from tools.gear_retention_oracle import exhaustive, tiny_cases, validate_solution

    if args.tiny:
        cases, identity = tiny_cases(), {"source": "synthetic tiny catalogs"}
    else:
        cases, identity = account_cases(
            args.database, args.player_id, datetime.fromisoformat(args.at)
        )
    if args.case:
        known = {c.name for c in cases}
        if set(args.case) - known:
            parser.error(f"unknown case: {sorted(set(args.case) - known)}")
        cases = [c for c in cases if c.name in args.case]
    started = perf_counter()
    hashes = provenance()
    rows = []
    for case in cases:
        oracle = exhaustive(case) if args.tiny else None
        runs = {}
        for strategy in args.strategy or STRATEGIES:
            result = measure(case, strategy, args.repeats)
            if oracle is not None:
                result["comparison"] = compare(result["response"], oracle)
                checks = []
                for point in result["response"]["curve"]:
                    solution = point["solution"]
                    if solution is not None:
                        check = validate_solution(case, solution)
                        if check["metrics"].get("maximum_actions", 0) > point["swap_limit"]:
                            raise ValueError("action-limit violation")
                        checks.append(check)
                if result["response"]["unrestricted"] is not None:
                    checks.append(validate_solution(case, result["response"]["unrestricted"]))
                if any(not c["valid"] for c in checks):
                    raise ValueError(f"independent solution validation failed: {checks}")
                result["independent_validation"] = checks
            runs[strategy] = result
            print(f"{case.name}/{strategy}: {result['median_seconds']:.4f}s", flush=True)
        rows.append(
            {
                "name": case.name,
                "request": case.request.model_dump(mode="json"),
                "catalog": {
                    str(i): v.model_dump(mode="json") for i, v in sorted(case.catalog.items.items())
                },
                "oracle": oracle,
                "runs": runs,
            }
        )
    if hashes != provenance():
        raise ValueError("research/production/content files changed during measurement")
    result = {
        "schema_version": 1,
        "identity": identity,
        "source_sha256": hashes,
        "elapsed_seconds": perf_counter() - started,
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
