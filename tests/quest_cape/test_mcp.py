import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.applications import Starlette

from tracker.mcp.accounts import ConfiguredAccount
from tracker.mcp.server import build_server, create_http_app
from tracker.mcp.settings import MCPSettings
from tracker.quest_cape.service import CompleteQuest


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-protected-resource",
        "/",
        "/healthz",
        "/api/sync",
        "/dashboard",
        "/unknown",
        "/mcp/",
        "/mcp/unknown",
    ],
)
def test_non_mcp_paths_return_without_entering_sdk(monkeypatch, service, snapshot, path):
    class Account:
        def get_snapshot(self):
            return snapshot

    class WaitingSDKApp(Starlette):
        async def __call__(self, scope, receive, send):
            await asyncio.Event().wait()

    server = build_server(Account(), service)
    monkeypatch.setattr(server, "streamable_http_app", lambda **kwargs: WaitingSDKApp())
    app = create_http_app(server, MCPSettings(enabled=True, player_id=42))

    async def request():
        messages = []

        async def receive():
            # A routing miss must not need a request body or client disconnect.
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        await asyncio.wait_for(
            app(
                {
                    "type": "http",
                    "method": "GET",
                    "path": path,
                    "root_path": "",
                    "headers": [],
                    "query_string": b"",
                },
                receive,
                send,
            ),
            timeout=1,
        )
        assert messages[0]["status"] == 404
        assert messages[1]["body"] == b"Not Found"
        assert not messages[1].get("more_body", False)

    asyncio.run(request())


def test_live_http_discovery_404_and_mcp_post(service, snapshot):
    class Account:
        def get_snapshot(self):
            return snapshot

    app = create_http_app(build_server(Account(), service), MCPSettings(enabled=True, player_id=42))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "MCP listener did not start"
            with httpx.Client(
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                timeout=2,
                trust_env=False,
            ) as client:
                for path in [
                    "/.well-known/oauth-protected-resource/mcp",
                    "/.well-known/oauth-protected-resource",
                    "/",
                    "/healthz",
                    "/api/sync",
                    "/unknown",
                    "/mcp/unknown",
                ]:
                    response = client.get(path)
                    assert response.status_code == 404
                    assert response.text == "Not Found"
                response = client.post(
                    "/mcp",
                    headers={"Accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
                assert response.status_code == 200, response.text
                assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
                    "get_account_summary",
                    "get_goal_status",
                    "get_available_actions",
                    "evaluate_action",
                }
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive(), "MCP listener did not stop"


def test_http_tools_delegate_and_use_configured_account(service, snapshot):
    calls = []

    class Accounts:
        def get_snapshot(self, player_id):
            calls.append(player_id)
            assert player_id == 42
            return snapshot

    account = ConfiguredAccount(Accounts(), 42)
    server = build_server(account, service)
    settings = MCPSettings(enabled=True, player_id=42)
    app = create_http_app(server, settings)
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(app, base_url="http://127.0.0.1:8503") as client:
        assert client.get("/").status_code == 404
        assert client.post("/api/sync").status_code == 404
        assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 404

        def rpc(method, params=None):
            response = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params or {},
                },
            )
            assert response.status_code == 200, response.text
            return response.json()["result"]

        initialized = rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert "tools" in initialized["capabilities"]
        tools = rpc("tools/list")["tools"]
        assert {t["name"] for t in tools} == {
            "get_account_summary",
            "get_goal_status",
            "get_available_actions",
            "evaluate_action",
        }
        assert all(t["annotations"]["readOnlyHint"] for t in tools)
        assert all("player_id" not in t["inputSchema"].get("properties", {}) for t in tools)
        assert all("outputSchema" in t for t in tools)
        for name, arguments, expected in [
            (
                "get_goal_status",
                {},
                service.get_goal_status(snapshot, quest_limit=20).model_dump(mode="json"),
            ),
            (
                "get_available_actions",
                {},
                service.get_available_actions(snapshot).model_dump(mode="json"),
            ),
            (
                "evaluate_action",
                {"action": {"type": "complete_quest", "quest": "a"}},
                service.evaluate_action(
                    snapshot, CompleteQuest(type="complete_quest", quest="a")
                ).model_dump(mode="json"),
            ),
        ]:
            result = rpc("tools/call", {"name": name, "arguments": arguments})
            assert not result.get("isError"), result
            assert result["structuredContent"] == expected
        summary = rpc("tools/call", {"name": "get_account_summary"})
        assert summary["structuredContent"]["snapshot_id"] == snapshot.fingerprint
        # A forged player argument must either be rejected or ignored; it must never
        # reach the account service. SDK versions may differ on extra argument policy.
        rpc("tools/call", {"name": "get_account_summary", "arguments": {"player_id": 99}})
        assert set(calls) == {42}
        bad = rpc(
            "tools/call", {"name": "evaluate_action", "arguments": {"action": {"type": "write"}}}
        )
        assert bad["isError"]
        rejected = client.post(
            "/mcp", headers={**headers, "Origin": "https://attacker.example"}, json={}
        )
        assert rejected.status_code == 403


