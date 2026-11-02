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
from tracker.db.models import Base, ContainerScan, ItemPrice, ObservedItem, Player, SkillSnapshot
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Container, PriceSourceLayer, Source
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
        original_catalog = app.state.gear_service.equipment_catalog()

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
                for skill in ("attack", "strength", "defence", "ranged", "magic", "hitpoints"):
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

        _mount_ui(app, app.state.settings)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ.get("GEAR_E2E_PORT", "8766")),
            log_level="warning",
        )
