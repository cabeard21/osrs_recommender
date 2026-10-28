# Fast/Thorough service performance acceptance

## Decision

**Not accepted for production deployment.** No user-accepted latency/resource envelope
has been established. The new mode integration remains development-only; no production
files, routes, Docker packaging, or observations were replaced. Production Thorough
must remain unavailable until the serving-process measurements and operator acceptance
below are complete.

## Current evidence and explicit blocker

On October 28, 2026 UTC, an existing `pi@pi` SSH connection was checked read-only and
reported `aarch64`. The installed tracker package location and static `/app/content`
directory were inspected. **No new Pi Fast/Thorough HTTP performance measurements were
completed.** Reachability does not establish service performance.

Automatic approval review rejected staging source for the disposable benchmark twice.
The first proposal recursively staged Python/static content. It was replaced with a
materially narrower explicit allowlist of 28 files: Gear Python modules, the browser
API integration, a preview route module, three benchmark modules, and public equipment
catalog metadata. That safer proposal also received this rejection:

> Despite the strict allowlist, this still exports non-public repository source to Pi;
> the user authorized Pi benchmarking but not the specific source-code payload and
> destination egress required by this command.

No transfer or benchmark was executed after either rejection. Approval is required to
copy that explicitly listed source/catalog payload into a temporary directory in the
existing user-owned `pi@pi` container. The harness excludes credentials, configuration,
settings, environment files, databases, live observations, and private account fixtures.
The transfer allowlist and per-file byte counts/SHA-256 hashes can be reviewed locally
without contacting the Pi:

```powershell
.venv\Scripts\python.exe -m tools.benchmark_gear_modes_api --manifest-only
```

## Reproducible serving-process harness

[`tools/benchmark_gear_modes_api.py`](../tools/benchmark_gear_modes_api.py) prepares an
isolated synthetic database and uses the actual `tracker.app.create_app`, NiceGUI,
browser optimization router, service concurrency guard, and worker-thread execution.
It sends actual loopback HTTP Fast/Thorough requests. It does not substitute direct
optimizer calls or a research child process for API measurements.

The synthetic member account is the existing joint benchmark fixture: level 99 skills,
authored quests complete, four owned starter items, deterministic synthetic cached
quotes, and a 5,000,000 GP acquisition budget. This is reproducible serving workload
evidence; it will not establish performance for the user's real account or market
prices. All roles and normal base round trips are retained. No combat/search settings
are reduced.

| Workload | Roles | Action limit | Reserved supply slots |
| --- | ---: | ---: | ---: |
| Slash | 1 | 8 | 12 |
| Ranged | 1 | 8 | 12 |
| Magic | 1 | 8 | 12 |
| Melee/Ranged joint | 2 | 4 | 12 |
| Melee/Ranged/Magic joint | 3 | 4 | 12 |
| Above plus second melee role against a different target | 4 | 4 | 12 |

The default is one measured request per cell after one Slash startup warmup. Use
`--repeats 3` for a three-sample comparison. First-use effects in other cells and warm
serving-process reuse must be considered; this is not a randomized or thermally
controlled performance study. The report retains individual samples and provenance.

While each optimization is active, concurrent traffic exercises:

- `GET /healthz` and real NiceGUI dashboard HTML construction at `/`.
- `GET /ui-api/gear/context` with the synthetic optimizing account.
- Authenticated `POST /api/sync` for a **separate synthetic player**, using the actual
  validation/merge/audit path in the disposable database. This avoids changing the
  optimizing account's fingerprint. No RuneLite client or production sync writes are
  generated, and no price refresh client/scheduler is started.
- A read-only MCP `get_account_summary` tool call on a separate temporary loopback
  sidecar, matching the deployed separate-process arrangement. This is a protocol
  responsiveness probe, not a benchmark of every MCP tool.

Per request, independent `/proc`/cgroup sampling records serving-process CPU time/RSS,
container memory, host available RAM, load averages and resource limits. Serving CPU
includes the concurrent dashboard/context/sync work; it is not isolated optimizer CPU.
Container readings include the existing production services and temporary services.
Sampled maxima are not guaranteed exact allocation peaks. HTTP probe latency includes
thread/GIL/event-loop/SQLite contention inside the actual serving process. Raw probe
status codes and MCP tool success are retained so unsuccessful responses cannot be
mistaken for responsiveness acceptance.

The cancellation check waits 0.2 seconds, obtains an overlapping optimization's busy
response, then closes the real TCP optimization request. It records actual request age
at disconnect separately from the scheduled wait. The run must first observe a 503
`optimizer_busy`; otherwise cancellation is explicitly unmeasured. It polls fixed
evaluation until a 200 response with valid baseline/proposed equipment establishes
that the same service guard is available. Error responses or invalid evaluations cannot
count as guard release. This measures disconnect-to-reuse latency, including cooperative
cancellation checkpoints and the probe's own overhead. It does not claim immediate
Python thread termination or specifically time refinement-only cancellation.

The temporary test service is loopback-only, receives a generated disposable token,
and never opens the production database. Remote staging copies the already installed
package/static content into a temporary directory and overlays the explicit source
allowlist. Both test processes and the synthetic database are removed on completion.
No dependencies are installed, production files changed, or persistent jobs created.

After transfer approval, the proposed full Pi run is:

```powershell
.venv\Scripts\python.exe -m tools.benchmark_gear_modes_api --remote pi@pi --repeats 3 --output .tmp/gear-modes-api/pi.json
```

The harness is Linux-specific because resource sampling reads `/proc` and cgroups.
Its thirteen focused local tests verify all six browser-valid workloads, the exact
static staging allowlist/manifest, cancellation evidence checks and environment isolation.
They do not establish successful remote execution,
MCP startup, cancellation latency, or Pi performance. Those remain unverified until
the complete run succeeds.

## Outstanding acceptance table

| Measurement | Fast | Thorough |
| --- | --- | --- |
| Pi API wall/serving CPU, all six workloads | Not measured | Not measured |
| Pi serving RSS/container/host memory under requests | Not measured | Not measured |
| Busy response and disconnect-to-guard reuse | Not measured | Not measured |
| Concurrent dashboard/context response latency | Not measured | Not measured |
| Concurrent isolated authenticated sync latency | Not measured | Not measured |
| Concurrent isolated MCP tool response latency | Not measured | Not measured |
| Physical RuneLite/browser acceptance under concurrent load | Not performed | Not performed |
| User-accepted latency/resource envelope | Not supplied | Not supplied |

Earlier isolated compute measurements in
[`GEAR_REFINEMENT_ENABLEMENT_REVIEW.md`](GEAR_REFINEMENT_ENABLEMENT_REVIEW.md) remain
valid for their stated scope. They used separate lower-priority research processes,
so they do not fill any of the new serving-process acceptance gaps above.
