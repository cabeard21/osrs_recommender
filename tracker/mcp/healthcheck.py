"""Bounded MCP protocol healthcheck; never invokes account tools."""

from __future__ import annotations

import argparse
import sys

import httpx

EXPECTED_TOOLS = frozenset(
    {"get_account_summary", "get_goal_status", "get_available_actions", "evaluate_action"}
)


def probe(url: str, *, client: httpx.Client | None = None) -> None:
    """Require a successful tools/list response with exactly the Milestone 1 tools."""
    if client is None:
        with httpx.Client(timeout=3, trust_env=False) as owned_client:
            probe(url, client=owned_client)
        return
    response = client.post(
        url,
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        timeout=3,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        tools = payload["result"]["tools"]
        names = [tool["name"] for tool in tools]
        valid = len(names) == len(EXPECTED_TOOLS) and set(names) == EXPECTED_TOOLS
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ValueError("MCP tool contract is unavailable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8503/mcp")
    args = parser.parse_args(argv)
    try:
        probe(args.url)
    except (httpx.HTTPError, ValueError):
        print("MCP not ready", file=sys.stderr)
        return 1
    print("MCP ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
