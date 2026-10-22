"""Browser facts use the real sync/account/catalog/cache boundaries."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.api.gear_ui import ContextResponse, ItemResponse, project_equipment
from tracker.db.models import ContainerScan, ItemPrice, ObservedItem, Player
from tracker.domain.types import Container, PriceSourceLayer, Source
from tracker.gear.service import GearService

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def seed(factory, *, ids=(4151,), scans=True):
    with factory() as session:
        player = Player(
            username="Synced player", display_name="Synced player", created_at=NOW, last_sync_at=NOW
        )
        session.add(player)
        session.flush()
        for item_id in ids:
            session.add(
                ObservedItem(
                    player_id=player.id,
                    item_id=item_id,
                    container=Container.EQUIPMENT,
                    quantity=1,
                    source=Source.RUNELITE,
                    observed_at=NOW,
                )
            )
        if scans:
            for container in Container:
                session.add(
                    ContainerScan(
                        player_id=player.id,
                        container=container,
                        scanned_at=NOW,
                        source=Source.RUNELITE,
                    )
                )
        session.commit()
        return player.id


def test_context_no_account_and_private_boundary(client):
    response = client.get("/ui-api/gear/context")
    assert response.status_code == 200
    data = ContextResponse.model_validate(response.json())
    assert data.account is None
    assert data.current_equipment.status == "unknown"
    assert all(s.status == "unknown" for s in data.current_equipment.slots.values())
    assert client.post("/api/sync", json={}).status_code == 401
    assert (
        client.post("/api/sync", json={}, headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )


def test_account_serialization_and_equipment(client, session_factory):
    player_id = seed(session_factory)
    data = client.get("/ui-api/gear/context").json()
    from tracker.accounts.service import AccountService

    snapshot = AccountService(session_factory).get_snapshot(player_id)
    assert data["account"] == {**snapshot.summary(), "snapshot_id": snapshot.fingerprint}
    assert data["current_equipment"]["equipment"] == {"weapon": 4151}
    assert data["current_equipment"]["slots"]["head"]["status"] == "empty"
    assert data["current_equipment"]["status"] == "observed"
    assert data["items"][0]["numeric_item_id"] == 4151
    assert data["catalog_version"] and data["model_version"] and data["price_revision"]
    assert data["capabilities"]["objectives"][0]["available"] is False


@pytest.mark.parametrize(
    "ids,status,weapon",
    [
        ((4151, 4587), "partial", "ambiguous"),
        ((4151, 99999999), "partial", "observed"),
        ((861, 12954), "partial", "ambiguous"),
    ],
)
def test_ambiguous_and_unknown_projection(client, session_factory, ids, status, weapon):
    seed(session_factory, ids=ids)
    result = client.get("/ui-api/gear/context").json()["current_equipment"]
    assert result["status"] == status
    assert result["slots"]["weapon"]["status"] == weapon
    if weapon == "ambiguous":
        assert "weapon" not in result["equipment"]
    if 99999999 in ids:
        assert result["unmapped_item_ids"] == [99999999]
        assert result["slots"]["head"]["status"] == "unknown"


def test_missing_scan_preserves_positive_sightings(client, session_factory):
    seed(session_factory, scans=False)
    projection = client.get("/ui-api/gear/context").json()["current_equipment"]
    assert projection["status"] == "unknown"
    assert projection["scanned_at"] is None
    assert projection["equipment"] == {"weapon": 4151}
    assert projection["slots"]["head"]["status"] == "unknown"


def test_superseded_observation_not_equipped(content):
    gear = GearService(content)
    snapshot = AccountSnapshot(
        1,
        "test",
        observed_items={
            (4151, Container.EQUIPMENT): ObservedItemFact(
                4151, Container.EQUIPMENT, 1, "runelite", NOW
            )
        },
        container_scans={
            Container.EQUIPMENT: ContainerScanFact(
                Container.EQUIPMENT, NOW + timedelta(seconds=1), "runelite"
            )
        },
    )
    assert project_equipment(snapshot, gear).equipment == {}


def test_ownership_timestamps_missing_prices_requirements_and_variants(client, session_factory):
    seed(session_factory, ids=(25264,))
    variant = client.get("/ui-api/gear/items/25264").json()
    assert variant["item_id"] == variant["numeric_item_id"] == variant["equipment"]["id"] == 25264
    assert variant["ownership"]["status"] == "owned"
    assert variant["ownership"]["sightings"][0]["observed_at"] == NOW.isoformat().replace(
        "+00:00", "Z"
    )
    assert variant["ownership"]["sightings"][0]["container"] == "equipment"
    primary = client.get("/ui-api/gear/items/11773").json()
    assert primary["ownership"]["status"] == "unowned"
    whip = client.get("/ui-api/gear/items/4151").json()
    assert whip["wear"]["status"] == "unknown"  # missing attack observation
    assert whip["equipment"]["requires"] is not None
    assert variant["price"]["amount_gp"] is None
    assert whip["price"]["layer"] == "static_hint"
    assert whip["price"]["provider"] is None
    assert client.get("/ui-api/gear/items/99999999").status_code == 404
    ItemResponse.model_validate(variant)
    with pytest.raises(ValidationError):
        ItemResponse.model_validate({**variant, "slot": None})


def test_price_provenance(client, session_factory):
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            ItemPrice(
                item_id=4151,
                high_price_gp=1234567,
                low_price_gp=1200000,
                high_trade_at=now,
                low_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.LIVE,
                provider="osrs_wiki",
            )
        )
        session.commit()
    price = client.get("/ui-api/gear/items/4151").json()["price"]
    assert price["amount_gp"] == 1234567
    assert price["provider"] == "osrs_wiki"
    assert price["source"] == price["layer"] == "live"
    assert (
        price["selected_trade_at"] == price["fetched_at"] == now.isoformat().replace("+00:00", "Z")
    )
    assert price["confidence"] == "high"
    assert price["policy"] == "acquisition_cost"


def test_catalog_search_pagination_validation(client):
    page = client.get(
        "/ui-api/gear/items", params={"q": "rune", "slot": "weapon", "limit": 2}
    ).json()
    assert page["total"] > 2 and page["next_offset"] == 2
    assert all("rune" in i["name"].lower() for i in page["items"])
    following = client.get(
        "/ui-api/gear/items", params={"q": "rune", "slot": "weapon", "offset": 2, "limit": 2}
    ).json()
    assert {i["item_id"] for i in page["items"]}.isdisjoint(
        i["item_id"] for i in following["items"]
    )
    assert client.get("/ui-api/gear/items?q=25264").json()["items"][0]["numeric_item_id"] == 25264
    for query in ("limit=0", "offset=-1", "slot=unknown", "style=invalid", "ownership=maybe"):
        assert client.get(f"/ui-api/gear/items?{query}").status_code == 422


def test_bank_inventory_observations_and_stale_scan_notes(client, session_factory):
    player_id = seed(session_factory, ids=())
    older = NOW - timedelta(days=30)
    with session_factory() as session:
        for container in (Container.BANK, Container.INVENTORY):
            scan = session.get(ContainerScan, (player_id, container))
            scan.scanned_at = older
            session.add(
                ObservedItem(
                    player_id=player_id,
                    item_id=4151,
                    container=container,
                    quantity=2,
                    source=Source.RUNELITE,
                    observed_at=older,
                )
            )
        session.commit()
    ownership = client.get("/ui-api/gear/items/4151").json()["ownership"]
    assert ownership["status"] == "owned"
    assert ownership["quantity"] == 2  # asynchronous counts must never be added
    assert {s["container"] for s in ownership["sightings"]} == {"bank", "inventory"}
    assert all(
        s["observed_at"] == older.isoformat().replace("+00:00", "Z") for s in ownership["sightings"]
    )
    context = client.get("/ui-api/gear/context")
    assert context.headers["cache-control"] == "no-store"
    assert "ago" in context.json()["container_scans"]["bank"]["note"]


def test_invalid_equipment_quantity_is_ambiguous(content):
    snapshot = AccountSnapshot(
        1,
        "test",
        observed_items={
            (4151, Container.EQUIPMENT): ObservedItemFact(
                4151, Container.EQUIPMENT, 2, "runelite", NOW
            )
        },
        container_scans={
            Container.EQUIPMENT: ContainerScanFact(Container.EQUIPMENT, NOW, "runelite")
        },
    )
    projection = project_equipment(snapshot, GearService(content))
    assert projection.slots["weapon"].status == "ambiguous"
    assert "weapon" not in projection.equipment


@pytest.mark.parametrize("level,expected", [(1, "unsatisfied"), (99, "satisfied")])
def test_physical_requirements_use_observed_skills(client, session_factory, level, expected):
    from tracker.db.models import SkillSnapshot

    player_id = seed(session_factory)
    with session_factory() as session:
        session.add(
            SkillSnapshot(
                player_id=player_id,
                skill="attack",
                level=level,
                source=Source.RUNELITE,
                observed_at=NOW,
            )
        )
        session.commit()
    item = client.get("/ui-api/gear/items/4151").json()
    assert item["wear"]["status"] == expected
    assert item["wear"]["requirements"]["current"] == level
