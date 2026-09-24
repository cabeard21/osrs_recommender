"""Four read-only tools. Every result comes from transport-independent services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from tracker.mcp.accounts import SnapshotProvider
from tracker.mcp.settings import MCPSettings
from tracker.quest_cape.service import (
    Action,
    ActionEvaluation,
    AvailableActions,
    GoalStatus,
    QuestCapeService,
)


def build_server(accounts: SnapshotProvider, quests: QuestCapeService) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        "OSRS Account Companion",
        instructions="Tools return deterministic account facts. You choose and explain next steps. "
        "evaluate_action is hypothetical and never changes the account.",
    )
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=annotations)
    def get_account_summary() -> dict[str, Any]:
        """Observed account facts and timestamps. Missing data is unknown; no recommendations."""
        account = accounts.get_snapshot()
        return {**account.summary(), "snapshot_id": account.fingerprint}

    @server.tool(annotations=annotations)
    def get_goal_status(
        goal: str = "quest_cape",
        quest_offset: int = 0,
        quest_limit: int = 20,
        quest_ids: list[str] | None = None,
    ) -> GoalStatus:
        """Deterministic Quest Cape totals and thresholds, plus a page of quest explanations.

        Follow next_quest_offset for more details, or supply quest_ids to inspect actions.
        Counts and skill blockers always cover the whole goal, independent of pagination.
        """
        return quests.get_goal_status(
            accounts.get_snapshot(),
            goal,
            quest_offset=quest_offset,
            quest_limit=quest_limit,
            quest_ids=quest_ids,
        )

    @server.tool(annotations=annotations)
    def get_available_actions(goal: str = "quest_cape") -> AvailableActions:
        """Available quests and useful skill thresholds in presentation order, without ranking."""
        return quests.get_available_actions(accounts.get_snapshot(), goal)

    @server.tool(annotations=annotations)
    def evaluate_action(
        action: Action,
        goal: str = "quest_cape",
        expected_snapshot_id: str | None = None,
    ) -> ActionEvaluation:
        """Hypothetical read-only impact of completing a quest or training; never saves changes.

        The server supplies facts and counterfactuals, not a choice of best action.
        Pass the snapshot_id from earlier results to detect intervening account changes.
        """
        return quests.evaluate_action(accounts.get_snapshot(), action, goal, expected_snapshot_id)

    return server


def create_http_app(server: MCPServer[Any], settings: MCPSettings) -> Starlette:
    if not settings.enabled:
        raise ValueError("MCP is disabled; explicitly set mcp.enabled and mcp.player_id")
    address = settings.bind_address
    host = f"[{address}]" if ":" in address else address
    # Wildcard bind addresses are interfaces, never trusted request hostnames.
    hosts = ["127.0.0.1", "[::1]", "localhost", *settings.allowed_hostnames]
    if address not in ("0.0.0.0", "::"):
        hosts = [*hosts, host]
    sdk_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[f"{name}:*" for name in hosts],
            allowed_origins=[f"http://{name}:*" for name in hosts],
        ),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # Nested ASGI apps do not receive lifespan events automatically.
        async with sdk_app.router.lifespan_context(sdk_app):
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/mcp", endpoint=sdk_app),
            # Handle misses directly, outside SDK transport and exception handling.
            # No body read, stream, OAuth metadata, or application routes here.
            Mount("/", app=PlainTextResponse("Not Found", status_code=404)),
        ],
    )
