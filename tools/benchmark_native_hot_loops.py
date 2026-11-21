"""Freeze or replay a private desktop Gear handoff with the production worker pool."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
import zlib
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from pydantic import TypeAdapter

from tools.benchmark_gear_desktop import frozen_inputs, load_frozen_case, without_observations
from tools.gear_process_memory import measure_process_tree
from tools.gear_retention_oracle import Case
from tools.p5_experiment import RunSpec, execute
from tracker.db.gear_prices import CachedPriceRecord
from tracker.gear.native.readiness import require_native
from tracker.gear.objective_store import ObjectiveRunStore, close_result_archives


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as destination:
        json.dump(data, destination, default=str, sort_keys=True)


def price_revision(prices: dict[int, CachedPriceRecord]) -> str:
    records = {item_id: str(record) for item_id, record in sorted(prices.items())}
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def historical_prices(
    archived: dict[str, dict[str, str]],
    current: dict[int, CachedPriceRecord],
    revision: str,
) -> dict[int, CachedPriceRecord] | None:
    """Verify the saved optimizer price rows with the browser's complete input hash."""
    adapter = TypeAdapter(CachedPriceRecord)
    recovered = {
        int(key): adapter.validate_json(
            json.dumps(
                {
                    "item_id": int(key),
                    "provider": current[int(key)].provider,
                    **{field: None if value == "None" else value for field, value in row.items()},
                }
            )
        )
        for key, row in archived.items()
        if int(key) in current
    }
    return recovered if price_revision(recovered) == revision else None


