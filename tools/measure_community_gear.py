"""Compare support policies on the same read-only historical account snapshot.

Raw output includes private exact owned IDs. Keep it in ignored ``.tmp/``.
No network, database writes, invented ownership, or price refresh is performed.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import median
from time import perf_counter

from tools.audit_gear_equipment import aware_time, frozen_database
from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content, load_content
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.domain.types import QuestStatus, SkillState, Source
from tracker.estimation.prices import PriceRecord
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.combat import SPELLS
from tracker.gear.coverage_audit import as_of_prices
from tracker.gear.facts import equipment_fact
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize


def coverage_counts(
    snapshot: AccountSnapshot,
    catalog: EquipmentCatalog,
    content: Content,
    prices: Mapping[int, PriceRecord],
    at: datetime,
) -> dict[str, list[int]]:
    """Count physical IDs before candidate truncation; no final-selection inference."""
    counts: dict[str, list[int]] = {
        name: []
        for name in (
            "supported_ids",
            "owned_usable_ids",
            "priced_purchase_usable_ids",
            "missing_purchase_price_ids",
            "blocked_effect_ids",
            "unknown_gate_ids",
            "unmet_gate_ids",
        )
    }
    assumptions = getattr(catalog, "community_assumptions", {})
    for item_id, item in sorted(catalog.items.items()):
        kwargs = {"support_assumptions": assumptions[item_id]} if item_id in assumptions else {}
        fact = equipment_fact(snapshot, item, content, prices, at, **kwargs)
        if fact["limitations"]:
            counts["blocked_effect_ids"].append(item_id)
        status = fact["wear"]["status"]
        if status != "satisfied":
            counts["unmet_gate_ids" if status == "unsatisfied" else "unknown_gate_ids"].append(
                item_id
            )
            continue
        if fact["limitations"]:
            continue
        counts["supported_ids"].append(item_id)
        if fact["ownership"]["status"] == "owned":
            counts["owned_usable_ids"].append(item_id)
        elif fact["acquisition"] == "tradeable":
            key = (
                "missing_purchase_price_ids"
                if fact["price"]["amount_gp"] is None
                else "priced_purchase_usable_ids"
            )
            counts[key].append(item_id)
    return counts


def measured_run(snapshot, request, catalog, content, prices, at, repeats):
    """Time full unchanged bounded optimizer; report exact selected equipment."""
    seconds = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = optimize(snapshot, request, catalog, content, prices, at)
        seconds.append(perf_counter() - started)
    solution = result["selected_solution"]
    return {
        "request": request.model_dump(mode="json"),
        "seconds": seconds,
        "median_seconds": median(seconds),
        "catalog_summary": result["catalog_summary"],
        "search": result["search"],
        "selected_solution": solution,
        "result_identity": {
            k: result.get(k)
            for k in ("snapshot_id", "catalog_version", "assumptions_fingerprint", "support_policy")
        },
    }


def measure_database(path: Path, player_id: int, at: datetime, repeats: int, budget: int):
    """One frozen DB image feeds both policies and all ordinary attack scenarios."""
    from tracker.gear.support import project_catalog

    content = load_content()
    catalog = load_catalog(content)
    community = project_catalog(catalog, "community_best_effort")
    with frozen_database(path) as (sessions, image_hash):
        snapshot = AccountService(sessions).get_snapshot(player_id)
        prices = as_of_prices(DatabaseGearPrices(sessions).get_prices(), at)
    counts = {
        policy: coverage_counts(snapshot, selected, content, prices, at)
        for policy, selected in (("verified_only", catalog), ("community_best_effort", community))
    }
    changes = {
        key: sorted(set(counts["community_best_effort"][key]) - set(counts["verified_only"][key]))
        for key in ("supported_ids", "owned_usable_ids", "priced_purchase_usable_ids")
    }
    max_level = replace(
        snapshot,
        skills={key: SkillState(99, None, Source.MANUAL, at) for key in content.skills},
        quests=dict.fromkeys(content.quests, QuestStatus.COMPLETE),
        combat_level=126,
    )
    potential = {
        policy: coverage_counts(max_level, selected, content, prices, at)["supported_ids"]
        for policy, selected in (("verified_only", catalog), ("community_best_effort", community))
    }
    potential_new = sorted(
        set(potential["community_best_effort"]) - set(potential["verified_only"])
    )
    signatures = {
        json.dumps(
            {
                "slot": catalog.items[i].slot,
                "bonuses": catalog.items[i].bonuses.model_dump(),
                "speed": catalog.items[i].attack_speed,
                "styles": catalog.items[i].attack_styles,
                "profiles": catalog.items[i].attack_profiles,
                "ammo_type": catalog.items[i].ammo_type,
                "ammo_for": catalog.items[i].ammo_for,
                "two_handed": catalog.items[i].two_handed,
            },
            sort_keys=True,
        )
        for i in potential_new
    }
    magic_level = snapshot.skills.get("magic")
    spell = max(
        (
            (name, damage)
            for name, (level, damage) in SPELLS.items()
            if magic_level is not None and level <= magic_level.level
        ),
        key=lambda p: p[1],
        default=("fire_strike", 2),
    )[0]
    runs = []
    for mode in ("owned", "usable"):
        for style in ("slash", "ranged", "magic"):
            for policy in ("verified_only", "community_best_effort"):
                request = OptimizationRequest(
                    roles=(
                        RoleConfig(
                            id=style,
                            style=style,
                            spell=spell,
                            stance="rapid" if style == "ranged" else "accurate",
                            target=CombatTarget(defence_level=100, magic_level=100),
                        ),
                    ),
                    mode=mode,
                    budget_gp=budget,
                    max_swaps=0,
                    support_policy=policy,
                )
                run = measured_run(snapshot, request, catalog, content, prices, at, repeats)
                runs.append(run)
                score = run["selected_solution"]["score"] if run["selected_solution"] else None
                print(
                    f"{mode}/{style}/{policy}: {run['median_seconds']:.3f}s score={score}",
                    flush=True,
                )
    return {
        "source_kind": "historical_local_database_snapshot",
        "evaluated_at": at.isoformat(),
        "frozen_database_sha256": image_hash,
        "snapshot_id": snapshot.fingerprint,
        "catalog_revision": catalog.revision,
        "community_provenance": getattr(community, "community_provenance", {}),
        "price_records_available_at_evaluation": len(prices),
        "policy_counts": counts,
        "newly_usable_ids": changes,
        "max_level_catalog_potential": {
            "meaning": "Synthetic level99/complete-quest upper bound, not account observations.",
            "policy_supported_counts": {k: len(v) for k, v in potential.items()},
            "newly_supported_ids": potential_new,
            "distinct_combat_signatures_added": len(signatures),
        },
        "newly_usable_by_slot": dict(
            Counter(catalog.items[i].slot for i in changes["supported_ids"])
        ),
        "runs": runs,
        "limitations": [
            "Historical local snapshot; not current live account acceptance.",
            "Supported counts precede price/budget/ownership and scenario compatibility checks.",
            "Priced purchase count excludes owned IDs; prices and ownership can be unknown.",
            "Single-role ordinary attacks; bounded search and unchanged formulas.",
            "Timings are local observations, not performance guarantees.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("tracker.db"))
    parser.add_argument("--player-id", type=int, default=1)
    parser.add_argument("--at", type=aware_time, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--budget-gp", type=int, default=50_000_000)
    parser.add_argument("--output", type=Path, default=Path(".tmp/community-gear-measurement.json"))
    args = parser.parse_args()
    if args.repeats < 1 or args.player_id < 1 or args.budget_gp < 0:
        parser.error("repeats/player-id must be positive and budget nonnegative")
    if args.output.resolve() == args.database.resolve():
        parser.error("output cannot replace the source database")
    result = measure_database(args.database, args.player_id, args.at, args.repeats, args.budget_gp)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "newly_usable": {k: len(v) for k, v in result["newly_usable_ids"].items()},
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
