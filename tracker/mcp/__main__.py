"""Private MCP sidecar: python -m tracker.mcp. Never mounts the dashboard or sync API."""

import uvicorn

from tracker.accounts.service import AccountService
from tracker.config.settings import load_settings
from tracker.content.loader import load_content
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.db.session import build_engine, build_session_factory
from tracker.gear.service import GearService
from tracker.mcp.accounts import ConfiguredAccount
from tracker.mcp.server import build_server, create_http_app
from tracker.quest_cape.catalog import load_catalog
from tracker.quest_cape.service import QuestCapeService


def main() -> None:
    settings = load_settings()
    if not settings.mcp.enabled or settings.mcp.player_id is None:
        raise SystemExit("MCP is disabled. Set mcp.enabled=true and mcp.player_id explicitly.")
    engine = build_engine(settings.database_url)
    try:
        sessions = build_session_factory(engine)
        account = ConfiguredAccount(AccountService(sessions), settings.mcp.player_id)
        account.get_snapshot()  # Fail before listening if the configured player does not exist.
        quests = QuestCapeService(load_catalog(settings.content_dir / "quest_cape/catalog.json"))
        gear = GearService(
            load_content(settings.content_dir, profile_path=settings.scoring_profile_path)
        )
        app = create_http_app(
            build_server(account, quests, gear, DatabaseGearPrices(sessions)), settings.mcp
        )
        uvicorn.run(
            app, host=settings.mcp.bind_address, port=settings.mcp.port, proxy_headers=False
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
