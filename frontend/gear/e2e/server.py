"""Disposable real FastAPI + NiceGUI server for preview acceptance tests."""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from sqlalchemy import delete, update

from tracker.app import _mount_ui, create_app
from tracker.config.settings import Settings
from tracker.db.models import (
    Base,
    ContainerScan,
    ItemPrice,
    ObservedItem,
    Player,
    QuestState,
    SkillSnapshot,
)
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Container, PriceSourceLayer, QuestStatus, Source
from tracker.gear.catalog import EquipmentCatalog

if __name__ == "__main__":
    with TemporaryDirectory(prefix="gear-preview-browser-") as directory:
        engine = build_engine(f"sqlite:///{directory}/preview.sqlite")
        Base.metadata.create_all(engine)
        factory = build_session_factory(engine)
        with factory() as session:
            session.add(
                Player(username="player", display_name="Player", created_at=datetime.now(UTC))
            )
            session.commit()
        app = create_app(
            Settings(
                bind_address="127.0.0.1",
                api_token="isolated-preview-test-token",
                content_dir=Path(__file__).resolve().parents[3] / "content",
            ),
            session_factory=factory,
            mount_ui=False,
        )
        native = os.environ.get("GEAR_E2E_NATIVE") == "1"
        if native:
            from tracker.gear.native.readiness import require_native
            from tracker.gear.service import GearService

            require_native()
            app.state.gear_service = GearService(
                app.state.gear_service.content,
                equipment_root=Path(__file__).resolve().parents[3] / "content" / "equipment",
                optimization_profile="combined",
                fixed_reporting=True,
                factored_evaluation=True,
                compact_states=True,
                native_search=True,
            )
        original_catalog = app.state.gear_service.equipment_catalog()

        @app.get("/test/native-diagnostics")
        def native_diagnostics():
            return {"enabled": native, **app.state.gear_service.native_diagnostics}

        @app.post("/test/reset-gear")
        def reset_gear():
            # Test-only control over this disposable database; never mounted by create_app.
            app.state.gear_service._equipment = original_catalog
            with factory() as session:
                for model in (ObservedItem, ContainerScan, SkillSnapshot):
                    session.execute(delete(model))
                session.execute(update(Player).values(last_sync_at=None))
                session.commit()
            return {"status": "reset"}

        @app.post("/test/seed-optimization")
        def seed_optimization():
            reset_gear()
            now = datetime.now(UTC)
            # Real bundled definitions and unchanged optimizer, deliberately tiny search.
            app.state.gear_service._equipment = EquipmentCatalog(
                {item_id: original_catalog.items[item_id] for item_id in (1331, 1333, 6585)},
                revision="browser-acceptance-bundled-subset-v2",
            )
            with factory() as session:
                player = session.query(Player).first()
                player.last_sync_at = now
                for skill in (
                    "attack",
                    "strength",
                    "defence",
                    "ranged",
                    "magic",
                    "hitpoints",
                    "prayer",
                ):
                    session.add(
                        SkillSnapshot(
                            player_id=player.id,
                            skill=skill,
                            level=75,
                            source=Source.RUNELITE,
                            observed_at=now,
                        )
                    )
                for container in Container:
                    session.add(
                        ContainerScan(
                            player_id=player.id,
                            container=container,
                            scanned_at=now,
                            source=Source.RUNELITE,
                        )
                    )
                session.add(
                    ObservedItem(
                        player_id=player.id,
                        item_id=1333,
                        quantity=1,
                        container=Container.EQUIPMENT,
                        source=Source.RUNELITE,
                        observed_at=now,
                    )
                )
                for item_id, high, low in ((1331, 1000, 900), (6585, 10000, 9000)):
                    session.merge(
                        ItemPrice(
                            item_id=item_id,
                            high_price_gp=high,
                            low_price_gp=low,
                            high_trade_at=now,
                            low_trade_at=now,
                            fetched_at=now,
                            provider="deterministic-browser-fixture",
                            source=PriceSourceLayer.CACHED,
                        )
                    )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-untradeables")
        def seed_untradeables():
            seed_optimization()
            app.state.gear_service._equipment = EquipmentCatalog(
                {item_id: original_catalog.items[item_id] for item_id in (1331, 1333, 6585, 6570)},
                revision="browser-acceptance-untradeables-v1",
            )
            return {"status": "seeded"}

        @app.post("/test/seed-slayer")
        def seed_slayer():
            seed_optimization()
            app.state.gear_service._equipment = EquipmentCatalog(
                {item_id: original_catalog.items[item_id] for item_id in (1333, 8921)},
                revision="browser-acceptance-slayer-v1",
            )
            with factory() as session:
                player = session.query(Player).first()
                player.combat_level = 100
                session.add(
                    ObservedItem(
                        player_id=player.id,
                        item_id=8921,
                        quantity=1,
                        container=Container.BANK,
                        source=Source.RUNELITE,
                        observed_at=datetime.now(UTC),
                    )
                )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-demonbane")
        def seed_demonbane():
            seed_optimization()
            app.state.gear_service._equipment = EquipmentCatalog(
                {
                    item_id: original_catalog.items[item_id]
                    for item_id in (29589, 29591, 29594, 892)
                },
                revision="browser-acceptance-demonbane-v1",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                session.execute(update(SkillSnapshot).values(level=99))
                session.merge(
                    QuestState(
                        player_id=player.id,
                        quest_id="a_kingdom_divided",
                        status=QuestStatus.COMPLETE,
                        source=Source.RUNELITE,
                        observed_at=now,
                    )
                )
                for item_id in (29589, 29591, 29594, 892):
                    session.add(
                        ObservedItem(
                            player_id=player.id,
                            item_id=item_id,
                            quantity=1000 if item_id == 892 else 1,
                            container=Container.BANK,
                            source=Source.RUNELITE,
                            observed_at=now,
                        )
                    )
                for item_id in (554, 562, 566, 564, 892):
                    session.merge(
                        ItemPrice(
                            item_id=item_id,
                            high_price_gp=100,
                            low_price_gp=90,
                            high_trade_at=now,
                            low_trade_at=now,
                            fetched_at=now,
                            provider="deterministic-browser-fixture",
                            source=PriceSourceLayer.CACHED,
                        )
                    )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-leafy")
        def seed_leafy():
            seed_optimization()
            app.state.gear_service._equipment = EquipmentCatalog(
                {item_id: original_catalog.items[item_id] for item_id in (1333, 20727)},
                revision="browser-acceptance-leafy-v1",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                session.add(
                    SkillSnapshot(
                        player_id=player.id,
                        skill="slayer",
                        level=55,
                        source=Source.RUNELITE,
                        observed_at=now,
                    )
                )
                session.add(
                    ObservedItem(
                        player_id=player.id,
                        item_id=20727,
                        quantity=1,
                        container=Container.BANK,
                        source=Source.RUNELITE,
                        observed_at=now,
                    )
                )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-joint")
        def seed_joint():
            seed_optimization()
            # Reviewed bundled definitions, with actual hand/ammunition metadata.
            # This subset exercises the unchanged joint optimizer, not a mock solve.
            item_ids = (1331, 1333, 861, 892, 1381, 12954, 6585)
            app.state.gear_service._equipment = EquipmentCatalog(
                {item_id: original_catalog.items[item_id] for item_id in item_ids},
                revision="browser-acceptance-joint-bundled-v1",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                for item_id in (861, 892, 1381, 12954):
                    session.add(
                        ObservedItem(
                            player_id=player.id,
                            item_id=item_id,
                            quantity=100 if item_id == 892 else 1,
                            container=Container.BANK,
                            source=Source.RUNELITE,
                            observed_at=now,
                        )
                    )
                session.commit()
            return {"status": "seeded", "catalog_items": len(item_ids)}

        @app.post("/test/seed-ammo")
        def seed_ammo():
            seed_joint()
            app.state.gear_service._equipment = EquipmentCatalog(
                {
                    **app.state.gear_service._equipment.items,
                    **{i: original_catalog.items[i] for i in (882, 10499, 22109, 29289)},
                },
                revision="browser-acceptance-arrow-comparison-v2",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                for item_id in (882, 29289):
                    session.add(
                        ObservedItem(
                            player_id=player.id,
                            item_id=item_id,
                            quantity=100 if item_id == 882 else 1,
                            container=Container.BANK,
                            source=Source.RUNELITE,
                            observed_at=now,
                        )
                    )
                session.merge(
                    ItemPrice(
                        item_id=892,
                        high_price_gp=100,
                        low_price_gp=95,
                        high_trade_at=now,
                        low_trade_at=now,
                        fetched_at=now,
                        provider="deterministic-browser-fixture",
                        source=PriceSourceLayer.CACHED,
                    )
                )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-running-cost")
        def seed_running_cost():
            seed_joint()
            now = datetime.now(UTC)
            with factory() as session:
                for item_id, price in (
                    (556, 5),
                    (555, 5),
                    (557, 5),
                    (554, 5),
                    (558, 4),
                    (562, 50),
                    (560, 100),
                    (565, 200),
                    (21880, 250),
                ):
                    session.merge(
                        ItemPrice(
                            item_id=item_id,
                            high_price_gp=price,
                            low_price_gp=price,
                            high_trade_at=now,
                            low_trade_at=now,
                            fetched_at=now,
                            provider="deterministic-browser-fixture",
                            source=PriceSourceLayer.CACHED,
                        )
                    )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-elemental-amulet")
        def seed_elemental_amulet():
            seed_running_cost()
            item_ids = (1381, 1727, 34428)
            app.state.gear_service._equipment = EquipmentCatalog(
                {item_id: original_catalog.items[item_id] for item_id in item_ids},
                revision="browser-acceptance-elemental-amulet-v1",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                for item_id in (1727, 34428):
                    session.add(
                        ObservedItem(
                            player_id=player.id,
                            item_id=item_id,
                            quantity=1,
                            container=Container.BANK,
                            source=Source.RUNELITE,
                            observed_at=now,
                        )
                    )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-tome")
        def seed_tome():
            seed_running_cost()
            app.state.gear_service._equipment = EquipmentCatalog(
                {i: original_catalog.items[i] for i in (1381, 20714, 20716, 34425)},
                revision="browser-tome-amulet-v2",
            )
            with factory() as session:
                player = session.query(Player).first()
                session.add(
                    ObservedItem(
                        player_id=player.id,
                        item_id=20716,
                        quantity=1,
                        container=Container.BANK,
                        source=Source.RUNELITE,
                        observed_at=datetime.now(UTC),
                    )
                )
                session.add(
                    ObservedItem(
                        player_id=player.id,
                        item_id=34425,
                        quantity=1,
                        container=Container.BANK,
                        source=Source.RUNELITE,
                        observed_at=datetime.now(UTC),
                    )
                )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-bolt-hopper")
        def seed_bolt_hopper():
            seed_optimization()
            item_ids = (9185, 9242, 32879)
            app.state.gear_service._equipment = EquipmentCatalog(
                {i: original_catalog.items[i] for i in item_ids},
                revision="browser-bolt-hopper-v1",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                for item_id in item_ids:
                    session.add(
                        ObservedItem(
                            player_id=player.id,
                            item_id=item_id,
                            quantity=100 if item_id == 9242 else 1,
                            container=Container.BANK,
                            source=Source.RUNELITE,
                            observed_at=now,
                        )
                    )
                session.merge(
                    ItemPrice(
                        item_id=9242,
                        high_price_gp=100,
                        low_price_gp=100,
                        high_trade_at=now,
                        low_trade_at=now,
                        fetched_at=now,
                        provider="deterministic-browser-fixture",
                        source=PriceSourceLayer.CACHED,
                    )
                )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-powered")
        def seed_powered():
            seed_running_cost()
            app.state.gear_service._equipment = EquipmentCatalog(
                {i: original_catalog.items[i] for i in (28583, 28585)},
                revision="browser-powered-v1",
            )
            now = datetime.now(UTC)
            with factory() as session:
                player = session.query(Player).first()
                session.add(
                    ObservedItem(
                        player_id=player.id,
                        item_id=28583,
                        quantity=1,
                        container=Container.BANK,
                        source=Source.RUNELITE,
                        observed_at=now,
                    )
                )
                session.commit()
            return {"status": "seeded"}

        @app.post("/test/seed-powered-purchase")
        def seed_powered_purchase():
            seed_powered()
            now = datetime.now(UTC)
            with factory() as session:
                session.execute(delete(ObservedItem).where(ObservedItem.item_id == 28583))
                session.merge(
                    ItemPrice(
                        item_id=28583,
                        high_price_gp=1000,
                        low_price_gp=900,
                        high_trade_at=now,
                        low_trade_at=now,
                        fetched_at=now,
                        provider="deterministic-browser-fixture",
                        source=PriceSourceLayer.CACHED,
                    )
                )
                session.commit()
            return {"status": "seeded"}

        _mount_ui(app, app.state.settings)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ.get("GEAR_E2E_PORT", "8766")),
            log_level="warning",
        )
