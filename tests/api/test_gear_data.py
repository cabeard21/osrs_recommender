from datetime import UTC, datetime

from pydantic import SecretStr

from tracker.db.models import Player
from tracker.gear.data_source import SnapshotEnvelope


def test_read_endpoint_disabled_without_token(client):
    assert client.get("/api/gear-data/v1/players/1/snapshot").status_code == 404


def test_read_credential_cannot_sync_and_write_credential_cannot_read(client, session_factory):
    client.app.state.settings.gear_data_token = SecretStr("read-only")
    with session_factory() as session:
        session.add(
            Player(id=1, username="test", display_name="test", created_at=datetime.now(UTC))
        )
        session.commit()
    path = "/api/gear-data/v1/players/1/snapshot"
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"Authorization": "Bearer test-token-1234567890"}).status_code
        == 401
    )
    response = client.get(path, headers={"Authorization": "Bearer read-only"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert SnapshotEnvelope.model_validate(response.json()).facts()[0].username == "test"
    assert (
        client.post("/api/sync", headers={"Authorization": "Bearer read-only"}, json={}).status_code
        == 401
    )
    assert (
        client.get(
            "/api/gear-data/v1/players/999/snapshot", headers={"Authorization": "Bearer read-only"}
        ).status_code
        == 404
    )


def test_account_and_prices_share_read_transaction(session_factory, monkeypatch):
    from tracker.accounts.service import AccountService
    from tracker.db.gear_prices import DatabaseGearPrices
    from tracker.db.models import ItemPrice
    from tracker.domain.types import PriceSourceLayer
    from tracker.gear.data_source import LocalGearDataSource

    with session_factory() as session:
        session.add(
            Player(id=1, username="test", display_name="test", created_at=datetime.now(UTC))
        )
        session.add(
            ItemPrice(
                item_id=4151,
                high_price_gp=100,
                fetched_at=datetime.now(UTC),
                provider="wiki",
                source=PriceSourceLayer.CACHED,
            )
        )
        session.commit()
    original = AccountService.read_snapshot

    def read_then_write(session, player_id):
        result = original(session, player_id)
        with session_factory() as writer:
            writer.get(ItemPrice, 4151).high_price_gp = 200
            writer.commit()
        return result

    monkeypatch.setattr(AccountService, "read_snapshot", staticmethod(read_then_write))
    account, prices = LocalGearDataSource(session_factory, 1).load()
    assert account.username == "test"
    assert prices[4151].high_price_gp == 100
    assert DatabaseGearPrices(session_factory).get_prices()[4151].high_price_gp == 200
