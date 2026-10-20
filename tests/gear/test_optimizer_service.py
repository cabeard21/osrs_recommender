"""One service boundary for web/MCP, with no database or price fetches."""

from datetime import UTC, datetime

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.gear.service import GearService


def test_service_optimizer_delegates_frozen_context(monkeypatch, make_content):
    import tracker.gear.optimizer as engine

    snapshot = AccountSnapshot(player_id=1, username="fixture")
    service = GearService(make_content())
    now = datetime(2026, 10, 19, tzinfo=UTC)
    calls = []

    def optimize(account, request, catalog, content, price_records, evaluated_at, **kwargs):
        calls.append((account, request, catalog, content, price_records, evaluated_at))
        return {"snapshot_id": account.fingerprint}

    monkeypatch.setattr(engine, "optimize", optimize)
    assert service.optimize(snapshot, {"roles": [{"id": "melee", "style": "slash"}]}, now=now) == {
        "snapshot_id": snapshot.fingerprint
    }
    assert calls[0][0] is snapshot
    assert calls[0][-1] == now
    assert calls[0][-2] == {}


def test_optimizer_catalog_explains_locked_items(make_content, make_item):
    content = make_content(
        items=[make_item("dragon_scimitar", numeric_id=4587, requires={"skill": {"attack": 60}})]
    )
    snapshot = AccountSnapshot(player_id=1, username="fixture")
    service = GearService(content)
    result = service.optimizer_catalog(snapshot)
    item = next(row for row in result["items"] if row["item_id"] == 4587)
    assert item["numeric_item_id"] == 4587
    assert item["wear"]["status"] == "unknown"
    assert item["ownership"]["status"] == "unknown"
    assert result["snapshot_id"] == snapshot.fingerprint


def test_optimizer_catalog_rejects_bad_filter(make_content):
    service = GearService(make_content())
    with pytest.raises(ValueError, match="ownership"):
        service.optimizer_catalog(
            AccountSnapshot(player_id=1, username="fixture"), ownership="invented"
        )


def test_service_bounds_concurrent_search_and_recovers(monkeypatch, make_content):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import tracker.gear.optimizer as engine

    service = GearService(make_content())
    snapshot = AccountSnapshot(player_id=1, username="fixture")
    started, release = Event(), Event()

    def work(*args, **kwargs):
        started.set()
        if not release.wait(10):
            raise RuntimeError("test search was not released")
        return {"snapshot_id": snapshot.fingerprint}

    monkeypatch.setattr(engine, "optimize", work)
    with ThreadPoolExecutor(max_workers=1) as worker:
        first = worker.submit(service.optimize, snapshot, {})
        try:
            assert started.wait(10)
            with pytest.raises(ValueError, match="optimizer_busy"):
                service.optimize(snapshot, {})
        finally:
            release.set()
        assert first.result(timeout=10)["snapshot_id"] == snapshot.fingerprint
    assert service.optimize(snapshot, {})["snapshot_id"] == snapshot.fingerprint


def test_numeric_details_can_inspect_non_ladder_equipment(make_content):
    service = GearService(make_content())
    snapshot = AccountSnapshot(player_id=1, username="fixture")
    result = service.item_details(snapshot, numeric_item_id=4587)
    assert result["items"][0]["numeric_item_id"] == 4587
    assert result["items"][0]["wear"]["status"] == "unknown"
    assert result["items"][0]["equipment"]["bonuses"]["slash"] == 67
