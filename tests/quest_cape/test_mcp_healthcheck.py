"""Health probe exercises the private MCP transport without reading account state."""

import httpx
import pytest

from tracker.mcp import healthcheck


def test_probe_validates_tools():
    def respond(request):
        assert request.url.path == "/mcp"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"tools": [{"name": n} for n in healthcheck.EXPECTED_TOOLS]},
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