def test_disabled_and_private_defaults(service, snapshot):
    class Account:
        def get_snapshot(self):
            return snapshot

    defaults = MCPSettings()
    assert not defaults.enabled
    assert defaults.bind_address == "127.0.0.1"
    assert defaults.port == 8503
    assert "api_token" not in MCPSettings.model_fields
    with pytest.raises(ValueError, match="disabled"):
        create_http_app(build_server(Account(), service), defaults)
    with pytest.raises(ValueError, match="player_id"):
        MCPSettings(enabled=True)


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "8.8.8.8", "public.example"])
def test_public_and_wildcard_binding_rejected(address):
    with pytest.raises(ValueError):
        MCPSettings(bind_address=address)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "192.168.1.10", "100.100.1.10"])
def test_private_binding_configurable(address):
    assert MCPSettings(bind_address=address).bind_address == address


def test_config_environment_and_sync_token_separation(monkeypatch, tmp_path):
    from tracker.config.settings import Settings

    monkeypatch.setenv("TRACKER_CONFIG_FILE", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("TRACKER_MCP__ENABLED", "true")
    monkeypatch.setenv("TRACKER_MCP__PLAYER_ID", "42")
    config = Settings(bind_address="127.0.0.1", api_token="fixture-sync-token")
    assert config.mcp.enabled
    assert config.mcp.player_id == 42
    assert "fixture-sync-token" not in config.mcp.model_dump_json()
    assert not config.mcp.allow_all_interfaces
    with pytest.raises(ValueError, match=r"mcp\.allow_all_interfaces"):
        Settings(
            bind_address="0.0.0.0",
            allow_all_interfaces=True,
            mcp={"bind_address": "0.0.0.0"},
        )


def test_disabled_entrypoint_never_opens_database(monkeypatch):
    from types import SimpleNamespace

    from tracker.mcp import __main__ as entrypoint

    monkeypatch.setattr(entrypoint, "load_settings", lambda: SimpleNamespace(mcp=MCPSettings()))

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled MCP opened database")

    monkeypatch.setattr(entrypoint, "build_engine", forbidden)
    with pytest.raises(SystemExit, match="disabled"):
        entrypoint.main()


@pytest.mark.parametrize("address", ["0.0.0.0", "::"])
def test_container_binding_requires_mcp_opt_in(address):
    assert MCPSettings(bind_address=address, allow_all_interfaces=True).bind_address == address


def test_opt_in_does_not_allow_public_address():
    with pytest.raises(ValueError):
        MCPSettings(bind_address="8.8.8.8", allow_all_interfaces=True)


@pytest.mark.parametrize(
    "hostname",
    ["*", "*.example", "http://osrs-mcp", "osrs-mcp:8503", "bad/name", "bad name", "-bad", ""],
)
def test_extra_hostnames_are_exact_dns_names(hostname):
    with pytest.raises(ValueError):
        MCPSettings(allowed_hostnames=[hostname])


def test_docker_hostname_transport_security(service, snapshot):
    class Account:
        def get_snapshot(self):
            return snapshot

    settings = MCPSettings(
        enabled=True,
        player_id=42,
        bind_address="0.0.0.0",
        allow_all_interfaces=True,
        allowed_hostnames=["osrs-mcp"],
    )
    app = create_http_app(build_server(Account(), service), settings)
    with TestClient(app, base_url="http://osrs-mcp:8503") as client:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        headers = {"Accept": "application/json, text/event-stream"}
        assert (
            client.post(
                "/mcp", headers={**headers, "Origin": "http://osrs-mcp:8503"}, json=payload
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/mcp", headers={**headers, "Host": "evil.example:8503"}, json=payload
            ).status_code
            == 421
        )
        assert (
            client.post(
                "/mcp", headers={**headers, "Origin": "http://evil.example:8503"}, json=payload
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/mcp", headers={**headers, "Host": "127.0.0.1:8503"}, json=payload
            ).status_code
            == 200
        )
