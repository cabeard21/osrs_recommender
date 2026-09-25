"""Four read-only tools. Every result comes from transport-independent services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from tracker.mcp.accounts import SnapshotProvider
from tracker.mcp.settings import MCPSettings
from tracker.quest_cape.service import (
    Action,
    ActionEvaluation,
    ActionType,
    AvailableActions,
    GoalStatus,
    QuestCapeService,
)


def build_server(accounts: SnapshotProvider, quests: QuestCapeService) -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(
        "OSRS Account Companion",
        instructions="Tools return deterministic observations, not guaranteed current state. "
        "Read get_account_summary first; account facts describe the snapshot as of last_sync_at "
        "(individual observations may be older). Acknowledge that time in account-state advice. "
        "For advice depending on an observed quest, skill, or account state, treat the state as "
        "observed at last_sync_at, not necessarily true now. Observed incomplete as of "
        "last_sync_at is not known incomplete now, including not_started observations. "
        "A non-null last_sync_at does not establish that no gameplay occurred afterward. "
        "When recommending an action inferred from incomplete progress, phrase it conditionally: "
        "'As of the last sync, Regicide was not started. If you haven't completed it since then, "
        "...' Ask the user to sync or confirm progress when needed. "
        "If last_sync_at is null, say the sync time is unknown and avoid current-state claims. "
        "Use get_goal_status with quest_ids=[] for compact "
        "Cape totals and blockers. available_now counts available Cape-counting quests; "
        "get_available_actions includes goal-advancing prerequisites too. Follow "
        "next_action_offset or filter by action_type and skill; discovery order is not preference "
        "order. For what-to-do-next recommendations, evaluate more than one meaningful candidate "
        "when practical, then use the counterfactual deltas to make and explain your own choice. "
        "evaluate_action is hypothetical and never saves changes. No XP rewards, item rewards, "
        "costs, or elapsed time are simulated. Distinguish these MCP facts from general OSRS "
        "knowledge and qualitative tradeoffs; do not attribute unsimulated efficiency "
        "to the tools.",
    )
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=annotations)
    def get_account_summary() -> dict[str, Any]:
        """Observed account facts and timestamps, not guaranteed current state.

        Check last_sync_at before advising. Quest and skill observations can be older;
        gameplay after the last sync is not represented. Missing data is unknown.
        """
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

        Start with quest_ids=[] for compact whole-goal totals and skill blockers without
        quest detail trees. available_now counts incomplete Cape-counting quests that are
        available, not every available goal-advancing prerequisite action. Supply specific
        quest_ids for detail, or follow next_quest_offset to scan more catalog details.
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
    def get_available_actions(
        goal: str = "quest_cape",
        action_type: Annotated[
            ActionType | None,
            Field(description="Optional action kind: complete_quest or train_skill."),
        ] = None,
        skill: Annotated[
            str | None,
            Field(description="Optional canonical skill ID; returns only its training actions."),
        ] = None,
        action_offset: Annotated[
            int,
            Field(ge=0, description="Offset into the filtered, quest-first action list."),
        ] = 0,
        action_limit: Annotated[
            int,
            Field(ge=1, le=100, description="Maximum actions on this page; defaults to 50."),
        ] = 50,
    ) -> AvailableActions:
        """Deterministic action discovery, ordered by quest name then skill and level.

        A no-argument call returns the first page, not the complete available-action set.
        quest_actions includes goal-advancing prerequisites and subquests; counts_for_cape
        marks which independently count toward the Cape total. Submit only type and quest
        when passing a discovered quest to evaluate_action. actions_total counts all
        matching actions after action_type/skill filters but before pagination, so it can
        differ from available_now. If next_action_offset is not null, request another page
        using that offset, or narrow with action_type and skill. A null next_action_offset
        means the filtered result is exhausted. Order is not a recommendation ranking.
        """
        return quests.get_available_actions(
            accounts.get_snapshot(),
            goal,
            action_type=action_type,
            skill=skill,
            action_offset=action_offset,
            action_limit=action_limit,
        )

    @server.tool(annotations=annotations)
    def evaluate_action(
        action: Action,
        goal: str = "quest_cape",
        expected_snapshot_id: str | None = None,
    ) -> ActionEvaluation:
        """Hypothetical read-only impact of completing a quest or training; never saves changes.

        For recommendation requests, compare more than one plausible action when practical.
        The server supplies requirement and availability deltas, not a choice of best action.
        No XP rewards, item rewards, costs, or elapsed time are simulated; distinguish any
        general OSRS reasoning from these results. Pass the snapshot_id from earlier results
        to detect intervening account changes.
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