def draft_request(draft: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Normalize an exported draft using the same TypeScript as the Optimize button."""
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "gear"
    run = subprocess.run(
        ["node", "scripts/benchmark-draft.mjs"],
        cwd=frontend,
        input=json.dumps({"draft": draft, "context": context}),
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode:
        raise ValueError(f"Browser draft normalization failed: {run.stderr.strip()}")
    return json.loads(run.stdout)


def attempt_request(data: dict[str, Any], snapshot_id: str) -> tuple[dict[str, Any], str] | None:
    attempt = data.get("attempt") or {}
    if attempt.get("status") not in {"running", "failed", "cancelled"}:
        return None
    original = attempt["request"]
    return {**original, "expected_snapshot_id": snapshot_id}, original["expected_snapshot_id"]


def freeze_fresh(
    data: dict[str, Any], output: Path, snapshot: Any, prices: Any, content: Any, gear: Any
) -> None:
    from tracker.api.gear_optimizations import BrowserOptimizationRequest, validate_scenario
    from tracker.api.gear_ui import combat_option_capabilities

    captured = attempt_request(data, snapshot.fingerprint)
    if captured is not None:
        request, original_id = captured
        provenance = {"account_input": "fresh_for_attempt", "original_snapshot_id": original_id}
    else:
        capabilities = {
            "combat_options": combat_option_capabilities(snapshot, gear),
            "potion_combat_options": combat_option_capabilities(snapshot, gear, potion_boost=True),
        }
        context = {
            "snapshotId": snapshot.fingerprint,
            "live": {"account": snapshot.summary(), "capabilities": capabilities},
        }
        request = draft_request(data["draft"], context)
        provenance = {"account_input": "fresh_for_draft"}
    scenario = BrowserOptimizationRequest.model_validate(request)
    validate_scenario(scenario, gear, snapshot)
    case = Case(
        "handoff", snapshot, scenario, gear.equipment_catalog(), content, prices, datetime.now(UTC)
    )
    write_json(
        output,
        {
            **frozen_inputs(case),
            "benchmark": {
                **provenance,
                "optimization_mode": scenario.optimization_mode,
                "price_input": "fresh",
                "price_revision": price_revision(prices),
            },
        },
    )


def freeze(handoff: Path, output: Path) -> None:
    from tracker.content.loader import load_content
    from tracker.gear.catalog import load_catalog
    from tracker.gear.data_source import RemoteGearDataSource
    from tracker.gear.optimizer import OptimizationRequest
    from tracker.gear_desktop import DesktopSettings

    data = json.loads(handoff.read_bytes())
    result = data["result"]
    settings = DesktopSettings()
    snapshot, prices = RemoteGearDataSource(
        settings.pi_url, settings.player_id, settings.read_token.get_secret_value()
    ).load()
    content = load_content(settings.content_dir)
    if snapshot is None:
        raise ValueError("A handoff capture requires a current account")
    if result is None or attempt_request(data, snapshot.fingerprint) is not None:
        from tracker.gear.service import GearService

        gear = GearService(content, equipment_root=settings.content_dir / "equipment")
        freeze_fresh(data, output, snapshot, prices, content, gear)
        return
    catalog = load_catalog(content)
    live = result["live"]
    if snapshot.fingerprint != result["snapshotId"] or catalog.revision != result["catalogVersion"]:
        raise ValueError("Current account and catalog must match the handoff")
    expected_revision = result["priceRevision"]
    if price_revision(prices) != expected_revision:
        archived = live["result"].get("assumptions", {}).get("running_cost_prices", {})
        restored = historical_prices(archived, prices, expected_revision)
        if restored is not None:
            prices = restored
    revision = price_revision(prices)
    historical = revision == expected_revision
    scenario = live["scenario"]
    request = OptimizationRequest.model_validate(
        {k: v for k, v in scenario.items() if k != "optimization_mode"}
    )
    evaluation_time = (
        datetime.fromisoformat(live["evaluated_at"]) if historical else datetime.now(UTC)
    )
    case = Case("handoff", snapshot, request, catalog, content, prices, evaluation_time)
    write_json(
        output,
        {
            **frozen_inputs(case),
            "benchmark": {
                "optimization_mode": scenario.get("optimization_mode", "fast"),
                "price_input": "historical" if historical else "fresh",
                "price_revision": revision,
            },
        },
    )


def freeze_merge(handoff: Path, store: Path, output: Path) -> None:
    """Recover the complete unfiltered input groups for this retained Auto run."""
    original = json.loads(handoff.read_bytes())["result"]["live"]
    run = original["result"]["run_id"]
    request = original["scenario"]
    capture_merge(
        store,
        run,
        request,
        original["result"]["search"]["discipline_selection"]["branches"],
        output,
    )


def capture_merge(
    store: Path, run: str, request: dict[str, Any], counts: dict[str, Any], output: Path
) -> None:
    if len(request["roles"]) != 1 or request["max_dps_loss_pct"] != 100:
        raise ValueError("Historical merge capture requires the single-role unfiltered run")
    with closing(sqlite3.connect(store.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        groups: dict[str, list[Any]] = {}
        for group_id, metadata in db.execute(
            "SELECT id, metadata FROM groups WHERE run=? ORDER BY id", (run,)
        ):
            group = json.loads(metadata)
            members = [
                identity
                for (identity,) in db.execute(
                    "SELECT solution FROM members WHERE run=? AND group_id=? ORDER BY solution",
                    (run, group_id),
                )
            ]
            if group["view"] != "global":
                branch = group["view"].removeprefix("discipline-")
                expected = counts[branch]["objective_frontier"]["archive_counts"]
                if len(members) != expected[str(group["swap_limit"])]:
                    raise ValueError("Retained branch is missing unfiltered members")
            groups.setdefault(group["view"], []).append(
                {
                    "cap": group["swap_limit"],
                    "baseline_dps": group["baseline_dps"],
                    "members": members,
                }
            )
        if set(groups) != {"global", *(f"discipline-{key}" for key in counts)}:
            raise ValueError("Store does not contain every view for the handoff")
        for view in groups.values():
            if {row["cap"] for row in view} != {*range(request["max_swaps"] + 1), None}:
                raise ValueError("Store does not contain every cap for the handoff")
        keys = {key for view in groups.values() for group in view for key in group["members"]}
        reports = {
            key: json.loads(zlib.decompress(report))
            for key, report in db.execute("SELECT id, report FROM solutions WHERE run=?", (run,))
            if key in keys
        }
    if reports.keys() != keys:
        raise ValueError("Store is missing detailed frontier solutions")
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "xt", encoding="utf-8") as destination:
        json.dump({"request": request, "groups": groups, "reports": reports}, destination)


def replay_merge(source: Path, output: Path, *, native: bool) -> None:
    from tracker.gear.discipline_assignments import branch_requests
    from tracker.gear.objective_store import _json
    from tracker.gear.optimizer import OptimizationRequest
    from tracker.gear.potion_search import merge_objective_frontiers
    from tracker.gear.vector_archive import VectorArchive, solution_identity, solution_vector
    from tracker.gear.vector_publish import FrontierPoints

    with gzip.open(source, "rt", encoding="utf-8") as stream:
        fixture = json.load(stream)
    request = OptimizationRequest.model_validate(
        {key: value for key, value in fixture["request"].items() if key != "optimization_mode"}
    )
    ids = tuple(axis.id for axis in request.objectives or ())
    reports = fixture["reports"]
    archives = {}
    results: dict[str, Any] = {}
    seconds: dict[str, float] = {}
    try:
        branches = {}
        for discipline, _ in branch_requests(request):
            view = f"discipline-{discipline}"
            groups = fixture["groups"][view]
            input_groups = []
            for group in groups:
                members = tuple(group["members"])
                if members not in archives:
                    archive = archives[members] = VectorArchive(ids)
                    params = ",".join("?" for _ in range(len(ids) + 3))
                    archive.connection.executemany(
                        f"INSERT INTO candidates VALUES ({params})",
                        (
                            (solution_identity(row), *solution_vector(row, ids), _json(row))
                            for key in members
                            for row in (reports[key],)
                        ),
                    )
                cap = group["cap"]
                input_groups.append(
                    {"swap_limit": cap, "points": FrontierPoints(archives[members], cap)}
                )
            branches[view] = {"objective_frontiers": input_groups}
        for view, groups in fixture["groups"].items():
            sources = list(branches.values()) if view == "global" else [branches[view]]
            prefix = "" if view == "global" else f"{view}-"
            start = perf_counter()
            results[view] = (
                merge_objective_frontiers(request, sources, id_prefix=prefix, native_merge=True)
                if native
                else merge_objective_frontiers(request, sources, id_prefix=prefix)
            )
            seconds[view] = perf_counter() - start
            expected_by_cap = {group["cap"]: group for group in groups}
            for group in results[view]["objective_frontiers"]:
                cap = group["swap_limit"]
                expected = expected_by_cap[cap]
                members = expected["members"]
                expected_ids = sorted(
                    members,
                    key=lambda key: (
                        *(-number for number in solution_vector(reports[key], ids)),
                        solution_identity(reports[key]),
                    ),
                )
                baseline = max((reports[key]["score"] for key in members), default=0)
                expected_baseline = expected.get("baseline_dps", baseline)
                if group["baseline_dps"] != expected_baseline:
                    raise ValueError(f"Historical merge baseline changed for {view} cap {cap}")
                found = []
                for point in group["points"]:
                    row = point["solution"]
                    identity = solution_identity(row)
                    loss = expected_baseline - row["score"]
                    if point["id"] != f"{prefix}objective-{cap}-{identity[:24]}":
                        raise ValueError(f"Historical merge point ID changed for {view} cap {cap}")
                    if point["dps_loss"] != loss or point["dps_loss_pct"] != (
                        100 * loss / expected_baseline if expected_baseline else None
                    ):
                        raise ValueError(f"Historical merge loss changed for {view} cap {cap}")
                    found.append(
                        "objective-" + hashlib.sha256(_json(row).encode()).hexdigest()[:24]
                    )
                if found != expected_ids:
                    raise ValueError(f"Historical merge rows or order changed for {view} cap {cap}")
        write_json(output, {"seconds": seconds, "total": sum(seconds.values()), "parity": True})
    finally:
        for result in results.values():
            close_result_archives(result)
        for archive in archives.values():
            archive.close()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(without_observations(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def frontier_digest(result: dict[str, Any]) -> dict[str, Any]:
    """Hash each complete group in published order without retaining rich points."""

    def view(container: Any) -> list[dict[str, Any]]:
        groups = []
        for group in container.get("objective_frontiers", ()):
            rolling = hashlib.sha256()
            for point in group["points"]:
                rolling.update(digest(point).encode())
            groups.append(
                {
                    "group": digest(
                        {key: value for key, value in group.items() if key != "points"}
                    ),
                    "points": len(group["points"]),
                    "sha256": rolling.hexdigest(),
                }
            )
        return groups

    fields = ("selected_solution", "unrestricted", "curve", "search", "objective_definitions")
    return {
        **{key: digest(result.get(key)) for key in fields},
        "global": view(result),
        "disciplines": {
            branch["discipline"]: {
                "groups": view(branch),
                **{key: digest(branch.get(key)) for key in fields},
            }
            for branch in result.get("discipline_results", ())
        },
    }


def complete_digest(store: ObjectiveRunStore, run_id: str) -> dict[str, Any]:
    """Fingerprint every canonical detail and every unsampled group membership."""
    with closing(
        sqlite3.connect(store.directory.joinpath("results.sqlite").as_uri() + "?mode=ro", uri=True)
    ) as db:
        details = hashlib.sha256()
        for identity, report in db.execute(
            "SELECT id, report FROM solutions WHERE run=? ORDER BY id", (run_id,)
        ):
            details.update(identity.encode())
            details.update(zlib.decompress(report))
        membership = {}
        groups = db.execute("SELECT id FROM groups WHERE run=? ORDER BY id", (run_id,))
        for (group_id,) in groups:
            keys = [
                identity
                for (identity,) in db.execute(
                    "SELECT solution FROM members WHERE run=? AND group_id=? ORDER BY solution",
                    (run_id, group_id),
                )
            ]
            membership[group_id] = {"count": len(keys), "sha256": digest(keys)}
    return {"details_sha256": details.hexdigest(), "groups": membership}


@contextmanager
def desktop_service(case: Case, workers: int) -> Iterator[tuple[Any, dict[str, Any]]]:
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.service import GearService

    build = require_native()
    with ExitStack() as stack:
        pool = None
        if workers > 1:
            pool = AutoProcessPool(workers)
            stack.callback(pool.close)
            pool.start(case.content, case.catalog, native_required=True)
        service = GearService(
            case.content,
            auto_pool=pool,
            optimization_profile="combined",
            fixed_reporting=True,
            factored_evaluation=True,
            compact_states=True,
            native_search=True,
            native_required=True,
        )
        service._equipment = case.catalog
        yield service, build


def replay(
    source: Path,
    output: Path,
    workers: int,
    observations: int,
    *,
    memory: bool = False,
    merge_fixture: Path | None = None,
    raw_parity: bool = False,
) -> None:
    if observations < 1:
        raise ValueError("At least one observation is required")
    if raw_parity and (memory or merge_fixture is not None):
        raise ValueError("Raw parity is a separate pass")
    case, provenance = load_frozen_case(source)
    spec = RunSpec(workers, True)
    with desktop_service(case, workers) as (service, build):
        build_hash = digest(build)
        for number in range(observations):
            if raw_parity:
                result, _ = execute(case, provenance, spec, service)
                try:
                    write_json(
                        output / f"{number}.json",
                        {
                            "inputs_sha256": provenance["inputs_sha256"],
                            "raw": frontier_digest(result),
                        },
                    )
                finally:
                    close_result_archives(result)
                continue
            with ObjectiveRunStore() as store:
                scope = measure_process_tree() if memory else nullcontext()
                with scope as measured:
                    started = perf_counter()
                    result, diagnostics = execute(case, provenance, spec, service)
                    optimizer_at = perf_counter()
                    print(
                        json.dumps(
                            {
                                "observation": number,
                                "optimizer_seconds": optimizer_at - started,
                                **result["search"].get("timings_seconds", {}),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    try:
                        published = store.publish_result(
                            result, metadata={}, player_id=case.snapshot.player_id
                        )
                    finally:
                        close_result_archives(result)
                    service_at = perf_counter()
                write_json(
                    output / f"{number}.json",
                    {
                        "inputs_sha256": provenance["inputs_sha256"],
                        "workers": workers,
                        "native_build_sha256": build_hash,
                        "seconds": {
                            "optimizer": optimizer_at - started,
                            "publication": service_at - optimizer_at,
                            "service": service_at - started,
                            **result["search"].get("timings_seconds", {}),
                        },
                        "native": diagnostics,
                        "memory": measured.report() if measured is not None else None,
                        "published": frontier_digest(published),
                        "full_archive": complete_digest(store, published["run_id"]),
                        "complete_membership": [
                            [group["view"], group["swap_limit"], group["total_count"]]
                            for group in published["objective_run"]["groups"]
                        ],
                    },
                )
                if merge_fixture is not None and number == 0:
                    capture_merge(
                        store.directory / "results.sqlite",
                        published["run_id"],
                        case.request.model_dump(mode="json"),
                        result["search"]["discipline_selection"]["branches"],
                        merge_fixture,
                    )


def joint_kernel_counts(native: dict[str, Any]) -> dict[str, int]:
    def total(name: str, field: str) -> int:
        return sum(
            event.get(field, 0) for event in native.get("events", ()) if event["event"] == name
        )

    return {
        "transition_solves": total("transition_solver", "solves"),
        "priced_screened": total("completed_candidate_admission", "screened"),
        "unpriced_screened": total("completed_candidate_admission", "unpriced_screened"),
    }


def compare_observations(
    reference: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    *,
    raw_reference: dict[str, Any] | None = None,
    raw_candidate: dict[str, Any] | None = None,
    control: bool = False,
    joint: bool = False,
) -> dict[str, Any]:
    if len(reference) != len(candidate) or not reference:
        raise ValueError("Supply equal nonempty reference and candidate cohorts")
    observations = reference + candidate
    if any(row.get("memory") is not None for row in observations):
        raise ValueError("Use latency observations without the memory sampler")
    for field in ("inputs_sha256", "workers"):
        if any(row[field] != reference[0][field] for row in observations):
            raise ValueError(f"Timing cohorts differ in {field}")
    for cohort in (reference, candidate):
        if any(
            row.get("native_build_sha256") != cohort[0].get("native_build_sha256") for row in cohort
        ):
            raise ValueError("Native release changed within a timing cohort")
    parity = all(
        "full_archive" in row
        and row["full_archive"] == reference[0].get("full_archive")
        and row["published"] == reference[0]["published"]
        for row in observations
    )
    thresholds = {"optimizer": 0.5, "service": 0.5, "merge": 0.2}
    if joint:
        if control:
            raise ValueError("Choose either joint-case or control thresholds")
        thresholds = {"service": 0.5}
    elif control:
        thresholds = {"optimizer": 1.05, "service": 1.05}
    ratios = {
        phase: median(row["seconds"][phase] for row in candidate)
        / median(row["seconds"][phase] for row in reference)
        for phase in thresholds
    }
    no_fallback = all(row["native"].get("fallback_requests") == 0 for row in candidate)
    kernel_counts = [joint_kernel_counts(row["native"]) for row in candidate] if joint else []
    kernels_exercised = all(
        row["transition_solves"] > 0 and row["priced_screened"] + row["unpriced_screened"] > 0
        for row in kernel_counts
    )
    raw_parity = (
        raw_reference is not None
        and raw_candidate is not None
        and raw_reference["inputs_sha256"] == reference[0]["inputs_sha256"]
        and raw_reference == raw_candidate
    )
    return {
        "pairs": len(reference),
        "complete_publication_parity": parity,
        "zero_candidate_fallbacks": no_fallback,
        **({"native_kernel_counts": kernel_counts} if joint else {}),
        "raw_optimizer_parity": raw_parity,
        "candidate_to_reference_ratios": ratios,
        "qualified": len(reference) >= 3
        and parity
        and raw_parity
        and no_fallback
        and kernels_exercised
        and all(ratios[phase] <= threshold for phase, threshold in thresholds.items()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("handoff", type=Path)
    freeze_parser.add_argument("output", type=Path)
    merge_freeze = commands.add_parser("freeze-merge")
    merge_freeze.add_argument("handoff", type=Path)
    merge_freeze.add_argument("store", type=Path)
    merge_freeze.add_argument("output", type=Path)
    merge_run = commands.add_parser("merge")
    merge_run.add_argument("frozen", type=Path)
    merge_run.add_argument("output", type=Path)
    merge_run.add_argument("--native", action="store_true")
    run = commands.add_parser("run")
    run.add_argument("frozen", type=Path)
    run.add_argument("output", type=Path)
    run.add_argument("--workers", type=int, default=6)
    run.add_argument("--observations", type=int, default=1)
    run.add_argument("--memory", action="store_true")
    run.add_argument("--capture-merge", type=Path)
    run.add_argument("--raw-parity", action="store_true")
    compare = commands.add_parser("compare")
    compare.add_argument("--reference", type=Path, nargs="+", required=True)
    compare.add_argument("--candidate", type=Path, nargs="+", required=True)
    compare.add_argument("--control", action="store_true")
    compare.add_argument(
        "--joint",
        action="store_true",
        help="Qualify full joint desktop service latency and native work",
    )
    compare.add_argument("--reference-raw", type=Path)
    compare.add_argument("--candidate-raw", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.handoff, args.output)
    elif args.command == "freeze-merge":
        freeze_merge(args.handoff, args.store, args.output)
    elif args.command == "merge":
        replay_merge(args.frozen, args.output, native=args.native)
    elif args.command == "compare":
        reference = [json.loads(path.read_bytes()) for path in args.reference]
        candidate = [json.loads(path.read_bytes()) for path in args.candidate]
        raw_reference = json.loads(args.reference_raw.read_bytes()) if args.reference_raw else None
        raw_candidate = json.loads(args.candidate_raw.read_bytes()) if args.candidate_raw else None
        print(
            json.dumps(
                compare_observations(
                    reference,
                    candidate,
                    raw_reference=raw_reference,
                    raw_candidate=raw_candidate,
                    control=args.control,
                    joint=args.joint,
                )
            )
        )
    else:
        replay(
            args.frozen,
            args.output,
            args.workers,
            args.observations,
            memory=args.memory,
            merge_fixture=args.capture_merge,
            raw_parity=args.raw_parity,
        )


if __name__ == "__main__":
    main()
