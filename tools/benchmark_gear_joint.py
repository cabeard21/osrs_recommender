"""Measure joint Gear search with disposable, public synthetic account data.

Uses the complete bundled catalog and the existing frozen-input profiler. Prices
are deterministic synthetic quotes, not market estimates. No operator database,
network, production configuration or optimizer setting is modified.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tools.benchmark_gear import benchmark
from tracker.content.loader import Content, load_content
from tracker.db.models import (
    Base,
    ContainerScan,
    ItemPrice,
    ObservedItem,
    Player,
    QuestState,
    SkillSnapshot,
)
from tracker.domain.types import Container, PriceSourceLayer, QuestStatus, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.service import GearService

FROZEN_AT = datetime(2026, 10, 27, tzinfo=UTC)
OWNED_IDS = frozenset((1333, 841, 882, 1381))


def create_database(
    database: Path, content: Content, catalog: EquipmentCatalog, at: datetime
) -> None:
    """Create new synthetic observations; refuse to overwrite any existing file."""
    database.parent.mkdir(parents=True, exist_ok=True)
    with database.open("xb"):
        pass
    engine = create_engine(f"sqlite:///{database.resolve().as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            session.add(
                Player(
                    id=1,
                    username="synthetic-joint-benchmark",
                    display_name="Synthetic joint benchmark",
                    created_at=at,
                    last_sync_at=at,
                    members=True,
                    combat_level=126,
                    quest_points=400,
                )
            )
            session.flush()
            session.add_all(
                SkillSnapshot(
                    player_id=1, skill=key, level=99, source=Source.MANUAL, observed_at=at
                )
                for key in dict.fromkeys(
                    (*content.skills, "attack", "strength", "defence", "ranged", "magic")
                )
            )
            session.add_all(
                QuestState(
                    player_id=1,
                    quest_id=key,
                    status=QuestStatus.COMPLETE,
                    source=Source.MANUAL,
                    observed_at=at,
                )
                for key in content.quests
            )
            session.add_all(
                ContainerScan(player_id=1, container=key, scanned_at=at, source=Source.MANUAL)
                for key in Container
            )
            session.add_all(
                ObservedItem(
                    player_id=1,
                    item_id=item_id,
                    container=Container.BANK,
                    quantity=1,
                    source=Source.MANUAL,
                    observed_at=at,
                )
                for item_id in sorted(OWNED_IDS & catalog.items.keys())
            )
            session.add_all(
                ItemPrice(
                    item_id=item.id,
                    high_price_gp=1000 + item.id % 1000 * 100,
                    low_price_gp=900 + item.id % 1000 * 100,
                    high_trade_at=at,
                    low_trade_at=at,
                    fetched_at=at,
                    provider="synthetic-benchmark",
                    source=PriceSourceLayer.CACHED,
                )
                for item in catalog.items.values()
                if item.tradeable
            )
            session.commit()
    finally:
        engine.dispose()


def joint_request(role_count: int, action_limit: int) -> dict[str, Any]:
    if role_count not in (2, 3, 4):
        raise ValueError("Joint benchmarks require two through four roles")
    roles = [
        {"id": "melee", "style": "slash", "weight": 2, "stance": "accurate"},
        {"id": "ranged", "style": "ranged", "weight": 1, "stance": "rapid"},
        {"id": "magic", "style": "magic", "weight": 1, "spell": "fire_blast"},
        {"id": "melee-second", "style": "slash", "weight": 0.5, "stance": "aggressive"},
    ]
    return {
        "roles": [
            {**role, "target": {"name": "Synthetic ordinary target", "defence_level": defence}}
            for role, defence in zip(roles[:role_count], (80, 80, 80, 150), strict=False)
        ],
        "mode": "usable",
        "budget_gp": 5_000_000,
        "base_role": "melee",
        "max_swaps": action_limit,
        "reserved_supply_slots": 12,
    }


def summarize(request: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    response = report["response"]
    selected = response["selected_solution"]
    return {
        "role_count": len(request["roles"]),
        "action_limit": request["max_swaps"],
        "reserved_supply_slots": request["reserved_supply_slots"],
        "optimizer_seconds": [run["seconds"]["optimization_total"] for run in report["runs"]],
        "optimizer_median_seconds": report["median_seconds"]["optimization_total"],
        "catalog": response["catalog_summary"],
        "search": response["search"],
        "selected_score": selected["score"] if selected else None,
        "maximum_actions": selected["maximum_actions"] if selected else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--roles", nargs="+", type=int, choices=(2, 3, 4), default=(2, 3, 4))
    parser.add_argument("--actions", nargs="+", type=int, choices=(0, 4, 8), default=(0, 4, 8))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")
    args.directory.mkdir(parents=True, exist_ok=True)
    content = load_content()
    catalog = GearService(content).equipment_catalog()
    database = args.directory / "synthetic.sqlite"
    create_database(database, content, catalog, FROZEN_AT)
    summary: dict[str, Any] = {
        "environment": {
            "platform": platform.platform(),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        "inputs": (
            "Synthetic level-99 member; complete authored quests; deterministic cached quotes"
        ),
        "catalog_version": catalog.revision,
        "at": FROZEN_AT.isoformat(),
        "repeats": args.repeats,
        "cases": [],
    }
    for role_count in args.roles:
        for action_limit in args.actions:
            name = f"roles-{role_count}-actions-{action_limit}"
            request = joint_request(role_count, action_limit)
            request_path = args.directory / f"{name}-request.json"
            request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
            print(f"Starting {name}", flush=True)
            report = benchmark(database, request_path, FROZEN_AT, args.repeats)
            (args.directory / f"{name}-report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            case = summarize(request, report)
            summary["cases"].append(case)
            (args.directory / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
            print(json.dumps(case), flush=True)


if __name__ == "__main__":
    main()
