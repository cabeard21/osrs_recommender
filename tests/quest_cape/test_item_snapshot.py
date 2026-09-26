"""Account item observations stay immutable and affect snapshot identity."""

from datetime import UTC, datetime, timedelta

from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.db.models import Base, ContainerScan, ObservedItem, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Container, Source


def test_item_and_scan_facts_change_identity_without_expanding_summary() -> None:
    now = datetime(2026, 9, 25, tzinfo=UTC)
    items = {
        (123, Container.BANK): ObservedItemFact(
            item_id=123,
            container=Container.BANK,
            quantity=1,
            source=Source.RUNELITE.value,
            observed_at=now,
        )
    }
    scans = {
        Container.BANK: ContainerScanFact(
            container=Container.BANK,
            scanned_at=now,
            source=Source.RUNELITE.value,
        )
    }
    baseline = AccountSnapshot(player_id=1, username="fixture")
    observed = AccountSnapshot(
        player_id=1, username="fixture", observed_items=items, container_scans=scans
    )
    assert baseline.summary() == observed.summary()
    assert baseline.fingerprint != observed.fingerprint
    items.clear()
    scans.clear()
    assert (123, Container.BANK) in observed.observed_items
    assert Container.BANK in observed.container_scans
    assert observed.fingerprint != baseline.fingerprint


def test_account_service_filters_sighting_superseded_by_latest_scan() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    now = datetime(2026, 9, 25, tzinfo=UTC)
    with sessions.begin() as db:
        db.add(Player(id=1, username="fixture", display_name="Fixture", created_at=now))
        db.flush()
        db.add(
            ObservedItem(
                player_id=1,
                item_id=123,
                container=Container.BANK,
                quantity=1,
                source=Source.RUNELITE,
                observed_at=now - timedelta(hours=2),
            )
        )
        db.add(
            ObservedItem(
                player_id=1,
                item_id=456,
                container=Container.INVENTORY,
                quantity=2,
                source=Source.RUNELITE,
                observed_at=now,
            )
        )
        db.add(
            ContainerScan(
                player_id=1,
                container=Container.BANK,
                source=Source.RUNELITE,
                scanned_at=now - timedelta(hours=1),
            )
        )
    snapshot = AccountService(sessions).get_snapshot(1)
    assert (123, Container.BANK) not in snapshot.observed_items
    assert snapshot.observed_items[(456, Container.INVENTORY)].quantity == 2
    assert snapshot.container_scans[Container.BANK].scanned_at == now - timedelta(hours=1)
    engine.dispose()
