"""Versioned raw Gear facts; calculations and authored content remain local."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import (
    AccountSnapshot,
    ContainerScanFact,
    Observation,
    ObservedItemFact,
)
from tracker.db.gear_prices import CachedPriceRecord, DatabaseGearPrices
from tracker.domain.types import QuestStatus, SkillState, UnlockState
from tracker.ui.read_model import first_player_id


class AccountFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_id: int = Field(gt=0)
    username: str
    skills: dict[str, SkillState]
    quests: dict[str, QuestStatus]
    quest_observations: dict[str, Observation]
    unlocks: dict[str, UnlockState]
    observed_items: list[ObservedItemFact]
    container_scans: list[ContainerScanFact]
    quest_points: int | None
    combat_level: int | None
    members: bool | None
    last_sync_at: datetime | None

    @classmethod
    def from_snapshot(cls, snapshot: AccountSnapshot) -> AccountFacts:
        values = {name: getattr(snapshot, name) for name in cls.model_fields}
        return cls(
            **(
                values
                | {
                    "observed_items": list(snapshot.observed_items.values()),
                    "container_scans": list(snapshot.container_scans.values()),
                }
            )
        )

    def snapshot(self) -> AccountSnapshot:
        items = {(v.item_id, v.container): v for v in self.observed_items}
        scans = {v.container: v for v in self.container_scans}
        if len(items) != len(self.observed_items) or len(scans) != len(self.container_scans):
            raise ValueError("Duplicate account facts")
        values = {name: getattr(self, name) for name in type(self).model_fields}
        return AccountSnapshot(**(values | {"observed_items": items, "container_scans": scans}))


class SnapshotEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_version: Literal["gear-data-v1"] = "gear-data-v1"
    retrieved_at: datetime
    snapshot_id: str
    price_revision: str
    account: AccountFacts
    prices: list[CachedPriceRecord]

    @classmethod
    def from_facts(
        cls, snapshot: AccountSnapshot, prices: dict[int, CachedPriceRecord]
    ) -> SnapshotEnvelope:
        records = [prices[key] for key in sorted(prices)]
        revision = hashlib.sha256(
            json.dumps([asdict(v) for v in records], default=str, sort_keys=True).encode()
        ).hexdigest()
        return cls(
            retrieved_at=datetime.now(UTC),
            snapshot_id=snapshot.fingerprint,
            price_revision=revision,
            account=AccountFacts.from_snapshot(snapshot),
            prices=records,
        )

    def facts(self) -> tuple[AccountSnapshot, dict[int, CachedPriceRecord]]:
        snapshot = self.account.snapshot()
        if snapshot.fingerprint != self.snapshot_id:
            raise ValueError("Account fingerprint mismatch")
        prices = {v.item_id: v for v in self.prices}
        if len(prices) != len(self.prices):
            raise ValueError("Duplicate prices")
        if self.from_facts(snapshot, prices).price_revision != self.price_revision:
            raise ValueError("Price revision mismatch")
        return snapshot, prices


class GearDataSource(Protocol):
    def load(self) -> tuple[AccountSnapshot | None, dict[int, CachedPriceRecord]]: ...


@dataclass(frozen=True)
class LocalGearDataSource:
    sessions: sessionmaker[Session]
    player_id: int | None = None

    def load(self) -> tuple[AccountSnapshot | None, dict[int, CachedPriceRecord]]:
        with self.sessions(autoflush=False) as session:
            if session.get_bind().dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN")
            player_id = self.player_id if self.player_id is not None else first_player_id(session)
            snapshot = AccountService.read_snapshot(session, player_id) if player_id else None
            return snapshot, DatabaseGearPrices.read_prices(session)


@dataclass(frozen=True)
class RemoteGearDataSource:
    base_url: str
    player_id: int
    token: str = field(repr=False)
    timeout: float = 10

    def __post_init__(self) -> None:
        parts = urlsplit(self.base_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError("Pi URL must be a private HTTP(S) origin without credentials")
        try:
            address = ipaddress.ip_address(parts.hostname)
            private = (
                address.is_private
                or address.is_loopback
                or address in ipaddress.ip_network("100.64.0.0/10")
            )
        except ValueError:
            private = (
                parts.hostname == "localhost"
                or "." not in parts.hostname
                or parts.hostname.endswith((".local", ".ts.net"))
            )
        if not private or self.player_id < 1 or not self.token or self.timeout <= 0:
            raise ValueError("Private Pi origin, player ID and token are required")

    def load(self) -> tuple[AccountSnapshot, dict[int, CachedPriceRecord]]:
        try:
            with httpx.Client(
                timeout=self.timeout, follow_redirects=False, trust_env=False
            ) as client:
                response = client.get(
                    f"{self.base_url.rstrip('/')}/api/gear-data/v1/players/{self.player_id}/snapshot",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                response.raise_for_status()
                envelope = SnapshotEnvelope.model_validate_json(response.content)
                if envelope.account.player_id != self.player_id:
                    raise ValueError("Wrong player")
                return envelope.facts()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                503,
                detail={
                    "code": "gear_source_unavailable",
                    "message": "Pi data unavailable; check connection, read token and API version.",
                },
            ) from exc
