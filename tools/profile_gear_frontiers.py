"""Profile frozen frontier passes without network access or smaller work budgets.

Example fixture comparison (does not replay the dump's original account)::

    python -m tools.profile_gear_frontiers --dump temp.txt --fixture melee_1m \
        --discipline ranged --potion divine_ranging --output .tmp/profile --cprofile

Use ``--snapshot`` with a gear-data-v1 SnapshotEnvelope instead of ``--fixture``
for complete frozen account observations and prices. Local content/catalog are
used in that mode, and their revision is recorded. Keep private output ignored.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import pstats
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.gear_retention_oracle import Case
from tools.gear_search_quality_fixture import load_case
from tracker.gear.objective_store import materialize_result_archives
from tracker.gear.optimizer import OptimizationRequest, optimize
from tracker.gear.potions import PotionPolicy


def load_profile_case(
    dump: Path,
    *,
    fixture: str | None = None,
    snapshot: Path | None = None,
    discipline: str | None = None,
    potions: tuple[str, ...] | None = None,
) -> tuple[Case, dict[str, Any]]:
    """Keep scenario settings, requiring explicit complete account input."""
    if (fixture is None) == (snapshot is None):
        raise ValueError("Provide a snapshot or an explicit fixture, but not both")
    data = json.loads(dump.read_text(encoding="utf-8-sig"))
    live = data["result"]["live"]
    scenario = live["scenario"]
    mode = scenario.get("optimization_mode", "fast")
    if mode not in {"fast", "thorough"}:
        raise ValueError("Unknown optimization mode")
    request = OptimizationRequest.model_validate(
        {k: v for k, v in scenario.items() if k != "optimization_mode"}
    )
    if fixture is not None:
        case = load_case(fixture)
        request = request.model_copy(update={"expected_snapshot_id": None})
        source = f"fixture:{fixture}"
        original_account = False
    else:
        from tracker.content.loader import load_content
        from tracker.gear.catalog import load_catalog
        from tracker.gear.data_source import SnapshotEnvelope

        assert snapshot is not None
        envelope = SnapshotEnvelope.model_validate_json(snapshot.read_bytes())
        account, prices = envelope.facts()
        content = load_content()
        case = Case(
            "snapshot",
            account,
            request,
            load_catalog(content),
            content,
            prices,
            datetime.fromisoformat(live["evaluated_at"]),
        )
        if request.expected_snapshot_id not in {None, account.fingerprint}:
            raise ValueError("Dump and snapshot account fingerprints differ")
        source = "snapshot"
        original_account = request.expected_snapshot_id == account.fingerprint
    if discipline is not None:
        if len(request.roles) != 1 or discipline not in {"melee", "ranged", "magic"}:
            raise ValueError("A discipline override requires one ordinary role")
        role = request.roles[0]
        if role.style == "special":
            raise ValueError("Cannot override a special role")
        role = role.model_copy(
            update={
                "allowed_disciplines": None,
                "style": "slash" if discipline == "melee" else discipline,
                "stance": "rapid" if discipline == "ranged" else "accurate",
            }
        )
        request = request.model_copy(update={"roles": (role,)})
    if potions is not None:
        request = request.model_copy(
            update={"potions": PotionPolicy(mode="fixed", selected_ids=potions)}
        )
    return replace(case, request=request), {
        "account_source": source,
        "original_account_replayed": original_account,
        "snapshot_id": case.snapshot.fingerprint,
        "catalog_revision": case.catalog.revision,
        "catalog_items": len(case.catalog.items),
        "optimization_mode": mode,
        "evaluated_at": case.at.isoformat(),
        "discipline_override": discipline,
        "potion_override": list(potions) if potions is not None else None,
    }


def solution_digest(result: dict[str, Any]) -> str:
    """Hash complete solution archives independently of observational diagnostics."""
    fields = (
        "selected_solution",
        "unrestricted",
        "curve",
        "secondary_frontiers",
        "objective_frontiers",
        "running_cost_frontiers",
    )
    payload = {key: result.get(key) for key in fields}
    if children := result.get("discipline_results"):
        payload["disciplines"] = [
            (child["discipline"], solution_digest(child)) for child in children
        ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def profile_case(
    case: Case, provenance: dict[str, Any], output: Path, *, cprofile: bool = False
) -> dict[str, Any]:
    """Retain complete responses and per-pass diagnostics for a later comparison."""
    output.mkdir(parents=True, exist_ok=True)
    profiler = cProfile.Profile() if cprofile else None
    started = perf_counter()
    options = {
        "_complete_frontiers": True,
        "local_refinement": provenance["optimization_mode"] == "thorough",
    }
    args = (case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    result = (
        profiler.runcall(optimize, *args, **options) if profiler else optimize(*args, **options)
    )
    seconds = perf_counter() - started
    result = materialize_result_archives(result)
    if profiler:
        profiler.dump_stats(output / "calls.prof")
        with (output / "calls.txt").open("w", encoding="utf-8") as stream:
            pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(60)
    report = {
        "provenance": provenance,
        "execution": "serial",
        "request": case.request.model_dump(mode="json"),
        "wall_seconds": seconds,
        "cprofile_enabled": cprofile,
        "complete_frontiers": True,
        "running_cost_objective": any(
            o.kind == "gp_per_damage" for o in case.request.objectives or ()
        ),
        "solution_digest": solution_digest(result),
        "search": result["search"],
    }
    (output / "result.json").write_text(json.dumps(result, default=str), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", help="Explicit substitute account/catalog fixture name")
    source.add_argument("--snapshot", type=Path, help="Frozen gear-data-v1 envelope")
    parser.add_argument("--discipline", choices=("melee", "ranged", "magic"))
    parser.add_argument("--potion", action="append", dest="potions")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cprofile", action="store_true")
    args = parser.parse_args()
    case, provenance = load_profile_case(
        args.dump,
        fixture=args.fixture,
        snapshot=args.snapshot,
        discipline=args.discipline,
        potions=tuple(args.potions) if args.potions is not None else None,
    )
    report = profile_case(case, provenance, args.output, cprofile=args.cprofile)
    print(json.dumps({key: value for key, value in report.items() if key != "search"}, indent=2))


if __name__ == "__main__":
    main()
