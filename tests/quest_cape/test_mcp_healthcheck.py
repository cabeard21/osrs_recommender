"""Health probe exercises the private MCP transport without reading account state."""

import httpx
import pytest

from tracker.mcp import healthcheck


@pytest.mark.parametrize(
    "tool_names",
    [
        {
            "get_account_summary",
            "get_goal_status",
            "get_available_actions",
            "evaluate_action",
            "get_gear_progression",
            "get_gear_candidates",
            "get_item_details",
            "evaluate_gear_change",
            "optimize_gear",
        },
    ],
)
def test_probe_validates_tools(tool_names):
    def respond(request):
        assert request.url.path == "/mcp"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"tools": [{"name": n} for n in tool_names]},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        healthcheck.probe("http://127.0.0.1:8503/mcp", client=client)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": {"tools": []}},
        {"result": {"tools": [{"name": "other"}]}},
        {"result": {"tools": [{"name": n} for n in healthcheck.BASE_TOOLS]}},
        {"result": {"tools": [{"name": n} for n in healthcheck.BASE_TOOLS | {"get_item_details"}]}},
        {"result": {"tools": [{"name": n} for n in healthcheck.BASE_TOOLS] * 2}},
        {"result": {"tools": None}},
        {"result": {"tools": [None]}},
    ],
)
def test_probe_rejects_invalid_tools(payload):
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ) as client,
        pytest.raises(ValueError),
    ):
        healthcheck.probe("http://127.0.0.1:8503/mcp", client=client)


def test_probe_rejects_http_error():
    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        healthcheck.probe("http://127.0.0.1:8503/mcp", client=client)


def test_cli_success(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(healthcheck, "probe", lambda url: calls.append(url))
    assert healthcheck.main([]) == 0
    assert calls == ["http://127.0.0.1:8503/mcp"]
    assert "ready" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error", [ValueError("secret"), httpx.ConnectError("secret"), httpx.ReadTimeout("secret")]
)
def test_cli_failure_is_sanitized(monkeypatch, capsys, error):
    def fail(url):
        raise error

    monkeypatch.setattr(healthcheck, "probe", fail)
    assert healthcheck.main(["--url", "http://osrs-mcp:8503/mcp"]) == 1
    assert "secret" not in capsys.readouterr().err
