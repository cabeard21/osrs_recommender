"""Keep the image smoke probe aligned with the production MCP contract."""

from __future__ import annotations

import json
from io import BytesIO
from urllib import error, request

from tools.container_smoke import PROBE
from tracker.mcp.healthcheck import EXPECTED_TOOLS


def test_container_probe_accepts_complete_mcp_tool_set(monkeypatch) -> None:
    def urlopen(target: request.Request | str, timeout: int) -> BytesIO:
        assert timeout == 2
        url = target.full_url if isinstance(target, request.Request) else target
        if url.endswith("/mcp"):
            assert isinstance(target, request.Request)
            method = json.loads(target.data)["method"]
            result = (
                {"tools": [{"name": name} for name in sorted(EXPECTED_TOOLS)]}
                if method == "tools/list"
                else {"content": [{"type": "text", "text": "container_smoke"}]}
            )
            return BytesIO(json.dumps({"result": result}).encode())
        raise error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(request, "urlopen", urlopen)
    exec(PROBE, {})
