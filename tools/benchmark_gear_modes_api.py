"""Disposable HTTP serving-process benchmark; never opens the operator database.

Run on Linux with ``python -m tools.benchmark_gear_modes_api --output report.json``.
``--remote pi@pi`` stages only source/content into an automatically removed temporary
directory in the existing container. It does not install, deploy, or modify services.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import secrets
import shlex
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def state(pid: int) -> dict[str, Any]:
    """Read independent serving-process and cgroup counters without instrumentation."""
    proc = Path(f"/proc/{pid}")
    stat = (proc / "stat").read_text().split()
    status = dict(
        line.split(":", 1) for line in (proc / "status").read_text().splitlines() if ":" in line
    )
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    result = {
        "cpu_seconds": (int(stat[13]) + int(stat[14])) / os.sysconf("SC_CLK_TCK"),
        "rss_kib": int(status["VmRSS"].split()[0]),
        "host_available_kib": int(memory["MemAvailable"].split()[0]),
        "loadavg": Path("/proc/loadavg").read_text().strip(),
    }
    for field in ("memory.current", "memory.peak", "memory.max", "memory.events", "cpu.max"):
        path = Path("/sys/fs/cgroup") / field
        if path.exists():
            result[field] = path.read_text().strip()
    return result


def requests(snapshot: str) -> dict[str, dict[str, Any]]:
    from tools.benchmark_gear_joint import joint_request

    rows = {}
    joint = joint_request(3, 4)
    for role in joint["roles"]:
        rows[role["style"]] = {
            **joint,
            "roles": [role],
            "base_role": role["id"],
            "max_swaps": 8,
            "expected_snapshot_id": snapshot,
        }
    for count in (2, 3, 4):
        rows[f"joint_{count}"] = {
            **joint_request(count, 4),
            "expected_snapshot_id": snapshot,
        }
    return rows


def serve(database: Path, port: int, token: str) -> None:
    import uvicorn

    from tracker.app import create_app
    from tracker.config.settings import Settings

    settings = Settings(
        bind_address="127.0.0.1",
        port=port,
        api_token=token,
        database_url=f"sqlite:///{database.resolve()}",
        content_dir=Path("content"),
    )
    app = create_app(settings, start_scheduler=False)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def wait_ready(url: str, process: subprocess.Popen) -> None:
    for _ in range(300):
        if process.poll() is not None:
            raise RuntimeError(f"Disposable service exited: {process.returncode}")
        try:
            with httpx.Client(timeout=1) as client:
                reply = client.get(url)
            if reply.status_code in (200, 404, 405):
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Disposable service startup timed out")


def probe(client: httpx.Client, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        reply = client.request(method, url, **kwargs)
        row = {"seconds": time.perf_counter() - started, "status": reply.status_code}
        if "mcp" in url:
            data = reply.json()
            row["tool_ok"] = "result" in data and not data["result"].get("isError", False)
        return row
    except (httpx.HTTPError, ValueError) as exc:
        return {"seconds": time.perf_counter() - started, "error": type(exc).__name__}


def probes(base: str, mcp_base: str, token: str, stop: threading.Event, rows: list) -> None:
    with httpx.Client(timeout=15) as client:
        while not stop.is_set():
            rows.append(
                {
                    "health": probe(client, "GET", base + "/healthz"),
                    "dashboard": probe(client, "GET", base + "/"),
                    "context": probe(client, "GET", base + "/ui-api/gear/context"),
                    "sync": probe(
                        client,
                        "POST",
                        base + "/api/sync",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "payload_version": 1,
                            "observed_at": datetime.now(UTC).isoformat(),
                            "player": {"username": "modesprobe"},
                            "skills": [{"skill": "magic", "level": 1, "xp": 0}],
                        },
                    ),
                    "mcp": probe(
                        client,
                        "POST",
                        mcp_base + "/mcp",
                        headers={"Accept": "application/json, text/event-stream"},
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {"name": "get_account_summary", "arguments": {}},
                        },
                    ),
                }
            )
            stop.wait(0.5)


def measure(base: str, mcp_base: str, token: str, pid: int, body: dict) -> dict:
    stop = threading.Event()
    samples: list[dict] = []
    traffic: list[dict] = []

    def sample() -> None:
        while not stop.wait(0.05):
            samples.append(state(pid))

    sampler = threading.Thread(target=sample)
    prober = threading.Thread(target=probes, args=(base, mcp_base, token, stop, traffic))
    before = state(pid)
    sampler.start()
    prober.start()
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=240) as client:
            response = client.post(base + "/ui-api/gear/optimizations", json=body)
        elapsed = time.perf_counter() - started
        after = state(pid)
    finally:
        stop.set()
        sampler.join()
        prober.join()
    response.raise_for_status()
    result = response.json()
    refinement = result["result"]["search"].get("local_refinement", {})
    solution = result["result"]["selected_solution"]
    return {
        "wall_seconds": elapsed,
        "serving_cpu_seconds": after["cpu_seconds"] - before["cpu_seconds"],
        "before": before,
        "after": after,
        "peak_rss_kib": max(s["rss_kib"] for s in [before, after, *samples]),
        "peak_container_bytes": max(int(s["memory.current"]) for s in [before, after, *samples]),
        "min_host_available_kib": min(s["host_available_kib"] for s in [before, after, *samples]),
        "concurrent_probes": traffic,
        "optimization_mode": result["optimization_mode"],
        "work_budget_policy": result["work_budget_policy"],
        "snapshot_id": result["result"]["snapshot_id"],
        "catalog_version": result["result"]["catalog_version"],
        "model_version": result["result"]["model_version"],
        "scenario_fingerprint": result["scenario_fingerprint"],
        "price_revision": result["price_revision"],
        "role_count": len(body["roles"]),
        "transitions": len(solution["transitions"]) if solution else None,
        "score": solution["score"] if solution else None,
        "assignment_attempts": refinement.get("assignment_attempts", 0),
        "work_budget_exhausted": refinement.get("work_budget_exhausted", False),
        "search": {k: v for k, v in result["result"]["search"].items() if k != "local_refinement"},
    }


def cancellation(base: str, body: dict) -> dict:
    """Close the real TCP request, then measure when the same service releases its guard."""
    payload = json.dumps(body).encode()
    host, raw_port = base.removeprefix("http://").split(":")
    with socket.create_connection((host, int(raw_port))) as sock:
        sent_at = time.perf_counter()
        sock.sendall(
            f"POST /ui-api/gear/optimizations HTTP/1.1\r\nHost: {host}:{raw_port}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
            + payload
        )
        time.sleep(0.2)
        with httpx.Client(timeout=240) as client:
            busy = client.post(base + "/ui-api/gear/optimizations", json=body)
    closed_at = time.perf_counter()
    observed = {
        "scheduled_sleep_seconds": 0.2,
        "disconnect_after_seconds": closed_at - sent_at,
        "concurrent_status": busy.status_code,
        "concurrent_code": busy.json().get("error", {}).get("code"),
    }
    if busy.status_code != 503 or observed["concurrent_code"] != "optimizer_busy":
        return {
            **observed,
            "status": "not_measured",
            "reason": "An active search holding the service guard was not established",
        }
    # A single-role fixed evaluation takes the identical guard and cannot start a new search.
    role = body["roles"][0]
    scenario = {
        **body,
        "roles": [role],
        "base_role": role["id"],
        "transitions": [],
        "ordered_roles": [],
        "loop": False,
    }
    trial = {
        "scenario": scenario,
        "baseline_loadouts": {role["id"]: {"weapon": 1333}},
        "proposed_loadouts": {role["id"]: {"weapon": 1333}},
    }
    with httpx.Client(timeout=30) as client:
        for _ in range(1000):
            reply = client.post(base + "/ui-api/gear/evaluations", json=trial)
            data = reply.json()
            valid = all(
                data.get(side, {}).get("status") == "valid" for side in ("baseline", "proposed")
            )
            if reply.status_code == 200 and valid:
                return {
                    **observed,
                    "status": "measured",
                    "guard_released_after_disconnect_seconds": time.perf_counter() - closed_at,
                    "evaluation_status": reply.status_code,
                }
            if reply.status_code != 503 or data.get("error", {}).get("code") != "optimizer_busy":
                return {
                    **observed,
                    "status": "not_measured",
                    "reason": "Guard release requires a successful valid fixed evaluation",
                    "evaluation_status": reply.status_code,
                }
            time.sleep(0.05)
    return {**observed, "status": "not_measured", "reason": "Guard reuse timed out"}


def service_environment(database: Path, directory: Path, mcp_port: int, token: str) -> dict:
    """Both disposable services use the copied content and synthetic database."""
    return {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "TRACKER_CONFIG_FILE": str(directory / "absent.yaml"),
        "TRACKER_BIND_ADDRESS": "127.0.0.1",
        "TRACKER_API_TOKEN": token,
        "TRACKER_DATABASE_URL": f"sqlite:///{database}",
        "TRACKER_CONTENT_DIR": str(Path("content").resolve()),
        "TRACKER_MCP__ENABLED": "true",
        "TRACKER_MCP__PLAYER_ID": "1",
        "TRACKER_MCP__BIND_ADDRESS": "127.0.0.1",
        "TRACKER_MCP__PORT": str(mcp_port),
    }


def local(repeats: int) -> dict:
    from tools.benchmark_gear_joint import FROZEN_AT, create_database
    from tracker.content.loader import load_content
    from tracker.gear.service import GearService

    with tempfile.TemporaryDirectory(prefix="gear-modes-serving-") as directory:
        database = Path(directory) / "synthetic.sqlite"
        content = load_content()
        create_database(database, content, GearService(content).equipment_catalog(), FROZEN_AT)
        port, mcp_port = free_port(), free_port()
        token = secrets.token_urlsafe(32)
        base, mcp_base = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{mcp_port}"
        env = service_environment(database, Path(directory), mcp_port, token)
        processes = []
        with (Path(directory) / "services.log").open("w+") as log:
            try:
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "tools.benchmark_gear_modes_api",
                            "--serve",
                            str(database),
                            str(port),
                        ],
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "tracker.mcp"], env=env, stdout=log, stderr=log
                    )
                )
                wait_ready(base + "/healthz", processes[0])
                wait_ready(mcp_base + "/", processes[1])
                with httpx.Client(timeout=30) as client:
                    context = client.get(base + "/ui-api/gear/context").json()
                cases = requests(context["account"]["snapshot_id"])
                report: dict[str, Any] = {
                    "at": datetime.now(UTC).isoformat(),
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "python": platform.python_version(),
                    "cpus": os.cpu_count(),
                    "fixture": "benchmark_gear_joint synthetic level99/all quests/4 owned starters",
                    "scope": "HTTP/create_app/NiceGUI/worker threads; separate MCP sidecar",
                    "cases": {},
                }
                # Warm imported code/catalog and UI; timings below remain single samples by default.
                with httpx.Client(timeout=240) as client:
                    client.get(base + "/")
                    client.post(
                        base + "/ui-api/gear/optimizations", json=cases["slash"]
                    ).raise_for_status()
                for name, body in cases.items():
                    report["cases"][name] = {}
                    for mode in ("fast", "thorough"):
                        rows = []
                        for _ in range(repeats):
                            row = measure(
                                base,
                                mcp_base,
                                token,
                                processes[0].pid,
                                {**body, "optimization_mode": mode},
                            )
                            rows.append(row)
                        report["cases"][name][mode] = rows
                        median = statistics.median(r["wall_seconds"] for r in rows)
                        print(
                            f"{name} {mode}: {median:.3f}s",
                            file=sys.stderr,
                            flush=True,
                        )
                report["cancellation"] = {
                    mode: cancellation(base, {**cases["joint_4"], "optimization_mode": mode})
                    for mode in ("fast", "thorough")
                }
                return report
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-8000:], file=sys.stderr)
                raise
            finally:
                for process in processes:
                    process.terminate()
                for process in processes:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


TRANSFER_PATHS = (
    "tracker/app.py",
    "tracker/api/gear_ui.py",
    "tracker/api/gear_optimizations.py",
    "tracker/api/gear_evaluations.py",
    "tracker/api/gear_scenario_validation.py",
    "tracker/gear/__init__.py",
    "tracker/gear/catalog.py",
    "tracker/gear/combat.py",
    "tracker/gear/encounters.py",
    "tracker/gear/evaluation.py",
    "tracker/gear/facts.py",
    "tracker/gear/ladders.py",
    "tracker/gear/local_refinement.py",
    "tracker/gear/models.py",
    "tracker/gear/optimizer.py",
    "tracker/gear/refinement.py",
    "tracker/gear/service.py",
    "tracker/gear/targeted_retention.py",
    "tracker/gear/transitions.py",
    "tracker/ui/gear_preview.py",
    "tools/benchmark_gear.py",
    "tools/benchmark_gear_joint.py",
    "tools/benchmark_gear_modes_api.py",
    "content/equipment/catalog.json",
    "content/equipment/manifest.json",
    "content/items/gear_high_impact.yaml",
    "content/items/gear_coverage_phase1.yaml",
    "content/items/gear_coverage_phase2.yaml",
)


def archive_inputs() -> tuple[bytes, dict]:
    """No recursive staging: only reviewed source files and public catalog metadata."""
    packed = io.BytesIO()
    manifest = {}
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in TRANSFER_PATHS:
            data = Path(name).read_bytes()
            archive.writestr(name, data)
            manifest[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return packed.getvalue(), manifest


def remote(host: str, repeats: int) -> dict:
    packed, manifest = archive_inputs()
    print(json.dumps({"transfer_manifest": manifest}, indent=2), file=sys.stderr)
    launcher = (
        "import sys,base64,io,zipfile,tempfile,subprocess,os,shutil,tracker,pathlib; "
        "d=tempfile.TemporaryDirectory(prefix='gear-modes-api-'); "
        "shutil.copytree(pathlib.Path(tracker.__file__).parent,pathlib.Path(d.name)/'tracker'); "
        "shutil.copytree('/app/content',pathlib.Path(d.name)/'content'); "
        "z=zipfile.ZipFile(io.BytesIO(base64.b64decode(sys.stdin.buffer.read()))); "
        "z.extractall(d.name); "
        "p=subprocess.run([sys.executable,'-m','tools.benchmark_gear_modes_api','--repeats',"
        f"'{repeats}'],cwd=d.name,env={{**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}}); "
        "d.cleanup(); sys.exit(p.returncode)"
    )
    command = (
        "cd /opt/stacks/osrs-recommender && docker compose exec -T osrs-recommender python -c "
        + shlex.quote(launcher)
    )
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        input=base64.b64encode(packed),
        stdout=subprocess.PIPE,
        timeout=2400,
    )
    result.check_returncode()
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", metavar="SSH_HOST")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--serve", nargs=2, metavar=("DATABASE", "PORT"), help=argparse.SUPPRESS)
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    if args.manifest_only:
        print(json.dumps(archive_inputs()[1], indent=2))
        return
    if args.serve:
        serve(Path(args.serve[0]), int(args.serve[1]), os.environ["TRACKER_API_TOKEN"])
        return
    report = remote(args.remote, args.repeats) if args.remote else local(args.repeats)
    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    else:
        print(serialized)


if __name__ == "__main__":
    main()
