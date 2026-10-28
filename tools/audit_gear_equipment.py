"""Audit frozen equipment observations without writes, refreshes or network access.

Run ``python -m tools.audit_gear_equipment --help`` from the repository root.
Raw outputs can contain private item observations; default to ignored .tmp/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from tools.gear_audit_report import render_markdown
from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import Content, load_content
from tracker.content.schema import Item
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.db.models import ObservedItem, SyncEvent
from tracker.domain.types import Container, QuestStatus, SkillState, Source, UnlockState
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.coverage_audit import audit_snapshot
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest


def aware_time(value: str) -> datetime:
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError("Evaluation time requires a timezone, for example 2026-10-19T22:05:44Z")
    return at.astimezone(UTC)


@contextmanager
def frozen_database(path: Path) -> Iterator[tuple[sessionmaker[Session], str]]:
    """Copy a WAL-aware read-only connection into one query-only in-memory image."""
    path = path.resolve(strict=True)
    source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    memory = sqlite3.connect(":memory:")
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(memory)
        identity = hashlib.sha256(memory.serialize()).hexdigest()
        memory.execute("PRAGMA query_only=ON")
        engine = create_engine("sqlite://", creator=lambda: memory, poolclass=StaticPool)
        try:
            yield sessionmaker(bind=engine, autoflush=False), identity
        finally:
            engine.dispose()
    finally:
        memory.close()
        source.close()


def code_identity(content: Content) -> dict[str, Any]:
    """Identify local code and normalized authored metadata without account identifiers."""

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    authored = {
        kind: {key: value.model_dump(mode="json") for key, value in sorted(mapping.items())}
        for kind, mapping in (
            ("items", content.items),
            ("quests", content.quests),
            ("skills", content.skills),
        )
    }
    payload = json.dumps(authored, sort_keys=True, separators=(",", ":")).encode()
    source_paths = sorted(
        {
            *Path("tracker/gear").glob("*.py"),
            *Path("tracker/accounts").glob("*.py"),
            Path("tracker/estimation/prices.py"),
            Path("tracker/db/gear_prices.py"),
            Path("tools/audit_gear_equipment.py"),
            Path("tools/gear_audit_report.py"),
        }
    )
    return {
        "git_revision": git("rev-parse", "HEAD"),
        "tracked_worktree_status": git("status", "--short", "--untracked-files=no"),
        "authored_content_sha256": hashlib.sha256(payload).hexdigest(),
        "source_file_sha256": {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths
        },
    }


def audit_database(
    path: Path,
    player_id: int,
    at: datetime | None,
    content: Content,
    catalog: EquipmentCatalog,
    requests: Sequence[OptimizationRequest] | None = None,
) -> dict[str, Any]:
    with frozen_database(path) as (sessions, image_hash):
        snapshot = AccountService(sessions).get_snapshot(player_id)
        prices = DatabaseGearPrices(sessions).get_prices()
        if at is None:
            dates = [
                f.observed_at
                for f in snapshot.observed_items.values()
                if f.quantity > 0
                and f.container in snapshot.container_scans
                and f.observed_at >= snapshot.container_scans[f.container].scanned_at
            ]
            if not dates:
                dates = [s.scanned_at for s in snapshot.container_scans.values()]
            if not dates:
                raise ValueError("No accepted observations/scans: supply an explicit --at")
            at = max(dates)
        result = audit_snapshot(snapshot, content, catalog, prices, at, requests)
        with sessions() as session:
            events = session.scalars(
                select(SyncEvent).where(SyncEvent.player_id == player_id)
            ).all()
            raw = session.scalars(
                select(ObservedItem).where(ObservedItem.player_id == player_id)
            ).all()
            latest_accepted = max((e.received_at for e in events if e.accepted), default=None)
            result["raw_observation_evidence"] = [
                {
                    "item_id": row.item_id,
                    "container": row.container.value,
                    "quantity": row.quantity,
                    "observed_at": row.observed_at.isoformat(),
                    "source": row.source.value,
                    "superseded": row.container in snapshot.container_scans
                    and row.observed_at < snapshot.container_scans[row.container].scanned_at,
                }
                for row in sorted(raw, key=lambda r: (r.item_id, r.container.value))
            ]
            result["provenance"] = {
                **code_identity(content),
                "source_kind": "local_database_snapshot",
                "frozen_database_sha256": image_hash,
                "player_id": player_id,
                "accepted_sync_events": sum(e.accepted for e in events),
                "rejected_sync_events": sum(not e.accepted for e in events),
                "latest_accepted_sync_received_at": latest_accepted.isoformat()
                if latest_accepted
                else None,
                "container_scans": {
                    c.value: {"scanned_at": s.scanned_at.isoformat(), "source": s.source}
                    for c, s in sorted(
                        snapshot.container_scans.items(), key=lambda pair: pair[0].value
                    )
                },
                "history_limit": "Current persisted facts only; deleted/overwritten observations "
                "and rejected payload contents cannot be reconstructed.",
            }
    return result


class FixtureObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: int = Field(gt=0, strict=True)
    container: Container = Container.BANK
    quantity: int = Field(default=1, ge=0, strict=True)
    observed_at: str | None = None


class AuditFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    at: str
    equipment: tuple[EquipmentDefinition, ...]
    content_items: tuple[Item, ...] = ()
    observations: tuple[FixtureObservation, ...] = ()
    scans: dict[Container, str] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    quests: dict[str, QuestStatus] = Field(default_factory=dict)
    unlocks: dict[str, UnlockState] = Field(default_factory=dict)
    members: bool | None = None

    @field_validator("skills")
    @classmethod
    def valid_skills(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not 1 <= level <= 99 for level in value.values()):
            raise ValueError("Fixture skill levels must be 1..99")
        return value


def audit_fixture(
    path: Path,
    at: datetime | None = None,
    requests: Sequence[OptimizationRequest] | None = None,
) -> dict[str, Any]:
    data = path.read_bytes()
    fixture = AuditFixture.model_validate_json(data)
    observed_at = aware_time(fixture.at)
    keys = [(f.item_id, f.container) for f in fixture.observations]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate fixture observation identity")
    items = {i.id: i for i in fixture.equipment}
    if len(items) != len(fixture.equipment):
        raise ValueError("Duplicate fixture physical equipment ID")
    snapshot = AccountSnapshot(
        1,
        "synthetic-audit",
        last_sync_at=observed_at,
        members=fixture.members,
        skills={
            key: SkillState(level, None, Source.MANUAL, observed_at)
            for key, level in fixture.skills.items()
        },
        quests=fixture.quests,
        unlocks=fixture.unlocks,
        container_scans={
            c: ContainerScanFact(c, aware_time(date), "synthetic")
            for c, date in fixture.scans.items()
        },
        observed_items={
            (f.item_id, f.container): ObservedItemFact(
                f.item_id,
                f.container,
                f.quantity,
                "synthetic",
                aware_time(f.observed_at) if f.observed_at else observed_at,
            )
            for f in fixture.observations
        },
    )
    content = Content(items={i.id: i for i in fixture.content_items})
    result = audit_snapshot(
        snapshot, content, EquipmentCatalog(items, "synthetic"), {}, at or observed_at, requests
    )
    result["provenance"] = {
        **code_identity(content),
        "source_kind": "deterministic_fixture",
        "fixture_sha256": hashlib.sha256(data).hexdigest(),
    }
    return result


def read_requests(path: Path) -> list[OptimizationRequest]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload == []:
        raise ValueError("Request list must contain at least one optimizer request")
    return [
        OptimizationRequest.model_validate(r)
        for r in (payload if isinstance(payload, list) else [payload])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", type=Path)
    source.add_argument("--fixture", type=Path)
    parser.add_argument("--player-id", type=int)
    parser.add_argument("--at", type=aware_time)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".tmp/gear-equipment-audit"))
    args = parser.parse_args()
    if args.database and (args.player_id is None or args.player_id < 1):
        parser.error("--database requires a positive --player-id")
    outputs = [args.output_dir / "audit.json", args.output_dir / "audit.md"]
    inputs = [p.resolve() for p in (args.database, args.fixture, args.request) if p]
    if any(p.resolve() in inputs for p in outputs):
        parser.error("Output must not overwrite an input")
    try:
        requests = read_requests(args.request) if args.request else None
        if args.fixture:
            report = audit_fixture(args.fixture, args.at, requests)
        else:
            content = load_content()
            report = audit_database(
                args.database, args.player_id, args.at, content, load_catalog(content), requests
            )
        encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        markdown = render_markdown(report)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        outputs[0].write_text(encoded, encoding="utf-8")
        outputs[1].write_text(markdown, encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Audit failed: {exc}\n")
    except SQLAlchemyError as exc:
        parser.exit(
            1, f"Audit failed: database schema/data could not be read ({type(exc).__name__})\n"
        )
    print(json.dumps({"json": str(outputs[0]), "markdown": str(outputs[1])}))


if __name__ == "__main__":
    main()
