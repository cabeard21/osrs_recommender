"""Exercise the built image with disposable Docker storage; never uses local account data."""

from __future__ import annotations

import subprocess
import sys
import time
import uuid


def docker(*arguments: str) -> str:
    return subprocess.check_output(["docker", *arguments], text=True).strip()


def wait_for(container: str, code: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container, "python", "-c", code], capture_output=True, text=True
        )
        if result.returncode == 0:
            return
        if docker("inspect", "--format", "{{.State.Running}}", container) != "true":
            break
        time.sleep(1)
    raise RuntimeError(f"Container readiness failed: {container}\n{result.stderr}")


def main() -> None:
    image = sys.argv[1] if len(sys.argv) > 1 else "osrs-recommender:test"
    prefix = f"osrs-smoke-{uuid.uuid4().hex[:10]}"
    app, mcp, volume, network = (f"{prefix}-{name}" for name in ("app", "mcp", "data", "net"))
    common = ["--network", network, "-v", f"{volume}:/data", "-e", "TRACKER_API_TOKEN=ci-only"]
    try:
        docker("volume", "create", volume)
        docker("network", "create", network)
        docker("run", "-d", "--name", app, *common, image)
        wait_for(
            app,
            "import urllib.request; "
            "urllib.request.urlopen('http://127.0.0.1:8502/healthz', timeout=2).read()",
        )
        docker(
            "exec",
            app,
            "python",
            "-c",
            "from datetime import UTC, datetime; "
            "from tracker.db.models import Player; "
            "from tracker.db.session import build_engine, build_session_factory; "
            "from tracker.api.contract import sync_payload_validator; "
            "from tracker.quest_cape.catalog import load_catalog; "
            "from pathlib import Path; import mcp, tracker.accounts, tracker.mcp; "
            "sync_payload_validator(); load_catalog(Path('content/quest_cape/catalog.json')); "
            "s=build_session_factory(build_engine('sqlite:////data/tracker.db'))(); "
            "s.add(Player(id=1, username='container_smoke', display_name='Container Smoke', "
            "created_at=datetime.now(UTC))); s.commit(); s.close()",
        )
        docker(
            "run",
            "-d",
            "--name",
            mcp,
            "--network-alias",
            "osrs-mcp",
            *common,
            "-e",
            "TRACKER_MCP__ENABLED=true",
            "-e",
            "TRACKER_MCP__PLAYER_ID=1",
            "-e",
            "TRACKER_MCP__BIND_ADDRESS=0.0.0.0",
            "-e",
            "TRACKER_MCP__ALLOW_ALL_INTERFACES=true",
            "-e",
            'TRACKER_MCP__ALLOWED_HOSTNAMES=["osrs-mcp"]',
            image,
            "python",
            "-m",
            "tracker.mcp",
        )
        wait_for(app, PROBE)
        docker("exec", mcp, "python", "-m", "tracker.mcp.healthcheck")
        docker("stop", mcp)
        wait_for(
            app,
            "import urllib.request; "
            "urllib.request.urlopen('http://127.0.0.1:8502/healthz', timeout=2).read()",
        )
        print("Container smoke passed: app, shared account, MCP tools, isolation, discovery 404s")
    finally:
        for container in (mcp, app):
            subprocess.run(["docker", "logs", "--tail", "30", container], check=False)
            subprocess.run(["docker", "rm", "-f", container], check=False)
        subprocess.run(["docker", "network", "rm", network], check=False)
        subprocess.run(["docker", "volume", "rm", volume], check=False)


PROBE = """
import json
import urllib.error
import urllib.request
from tracker.mcp.healthcheck import EXPECTED_TOOLS

def call(method, params=None):
    request = urllib.request.Request(
        'http://osrs-mcp:8503/mcp',
        data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode(),
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)['result']

names = [tool['name'] for tool in call('tools/list')['tools']]
assert len(names) == len(EXPECTED_TOOLS) and set(names) == EXPECTED_TOOLS, names
summary = call('tools/call', {'name':'get_account_summary','arguments':{}})
assert not summary.get('isError'), summary
assert 'container_smoke' in json.dumps(summary), summary
for path in ('/', '/healthz', '/api/sync', '/.well-known/oauth-authorization-server',
             '/.well-known/oauth-protected-resource', '/.well-known/openid-configuration'):
    try:
        urllib.request.urlopen('http://osrs-mcp:8503' + path, timeout=2)
    except urllib.error.HTTPError as error:
        assert error.code == 404, (path, error.code)
    else:
        raise AssertionError('Non-MCP route exposed: ' + path)
"""


if __name__ == "__main__":
    main()
