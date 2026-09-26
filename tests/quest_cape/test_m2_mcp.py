"""The additive gear tools stay on the configured account and exact MCP route."""

from fastapi.testclient import TestClient

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.service import GearService
from tracker.mcp.server import build_server, create_http_app
from tracker.mcp.settings import MCPSettings


def test_gear_tools_delegate_with_fresh_snapshot_and_cached_prices(service, snapshot):
    snapshots = []
    calls = []

    class Accounts:
        def get_snapshot(self):
            snapshots.append(snapshot)
            return snapshot

    class Prices:
        def get_prices(self):
            return {}

    class Gear:
        def progression(self, account, **kwargs):
            calls.append(("progression", account, kwargs))
            return {"snapshot_id": account.fingerprint, "items": [], "total": 0}

        def candidates(self, account, **kwargs):
            calls.append(("candidates", account, kwargs))
            return {"snapshot_id": account.fingerprint, "items": [], "total": 0}

        def item_details(self, account, **kwargs):
            calls.append(("details", account, kwargs))
            return {"snapshot_id": account.fingerprint, "items": []}

        def evaluate_change(self, account, **kwargs):
            calls.append(("evaluate", account, kwargs))
            return {
                "snapshot_id": account.fingerprint,
                "joint_loadout_validity": "not_evaluated",
                "items": [],
            }

    app = create_http_app(
        build_server(Accounts(), service, Gear(), Prices()),
        MCPSettings(enabled=True, player_id=42),
    )
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://127.0.0.1:8503") as client:

        def rpc(method, params=None):
            response = client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            )
            assert response.status_code == 200, response.text
            return response.json()["result"]

        tools = rpc("tools/list")["tools"]
        assert {tool["name"] for tool in tools} == {
            "get_account_summary",
            "get_goal_status",
            "get_available_actions",
            "evaluate_action",
            "get_gear_progression",
            "get_gear_candidates",
            "get_item_details",
            "evaluate_gear_change",
        }
        assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
        for name, arguments in (
            ("get_gear_progression", {"style": "ranged", "limit": 1}),
            ("get_gear_candidates", {"style": "ranged", "ownership": "unknown"}),
            ("get_item_details", {"content_id": "fixture_item"}),
            (
                "evaluate_gear_change",
                {
                    "style": "ranged",
                    "changes": [{"slot": "weapon", "content_id": "fixture_item"}],
                    "expected_snapshot_id": snapshot.fingerprint,
                },
            ),
        ):
            result = rpc("tools/call", {"name": name, "arguments": arguments})
            assert not result.get("isError"), result
            assert result["structuredContent"]["snapshot_id"] == snapshot.fingerprint
        assert [call[0] for call in calls] == ["progression", "candidates", "details", "evaluate"]
        assert len(snapshots) == 4
        assert calls[-1][2]["expected_snapshot_id"] == snapshot.fingerprint
        assert calls[-1][2]["price_records"] == {}
        assert rpc(
            "tools/call",
            {"name": "evaluate_gear_change", "arguments": {"style": "ranged", "changes": []}},
        )["isError"]
        assert client.get("/gear").status_code == 404


def test_real_catalog_ava_requirement_survives_mcp_serialization(service):
    from datetime import UTC, datetime

    at = datetime(2026, 9, 25, tzinfo=UTC)
    snapshot = AccountSnapshot(
        player_id=1,
        username="Rehvun fixture",
        skills={"ranged": SkillState(38, None, Source.RUNELITE, at)},
        quests={"animal_magnetism": QuestStatus.COMPLETE},
        observed_items={
            (10498, Container.BANK): ObservedItemFact(10498, Container.BANK, 1, "runelite", at)
        },
        container_scans={
            container: ContainerScanFact(container, at, "runelite") for container in Container
        },
    )

    class Accounts:
        def get_snapshot(self):
            return snapshot

    class Prices:
        def get_prices(self):
            return {}

    app = create_http_app(
        build_server(Accounts(), service, GearService(load_content()), Prices()),
        MCPSettings(enabled=True, player_id=1),
    )
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://127.0.0.1:8503") as client:

        def call(name, arguments):
            response = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            assert response.status_code == 200
            result = response.json()["result"]
            assert not result.get("isError"), result
            return result["structuredContent"]

        proposal = call(
            "evaluate_gear_change",
            {"style": "ranged", "changes": [{"slot": "cape", "content_id": "avas_accumulator"}]},
        )["items"][0]
        assert proposal["wear"]["status"] == "unsatisfied"
        assert proposal["wear"]["requirements"]["current"] == 38
        assert proposal["wear"]["unmet"][0]["required"] == 50
        assert proposal["ownership"]["status"] == "unowned"

        satisfied = call(
            "get_gear_candidates",
            {"style": "ranged", "slot": "cape", "wear_status": "satisfied"},
        )
        unsatisfied = call(
            "get_gear_candidates",
            {"style": "ranged", "slot": "cape", "wear_status": "unsatisfied"},
        )
        assert "avas_accumulator" not in {item["content_id"] for item in satisfied["items"]}
        assert "avas_accumulator" in {item["content_id"] for item in unsatisfied["items"]}

        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_item_details",
                    "arguments": {"content_id": "yew_shortbow"},
                },
            },
        )
        assert response.status_code == 200
        error = response.json()["result"]
        assert error["isError"] is True
        assert "unknown content_id: yew_shortbow" in error["content"][0]["text"]
