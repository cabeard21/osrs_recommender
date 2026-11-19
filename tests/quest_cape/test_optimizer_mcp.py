"""The optimizer uses the same service on MCP and the dashboard."""

from fastapi.testclient import TestClient

from tracker.mcp.server import build_server, create_http_app
from tracker.mcp.settings import MCPSettings


def test_optimizer_tool_delegates_and_rejects_invalid_requests(service, snapshot):
    calls = []

    class Accounts:
        def get_snapshot(self):
            return snapshot

    class Prices:
        def get_prices(self):
            return {}

    class Gear:
        def optimize(self, account, request, **kwargs):
            calls.append((account, request, kwargs))
            if request.objectives:
                return {"objective_frontiers": [{"points": iter([{"id": "cost-point"}])}]}
            if request.expected_snapshot_id == "old":
                raise ValueError("snapshot_changed: refresh account facts")
            return {
                "snapshot_id": account.fingerprint,
                "search": {"quality": "best_found"},
                "selected_solution": {
                    "loadouts": {
                        "melee": {
                            "combat_option": {
                                "attack_type": "slash",
                                "stance": "aggressive",
                                "spell": None,
                                "powered_attack": None,
                            }
                        }
                    }
                },
            }

    app = create_http_app(
        build_server(Accounts(), service, Gear(), Prices()), MCPSettings(enabled=True, player_id=1)
    )
    with TestClient(app, base_url="http://127.0.0.1:8503") as client:

        def call(request):
            response = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "optimize_gear", "arguments": {"request": request}},
                },
            )
            assert response.status_code == 200
            return response.json()["result"]

        result = call({"roles": [{"id": "melee", "style": "slash"}], "budget_gp": 100})
        assert not result.get("isError"), result
        assert result["structuredContent"]["snapshot_id"] == snapshot.fingerprint
        assert result["structuredContent"]["selected_solution"]["loadouts"]["melee"][
            "combat_option"
        ] == {
            "attack_type": "slash",
            "stance": "aggressive",
            "spell": None,
            "powered_attack": None,
        }
        cost = call(
            {
                "roles": [{"id": "melee", "style": "slash"}],
                "objectives": [{"kind": "gp_per_damage"}],
            }
        )
        assert cost["structuredContent"]["objective_frontiers"][0]["points"] == [
            {"id": "cost-point"}
        ]
        assert calls[0][0] is snapshot
        assert calls[0][1].budget_gp == 100
        assert calls[0][2]["price_records"] == {}
        assert calls[0][2]["now"].tzinfo is not None
        filtered = call(
            {
                "roles": [
                    {
                        "id": "melee",
                        "style": "slash",
                        "combat_options": {
                            "attack_types": ["slash"],
                            "stances": ["aggressive"],
                            "spells": [],
                        },
                    }
                ]
            }
        )
        assert not filtered.get("isError"), filtered
        assert tuple(calls[-1][1].roles[0].combat_options.attack_types) == ("slash",)
        assert tuple(calls[-1][1].roles[0].combat_options.stances) == ("aggressive",)
        assert tuple(calls[-1][1].roles[0].combat_options.spells) == ()
        assert call({"roles": []})["isError"]
        assert call({"roles": [{"id": "melee", "style": "slash"}], "budget_gp": -1})["isError"]
        stale = call({"roles": [{"id": "melee", "style": "slash"}], "expected_snapshot_id": "old"})
        assert stale["isError"]
        assert "snapshot_changed" in str(stale)
