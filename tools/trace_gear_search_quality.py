"""Serial research-only beam observer over redacted frozen inputs.

The observer executes the current search class AST with callbacks inserted just
before beam trimming. It changes no branches, ranking, widths, or production
files. Never import this process-local instrumentation from an application.
Instrumented timings are deliberately not reported as benchmarks.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
from copy import deepcopy
from typing import Any

from tools.gear_retention_oracle import Case
from tools.gear_search_quality_fixture import fixture_data, load_case
from tracker.gear import optimizer


def _witness(name: str, bracelet: bool) -> dict[str, dict[str, int]]:
    expected = fixture_data()["expected"]
    result = {r: dict(v["equipment"]) for r, v in expected[name]["loadouts"].items()}
    if name == "joint_four":
        return {**result, "melee": {**result["melee"], "head": 3751}}
    if bracelet:
        return {**result, "melee": {**result["melee"], "hands": 11126}}
    return {"melee": {**expected["owned_slash"]["loadouts"]["melee"]["equipment"], "neck": 1725}}


class _ObserveTrims(ast.NodeTransformer):
    def __init__(self) -> None:
        self.trim_sites = 0

    def visit_Assign(self, node: ast.Assign) -> Any:
        """Insert only beside the two existing expanded-beam retention calls."""
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"states", "beam"}
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "self"
            and node.value.func.attr == "retain"
            and node.value.args
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "expanded"
        ):
            self.trim_sites += 1
            callback = ast.parse("_observe(locals())").body[0]
            return [ast.copy_location(callback, node), node]
        return node


def trace_case(case: Case, *, bracelet: bool = False) -> dict[str, Any]:
    """Observe the baseline serially; restore the original class even on failure."""
    witness = _witness(case.name, bracelet)
    stages: list[dict[str, Any]] = []

    def observe(local: dict[str, Any]) -> None:
        search = local["self"]
        slot = local["slot"]
        slots = set(optimizer.SLOTS[: optimizer.SLOTS.index(slot) + 1])
        joint = "limit" in local
        roles = local["roles"]

        def matches(state: dict[str, Any]) -> bool:
            for role in roles:
                # Conservatively include all non-ranged ammunition variants.
                # Protected prayer/defence means they are not all interchangeable.
                relevant = slots - ({"ammunition"} if role.style != "ranged" else set())
                target = {s: i for s, i in witness[role.id].items() if s in relevant}
                equipment = state[role.id] if joint else state
                if target != {s: i for s, i in equipment.items() if s in relevant}:
                    return False
            return True

        ordered = sorted(local["expanded"], key=local["rank"])
        first = next((index for index, state in enumerate(ordered) if matches(state)), None)
        ids = {r.id: witness[r.id].get(slot) for r in roles}
        stages.append(
            {
                "stage": "joint" if joint else "role" if len(roles) == 1 else "common",
                "roles": [r.id for r in roles],
                "limit": local.get("limit"),
                "slot": slot,
                "expanded": len(ordered),
                "first_witness_rank": first,
                "beam_width": 16 if joint else optimizer.BEAM_WIDTH,
                "choices": deepcopy(local["choices"]),
                "witness_item_ids": ids,
                "witness_retained_in_pool": all(i in search.pools[slot] for i in ids.values()),
            }
        )

    original = optimizer._Search
    tree = ast.parse("from __future__ import annotations\n" + inspect.getsource(original))
    observer = _ObserveTrims()
    tree = ast.fix_missing_locations(observer.visit(tree))
    if observer.trim_sites != 2:
        raise RuntimeError(f"Expected 2 beam retention sites, found {observer.trim_sites}")
    namespace = {**vars(optimizer), "_observe": observe}
    exec(compile(tree, "<research beam observer>", "exec"), namespace)
    optimizer._Search = namespace["_Search"]
    try:
        response = optimizer.optimize(
            case.snapshot, case.request, case.catalog, case.content, case.prices, case.at
        )
    finally:
        optimizer._Search = original
    selected = response["selected_solution"]
    return {
        "scenario": case.name,
        "witness": witness,
        "ammo_equivalence": "Non-ranged role ammunition ignored in prefix matching",
        "baseline_score": selected["score"] if selected else None,
        "stages": stages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=tuple(fixture_data()["requests"]))
    parser.add_argument("--bracelet", action="store_true")
    args = parser.parse_args()
    print(json.dumps(trace_case(load_case(args.case), bracelet=args.bracelet), indent=2))


if __name__ == "__main__":
    main()
