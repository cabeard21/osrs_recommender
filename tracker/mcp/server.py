"""Read-only Account Companion tools backed by transport-independent services."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from tracker.accounts.snapshot import AccountSnapshot
from tracker.estimation.prices import PriceRecord
from tracker.gear.optimizer import OptimizationRequest
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

GearStyle = Literal["melee", "ranged", "magic"]
OwnershipFilter = Literal["owned", "unowned", "unknown"]
WearFilter = Literal["satisfied", "unsatisfied", "unknown"]
AcquisitionFilter = Literal["tradeable", "untradeable", "unknown"]


class GearChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    slot: str
    content_id: str


class GearToolService(Protocol):
    def optimize(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest,
        *,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def optimizer_catalog(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str | None = None,
        slot: str | None = None,
        ownership: str | None = None,
        wear_status: str | None = None,
        acquisition: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def progression(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str,
        slot: str | None = None,
        offset: int = 0,
        limit: int = 50,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def candidates(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str,
        slot: str | None = None,
        ownership: str | None = None,
        wear_status: str | None = None,
        acquisition: str | None = None,
        offset: int = 0,
        limit: int = 50,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def item_details(
        self,
        snapshot: AccountSnapshot,
        *,
        content_id: str | None = None,
        numeric_item_id: int | None = None,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...

    def evaluate_change(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str,
        changes: Sequence[Mapping[str, str]],
        expected_snapshot_id: str | None = None,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


class GearPriceProvider(Protocol):
    def get_prices(self) -> Mapping[int, PriceRecord]: ...


def build_server(
    accounts: SnapshotProvider,
    quests: QuestCapeService,
    gear: GearToolService | None = None,
    prices: GearPriceProvider | None = None,
) -> MCPServer[Any]:
    if (gear is None) != (prices is None):
        raise ValueError("gear service and price provider must be configured together")
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
        "to the tools. Legacy gear progression is editorial order, not DPS. "
        "Use optimize_gear for complete compatible loadouts, directional equipment actions, "
        "inventory constraints and a swap curve. Its bounded best-found results are not "
        "globally optimal claims. Read supported mechanics, assumptions and limitations. "
        "Special roles are unscored unless explicitly supported. Use optimizer catalog "
        "browsing to inspect locked or unsupported equipment. "
        "Ownership is dated: unowned means absent in each container's latest accepted scan, "
        "which may be old or taken at different times. evaluate_gear_change does not check "
        "joint loadout validity, replaced items, or combat stat deltas.",
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

    if gear is not None and prices is not None:

        @server.tool(annotations=annotations)
        async def optimize_gear(request: OptimizationRequest) -> dict[str, Any]:
            """Find compatible account-aware equipment and a bounded swap-efficiency curve.

            Equipment actions include explicit unequips; automatic removals are not extra
            actions. Time-share DPS is a supported-mechanics proxy, not predicted kill time.
            Future assumptions are request-local. Inspect limitations and search quality.
            """
            account = accounts.get_snapshot()
            records = prices.get_prices()
            evaluated_at = datetime.now(UTC)
            try:
                return await asyncio.to_thread(
                    gear.optimize, account, request, price_records=records, now=evaluated_at
                )
            except ValueError as exc:
                raise ToolError(str(exc)) from exc

        @server.tool(annotations=annotations)
        def get_gear_progression(
            style: GearStyle,
            slot: str | None = None,
            offset: Annotated[int, Field(ge=0)] = 0,
            limit: Annotated[int, Field(ge=1, le=100)] = 50,
        ) -> dict[str, Any]:
            """Curated style/slot progression facts, in authored order, never a best-item choice.

            Ownership and equipment-container sightings are dated observations. A page may
            omit rungs; follow next_offset for the remainder.
            """
            return gear.progression(
                accounts.get_snapshot(),
                style=style,
                slot=slot,
                offset=offset,
                limit=limit,
                price_records=prices.get_prices(),
                now=datetime.now(UTC),
            )

        @server.tool(annotations=annotations)
        def get_gear_candidates(
            style: GearStyle,
            slot: str | None = None,
            ownership: OwnershipFilter | None = None,
            wear_status: WearFilter | None = None,
            acquisition: AcquisitionFilter | None = None,
            offset: Annotated[int, Field(ge=0)] = 0,
            limit: Annotated[int, Field(ge=1, le=100)] = 50,
            catalog: Literal["authored", "optimizer"] = "authored",
        ) -> dict[str, Any]:
            """Browse dated item facts; optimizer catalog includes locked/unsupported gear.

            The authored catalog is retained for compatibility. Neither browsing order
            is a performance ranking; use optimize_gear for complete setups.
            """
            if catalog == "optimizer":
                return gear.optimizer_catalog(
                    accounts.get_snapshot(),
                    style=style,
                    slot=slot,
                    ownership=ownership,
                    wear_status=wear_status,
                    acquisition=acquisition,
                    offset=offset,
                    limit=limit,
                    price_records=prices.get_prices(),
                    now=datetime.now(UTC),
                )
            return gear.candidates(
                accounts.get_snapshot(),
                style=style,
                slot=slot,
                ownership=ownership,
                wear_status=wear_status,
                acquisition=acquisition,
                offset=offset,
                limit=limit,
                price_records=prices.get_prices(),
                now=datetime.now(UTC),
            )

        @server.tool(annotations=annotations)
        def get_item_details(
            content_id: str | None = None,
            numeric_item_id: Annotated[int | None, Field(gt=0)] = None,
        ) -> dict[str, Any]:
            """Catalog memberships, requirements, ownership and cached price for one ID.

            Supply exactly one identifier. Numeric IDs can match several authored entries;
            the result reports all matches rather than guessing a style.
            """
            try:
                return gear.item_details(
                    accounts.get_snapshot(),
                    content_id=content_id,
                    numeric_item_id=numeric_item_id,
                    price_records=prices.get_prices(),
                    now=datetime.now(UTC),
                )
            except ValueError as exc:
                raise ToolError(str(exc)) from exc

        @server.tool(annotations=annotations)
        def evaluate_gear_change(
            style: GearStyle,
            changes: Annotated[Sequence[GearChange], Field(min_length=1, max_length=5)],
            expected_snapshot_id: str | None = None,
        ) -> dict[str, Any]:
            """Read-only facts and known purchase cost for 1–5 proposed catalog items.

            A successful response explicitly says joint_loadout_validity=not_evaluated.
            It does not establish that the proposed items can be worn together, identify
            replaced gear, or calculate combat-stat or DPS changes.
            """
            return gear.evaluate_change(
                accounts.get_snapshot(),
                style=style,
                changes=[change.model_dump() for change in changes],
                expected_snapshot_id=expected_snapshot_id,
                price_records=prices.get_prices(),
                now=datetime.now(UTC),
            )

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
