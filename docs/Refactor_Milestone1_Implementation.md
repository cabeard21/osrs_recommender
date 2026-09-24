# Milestone 1 implementation and private deployment

## Architecture and final deployment decision

The implemented path is:

```text
Existing RuneLite sync → existing account tables → AccountSnapshot
    → requirement evaluation → Quest Cape services → four Streamable HTTP tools
    → OpenAI Secure MCP Tunnel → ChatGPT reasoning
```

The final Milestone 1 deployment supersedes the earlier public HTTPS/OAuth plan.
There is no external issuer, JWKS verifier, OAuth subject mapping, public hostname,
protected-resource metadata, or login UI. The dedicated MCP process listens on
`127.0.0.1:8503` by default. It does not mount the dashboard, sync routes, or health
routes from the existing application. `make run` continues to run that application;
`make run-mcp` runs the optional private sidecar against the same database.

The private listener trusts its local/private network boundary. Development uses loopback
with the tunnel client on the same host. Production uses a dedicated internal Docker
network and an explicit MCP-only wildcard binding opt-in, without host publication.
Explicit RFC1918, ULA, and Tailscale IP bindings remain supported; public bindings and
wildcard bindings without that opt-in are rejected.
No inbound Internet port or public reverse proxy is needed. The RuneLite bearer token
is neither sent to the tunnel nor used to authenticate MCP.

`ConfiguredAccount` binds the sidecar to one existing `player.id`. MCP handlers depend
only on the `SnapshotProvider` interface, which can later be implemented by an
authenticated account resolver without changing tool implementations or domain services.
There is no model-supplied player selector. MCP is disabled until explicitly configured.

## Implementation map

- `tracker/accounts/`: immutable factual snapshots, stable fingerprints, consistent read
  transactions over existing repository queries, and shared skill/quest truth checks.
- `tracker/quest_cape/`: standalone catalog validation, structured three-valued requirement
  explanations, Cape status, threshold actions, and isolated counterfactual evaluation.
- `tracker/mcp/`: private sidecar entrypoint, four thin tool handlers, configured account
  resolver, and private binding settings. It never starts a refresh scheduler or an LLM.
- `content/quest_cape/catalog.json` and `tools/data/quest_cape_source.json`: generated facts
  and pinned Wiki revision inputs, independent of recommendation candidates.
- `tools/capture_quest_cape.py` / `tools/generate_quest_cape.py`: manual online capture and
  deterministic offline generation. Wiki-derived content is attributed to its page/revision
  and licensed CC BY-NC-SA 3.0.
- `tests/quest_cape/`: snapshot, requirement, graph, action, persistence, configuration,
  and HTTP MCP regression coverage.
- Configuration, Make targets, dependencies, and README expose the optional sidecar.
  The existing evaluator delegates skill/quest truth checks to shared factual functions.
  One existing API test uses `httpx2.Response`, matching Starlette's response type after
  the MCP SDK installs its `httpx2` dependency. No database or sync-contract migrations.

## Tool contracts and modeling decisions

| Tool | Inputs | Result |
|---|---|---|
| `get_account_summary` | None | Observed facts, timestamps, provenance, snapshot ID |
| `get_goal_status` | `goal`, optional `quest_offset`, `quest_limit`, `quest_ids` | Whole-goal totals/thresholds and a page of explanations |
| `get_available_actions` | `goal` | Separate available quest actions and training thresholds |
| `evaluate_action` | `action`, `goal`, optional `expected_snapshot_id` | Hypothetical deltas and blocker changes |

The only goal is `quest_cape`. `quest_limit` defaults to 20 through MCP, with a maximum
of 100. Follow `next_quest_offset` or request specific quest IDs. Counts and thresholds
always cover the whole goal; pagination affects only quest details.

Actions are `{"type":"complete_quest","quest":"regicide"}` or
`{"type":"train_skill","skill":"agility","target_level":70}`. IDs must come from
the returned facts. Ordering is alphabetical, never a recommendation ranking.

Missing observations remain unknown. `remaining` means not confirmed complete, including
unknown completion states. For counted quests, `remaining = available_now + blocked + unknown`.
Miniquests and RFD chapters needed by the goal appear as dependency/action nodes but do not
inflate Cape totals. Completing RFD's terminal chapter also completes its parent in the
hypothetical copy, contributing one Cape quest.

Availability checks modeled completion requirements with observed base levels, without
temporary boosts. It does not predict combat execution, supplies, equipment, or step-by-step
quest progression. Membership is exposed as an account fact but is not an availability gate
in this slice. Conditions the catalog cannot represent remain explicit unknowns.

Counterfactuals do not save anything. Completion of a blocked quest is allowed as a conditional
experiment, with its unmet preconditions listed. No prerequisite is automatically completed.
Known quest-point rewards are applied; staged/unknown remaining rewards make the hypothetical
point total unknown. Combat training recomputes combat level only with all combat-skill inputs.
XP rewards, items, costs, and time are excluded. `requirements_newly_satisfied` counts distinct
requirement identities per quest; `downstream_quests` lists structural descendants, not a claim
that they all become available. Snapshot-ID checks detect intervening account changes.

The captured identity spine has 211 nodes, including 182 full quests. The Cape dependency
closure uses 198 nodes. Twenty-three relevant nodes retain unmodeled conditions, including
Kudos, access to areas/facilities, partial quest stages, partners, and some alternatives.
Sailing requirements are preserved even when an installed sync source has no Sailing observation.
No missing skill is fabricated. The corpus is revision-pinned, not automatically current:
new RuneLite identities require refreshing the identity spine and recapturing the catalog.

## Development and desktop testing

Desktop integration has passed on Windows with Python 3.12 and tunnel-client v0.0.14:
the MCP listener, exactly four tools, prompt discovery 404s, `doctor`, tunnel readiness,
ChatGPT app creation, and actual tool invocation were verified. The desktop database is
stale; these checks do not establish acceptance against current RuneLite state. The
authoritative database lives on the Pi. Do not repeat provisioning or create another
logical tunnel for production.

### Configure and start locally

From the repository root, install the updated dependencies:

```bash
.venv/bin/pip install -e '.[dev]'
```

Find the existing player ID without modifying the database:

```bash
.venv/bin/python - <<'PY'
from sqlalchemy import select
from tracker.config.settings import load_settings
from tracker.db.models import Player
from tracker.db.session import build_engine
engine = build_engine(load_settings().database_url)
with engine.connect() as connection:
    for row in connection.execute(select(Player.id, Player.username).order_by(Player.id)):
        print(row.id, row.username)
engine.dispose()
PY
```

Set `mcp.player_id` in your existing private `config.yaml` to the returned integer and set
`mcp.enabled: true`. Leave `mcp.bind_address: 127.0.0.1` and `mcp.port: 8503` for same-host
operation. The existing application settings, including its separate sync token, are unchanged.
Alternatively, provide only the sidecar overrides in its shell:

```bash
read -rp 'Existing OSRS player ID: ' TRACKER_MCP__PLAYER_ID
export TRACKER_MCP__PLAYER_ID
export TRACKER_MCP__ENABLED=true
make run-mcp
```

The sidecar refuses to start if MCP is disabled or the player does not exist. Keep the normal
application running separately when syncing is desired. A normal application process never
exposes `/mcp`, even when the sidecar configuration is enabled.

Check local discovery in another shell (no bearer token):

```bash
curl --fail-with-body http://127.0.0.1:8503/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Exactly the four tools above should be returned. `/`, `/api/sync`, and OAuth discovery
paths are not served by this listener.

### Windows no-auth preflight regression check

Restart the sidecar after updating its code, then run these commands in PowerShell:

```powershell
curl.exe -i --max-time 5 http://127.0.0.1:8503/.well-known/oauth-protected-resource/mcp
curl.exe -i --max-time 5 http://127.0.0.1:8503/.well-known/oauth-protected-resource
curl.exe -i --max-time 5 http://127.0.0.1:8503/
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | curl.exe -i --max-time 10 http://127.0.0.1:8503/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' --data-binary '@-'
tunnel-client doctor --profile osrs-recommender --explain
```

All three GETs must promptly return `404 Not Found`; the POST must return HTTP 200
with exactly the four tools. For the intentionally configured
`sample_mcp_remote_no_auth` profile, these discovery 404s are the expected optional/no-auth
result. Confirm that `doctor` passes against the restarted process; local tests alone
do not establish live tunnel acceptance.

The outer ASGI router delegates only exact `/mcp` requests to the SDK app and retains
its session-manager lifespan. Every other path receives a direct plain-text 404, without
entering SDK handling or Starlette's exception-based missing-route handler. This includes
OAuth discovery, root, dashboard, sync, health, and unknown paths. The installed SDK itself
has an exact `/mcp` route; inspection did not show discovery GETs opening an MCP stream.
The outer boundary avoids depending on SDK fallback behavior for no-auth preflight.
No OAuth metadata, authentication, additional application routes, or binding changes
are introduced.

Routing-fix verification on Windows (2026-09-24): `tests/quest_cape`, `tests/api`,
`tests/sync`, and `tests/progression` passed together (412 tests). MCP coverage was
90%, including 100% of `tracker/mcp/server.py`. The regression tests include a real
loopback listener with two-second HTTP timeouts and a deliberately waiting SDK stub
that must never receive non-MCP requests. Scoped Ruff and MCP mypy checks passed.

## Development tunnel setup (already completed)

This procedure follows the [OpenAI Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
and the [tunnel-client configuration reference](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md),
checked on 2026-09-24. Tunnel access is separate from the OSRS application's credentials.

1. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels).
   Reuse the existing OSRS tunnel associated with the target ChatGPT workspace.
   Copy its actual `tunnel_id`; do not create another tunnel for the Pi.
2. Use the download offered there, or the platform-appropriate asset from the
   [latest tunnel-client release](https://github.com/openai/tunnel-client/releases/latest).
   Put the full `tunnel-client` binary on your PATH. Run `tunnel-client help quickstart`.
3. Provide a runtime API key from [Platform API keys](https://platform.openai.com/settings/organization/api-keys).
   Tunnel management needs Read + Manage; runtime use and ChatGPT connection need Read + Use.
   The runtime key is not an admin key or the RuneLite token.
4. In a fresh shell on the MCP host, use the documented environment-based HTTP configuration:

```bash
read -rp 'OpenAI tunnel ID: ' CONTROL_PLANE_TUNNEL_ID
read -rsp 'OpenAI tunnel runtime API key: ' CONTROL_PLANE_API_KEY
echo
export CONTROL_PLANE_TUNNEL_ID CONTROL_PLANE_API_KEY
export MCP_SERVER_URL=http://127.0.0.1:8503/mcp
tunnel-client doctor --explain
tunnel-client run
```

Keep both processes running. The tunnel client needs outbound HTTPS to `api.openai.com:443`
and local access to port 8503. No tunnel credential belongs in OSRS config or source control.
The optional private-IP override is only needed when these processes are on different trusted
hosts; then use that same address in both the MCP binding and `MCP_SERVER_URL`.

## Production Raspberry Pi deployment

Production Compose is maintained in `home-app-deployment/stacks/osrs-recommender/compose.yaml`.
Apply its reviewed changes to the live `/opt/stacks/osrs-recommender/compose.yaml`; retain
the live app's environment, healthcheck, private port and mounts. The verified contract is:

| Setting | Production value |
|---|---|
| Application port | `100.117.157.57:8502:8502` |
| Database | `./data:/data`, `sqlite:////data/tracker.db` |
| Configuration | `./config/config.yaml:/config/config.yaml:ro` |
| Application/MCP user | `10001:10001` |
| Restart policy | `unless-stopped` |
| Target platform | `linux/arm64`, Raspberry Pi 4 / 64-bit Debian |

`osrs-recommender` remains the writer. Optional profile `mcp` adds `osrs-mcp`, using the
same image with command `python -m tracker.mcp`, and `osrs-mcp-tunnel`. The sidecar mounts
the same complete data directory to support SQLite WAL, but its handlers only read and
evaluate immutable counterfactual copies. Its entrypoint skips migrations. No database
migration or copy is needed to add MCP.

MCP binds `0.0.0.0:8503` only with its separate explicit opt-in and `osrs-mcp` hostname
allowance. The internal network connects only MCP and tunnel. Neither has a published
port. The tunnel also joins an outbound-capable network; the application is not dependent
on either optional service. Only `/mcp` is routed on the sidecar; all other paths return
prompt 404s. Docker healthchecks use `python -m tracker.mcp.healthcheck`, which verifies
the actual protocol and exact tool set, rather than an OAuth or dashboard endpoint.

The official image is pinned to
`ghcr.io/openai/tunnel-client:v0.0.14@sha256:41d7c85dab37797a3eaa17c41b94a7206dd0bc186fd361034c9ec3863596ff6c`, matching desktop
acceptance and the latest release verified on 2026-09-24. Record its pulled digest in the
release record; do not substitute `latest`. Official release/image support includes ARM64.
See the [versioned Docker guide](https://github.com/openai/tunnel-client/blob/v0.0.14/docs/deployment/docker.md)
and [runtime configuration](https://github.com/openai/tunnel-client/blob/v0.0.14/docs/configuration.md).
The target is `http://osrs-mcp:8503/mcp`; startup waiting is 60 seconds. The image runs
non-interactively with its supported `run` entrypoint. `/healthz` indicates liveness and
`/readyz` indicates readiness on container loopback port 8080. No admin port is published.

### Release prerequisites

Run the final checks below and review both repositories' diffs for secrets/unrelated edits.
Create the Milestone 1 checkpoint, then publish through the existing GHCR workflow. Use
`ghcr.io/cabeard21/osrs_recommender:sha-<full checkpoint commit>` for both application
services. Record that exact tag, its registry digest, and its `linux/arm64` manifest before
deployment. The new tag/digest are release outputs; this document does not imply that a
new image has already been published. Manifest inspection is not native Pi runtime testing.

The application checkpoint is on `refactor/account-companion`. After pushing that branch,
use **Run workflow** on the existing GitHub Actions **Container image** workflow and select
that branch; `workflow_dispatch` builds and publishes its exact commit without a new release
system. A normal push to this feature branch does not trigger the main-only push workflow.
If publishing after a merge to `main` instead, use the SHA of that workflow run (which may
be the merge commit), not an assumed feature-branch SHA. Wait for validation, container
smoke and both architecture builds to succeed before changing the Pi's image reference.

The known previous application image is
`ghcr.io/cabeard21/osrs_recommender:sha-b7bdd80221eef02e172494d63cca33cae1fca036`,
digest `sha256:33c832b92e4c5dedde00c979880d923abed791489d2392a0aaf93ceb2c434415`.
Its installed platform was verified as `linux/arm64`.

### Back up the live stack

Run each command separately on the Pi. Keep this shell open so its variables persist.
Do not paste raw `.env`, configuration, expanded Compose output, or secrets into chat.

```bash
cd /opt/stacks/osrs-recommender
backup_name="pre-mcp-$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -m 700 "backups/$backup_name"
sudo cp -a compose.yaml .env config "backups/$backup_name/"
printf '%s\n' "$backup_name"
docker compose exec -T osrs-recommender python -c 'import sqlite3; from datetime import datetime, timezone; from pathlib import Path; p=Path("/data/backups"); p.mkdir(mode=0o700,exist_ok=True); target=p/("pre-mcp-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".db"); src=sqlite3.connect("file:/data/tracker.db?mode=ro",uri=True); dst=sqlite3.connect(target); src.backup(dst); dst.close(); src.close(); target.chmod(0o600); print(target)'
```

This uses SQLite's online backup API, including committed WAL data, without pausing sync.
Preserve the existing `10001:10001` ownership and mode on `data` and `config`; do not
recursively change permissions or copy the active database file alone.

### Configure the existing account and tunnel

After the backup, transfer the reviewed candidate from Windows PowerShell:

```powershell
scp D:\Repos\home-app-deployment\stacks\osrs-recommender\compose.yaml pi@100.117.157.57:/opt/stacks/osrs-recommender/compose.mcp.proposed.yaml
```

On the Pi, inspect the difference locally (do not paste any unexpected inline credentials):

```bash
diff -u compose.yaml compose.mcp.proposed.yaml
```

The intended change adds only the optional services, networks and secret definition.
The live checksum differed from the source template, so reconcile any existing application
command, healthcheck or environment differences in the candidate before replacing the file.
Do not discard local settings. Once that comparison is correct:

```bash
cp compose.mcp.proposed.yaml compose.yaml
```

Find the
existing player IDs using the current application image:

```bash
docker compose exec -T osrs-recommender python -c 'from sqlalchemy import select; from tracker.config.settings import load_settings; from tracker.db.models import Player; from tracker.db.session import build_engine; e=build_engine(load_settings().database_url); c=e.connect(); print(*c.execute(select(Player.id,Player.username).order_by(Player.id)),sep="\n"); c.close(); e.dispose()'
nano .env
```

In the existing `.env`, update `OSRS_RECOMMENDER_IMAGE` to the actual published full-SHA
tag. Add `OSRS_MCP_PLAYER_ID=<existing integer>` and `CONTROL_PLANE_TUNNEL_ID=<existing tunnel ID>`.
Retain the private publish address and RuneLite token. Neither identifier is a runtime key.
Compose maps `OSRS_MCP_PLAYER_ID` to `TRACKER_MCP__PLAYER_ID` only in the sidecar. Do not
put nested `TRACKER_MCP__...` settings into shared `.env`; the normal app imports it too.
The sidecar receives a fixed unused token solely to satisfy common settings validation;
it has no sync endpoint and does not import the application's `.env` or require the real
synchronization bearer token. The shared configuration file may still contain that token;
the sidecar remains inside the same trusted account-data boundary.

The existing app imports all of `.env`, so **never put the OpenAI runtime key there**.
Provide it as a tunnel-only file secret. The following hidden prompt avoids shell history:

```bash
install -d -m 700 secrets
read -rsp 'Existing OpenAI tunnel runtime key: ' tunnel_runtime_key
printf '\n'
printf '%s' "$tunnel_runtime_key" | sh -c 'umask 077; cat > secrets/openai-tunnel-api-key'
unset tunnel_runtime_key
chmod 600 secrets/openai-tunnel-api-key
```

Keep the directory and file owned by the Pi operator running Compose so it can resolve
the source path. The v0.0.14 tunnel image runs as root and can read the mounted file. Compose mounts
it only into that container at `/run/secrets/openai-tunnel-api-key`, passed with
`--control-plane.api-key=file:/run/secrets/openai-tunnel-api-key`. Keep the directory
excluded from version control. Do not reuse the RuneLite bearer token.

### Pull and start with checkpoints

```bash
docker compose --profile mcp config --quiet
docker compose --profile mcp pull
docker compose up -d osrs-recommender
docker compose ps
curl --fail --max-time 10 http://100.117.157.57:8502/healthz
```

Require healthy status, working dashboard, and a fresh RuneLite sync before continuing.

```bash
docker compose --profile mcp up -d osrs-mcp
docker compose --profile mcp ps
docker compose logs --tail 100 osrs-mcp
docker compose exec -T osrs-mcp python -m tracker.mcp.healthcheck
```

Require a successful MCP probe. Before starting the Pi tunnel, stop the desktop OSRS
tunnel terminal with Ctrl+C. If it was launched by a scheduled task/service, disable only
that OSRS runtime's task/service. On Windows, inspect candidate process IDs locally:

```powershell
Get-Process tunnel-client -ErrorAction SilentlyContinue | Select-Object Id, StartTime, Path
```

If the terminal is unavailable, identify the OSRS process before `Stop-Process -Id <ID>`;
do not stop all tunnel clients. Verify it remains stopped. Keep the logical tunnel and
existing ChatGPT app intact.

Back on the Pi:

```bash
docker compose --profile mcp up -d osrs-mcp-tunnel
docker compose --profile mcp ps
docker compose logs --tail 100 osrs-mcp-tunnel
docker compose exec -T osrs-mcp-tunnel wget -q -O - http://127.0.0.1:8080/healthz
docker compose exec -T osrs-mcp-tunnel wget -q -O - http://127.0.0.1:8080/readyz
docker image inspect "$(docker inspect "$(docker compose ps -q osrs-mcp-tunnel)" --format '{{.Image}}')" --format 'Platform={{.Os}}/{{.Architecture}} Digests={{json .RepoDigests}}'
docker inspect "$(docker compose ps -q osrs-mcp)" --format 'Image={{.Config.Image}} ImageID={{.Image}}'
```

Record application image digest/platform as well:

```bash
docker image inspect "$(docker inspect "$(docker compose ps -q osrs-mcp)" --format '{{.Image}}')" --format 'Platform={{.Os}}/{{.Architecture}} Digests={{json .RepoDigests}}'
```

Both readiness and liveness must succeed. Readiness is not proven merely by a running
process. If startup times out, correct MCP/configuration/network errors and restart only
the tunnel; do not add a retry script or reprovision a tunnel. Verify service recovery
after restarting MCP and tunnel, and confirm dashboard/sync continue when both are stopped.
Run the ChatGPT acceptance below before marking production complete.

### Rollback without restoring account data

If using a new shell, set `backup_name` to the exact recorded backup directory basename.
Stop/remove optional containers before restoring Compose:

```bash
cd /opt/stacks/osrs-recommender
docker compose --profile mcp stop osrs-mcp-tunnel osrs-mcp
docker compose --profile mcp rm -f osrs-mcp-tunnel osrs-mcp
sudo cp -a "backups/$backup_name/compose.yaml" compose.yaml
sudo cp -a "backups/$backup_name/.env" .env
docker compose config --quiet
docker compose pull osrs-recommender
docker compose up -d osrs-recommender
docker compose ps
curl --fail --max-time 10 http://100.117.157.57:8502/healthz
```

The backed-up `.env` restores the recorded previous image tag. Verify it resolves to the
previous image above. Configuration was not changed for MCP; do not overwrite newer
intentional application configuration. Leave account data and backup files in place.
Never use `down -v`, delete the data directory, or restore an old database for this rollback.

## ChatGPT acceptance — production Pi verification pending

The existing tunnel and ChatGPT app have already worked with the desktop runtime. Reuse
both. Production acceptance requires stopping that desktop runtime and verifying that
only the Pi runtime serves the existing tunnel against the live database.

Use the existing connection at [ChatGPT Plugins](https://chatgpt.com/plugins). If it is
absent, check workspace association and permissions before changing the connection.

1. Sync the intended RuneLite account. Make `get_account_summary` the first ChatGPT tool
   call: require its username, recent skill and quest observation timestamps/provenance,
   and generated snapshot fingerprint to match the live Pi account. A correct username
   alone does not rule out the stale desktop database.
2. Attach the connection in a new ChatGPT conversation and ask:
   **“I'm working toward my Quest Cape. What should I do next?”**
3. Inspect tool activity: require `get_goal_status("quest_cape")` and
   `get_available_actions("quest_cape")`.
4. Have ChatGPT evaluate an available quest action and an offered skill threshold. Pass the
   returned snapshot ID to detect intervening syncs. If necessary, explicitly ask it to compare
   one quest and one training action before answering.
5. Check that the answer reasons from factual deltas and acknowledges unknowns. No tool response
   should contain a score, priority, efficiency rating, or server-selected best action.
6. Compare the account summary/fingerprint again. For a strict persisted-state comparison,
   pause normal sync/refresh writers during the test, leaving only the MCP sidecar and tunnel
   running, and run the digest command below before and after. The digests must match. A genuine
   concurrent sync can change a digest independently of MCP; rerun with writers paused.

For that controlled test, stop only the application writer after a fresh sync; existing
MCP/tunnel containers remain running. This temporarily pauses the dashboard and sync.
Run the same read-only digest command before and after the ChatGPT evaluations:

```bash
docker compose stop osrs-recommender
docker compose exec -T osrs-mcp python -c 'import hashlib,sqlite3; c=sqlite3.connect("file:/data/tracker.db?mode=ro",uri=True); c.execute("BEGIN"); print(hashlib.sha256("\n".join(c.iterdump()).encode()).hexdigest()); c.close()'
```

The digest covers logical persisted rows rather than physical WAL bytes. Resume the app
immediately after the comparison, including if an acceptance step fails:

```bash
docker compose start osrs-recommender
docker compose ps
```

If the account already has its Cape, or lacks observed skill/quest state, the tools should
report that honestly rather than inventing actions. Use a synced account with remaining quest
and training actions to exercise both counterfactuals in the live acceptance scenario.

## Verification and later observations

Run from the repository root:

```bash
.venv/bin/python -m pytest tests/quest_cape -q
.venv/bin/python -m pytest -q
make lint
make typecheck
make validate-content
.venv/bin/python tools/generate_candidates.py --check
make validate-quest-cape
```

The focused suite includes HTTP initialization/discovery/schema checks, configured account
resolution, rejected/ineffective account-switch arguments, service equivalence, local/private
binding, disabled startup, unknown observations, meaningful thresholds, prerequisite chains,
RFD counting, and explicit no-write checks against all persisted tables for both action types.
Network calls are absent from domain/runtime content evaluation. Capture is manual and separate.

The historical type-check baseline was 53 errors in five existing test files. With the
current Python 3.12 / mypy 2.3.1 environment, an isolated checkout of the pre-checkpoint
HEAD reports 57 errors in seven test files. This checkpoint removes the HTTP response-type
mismatch and leaves 56 pre-existing errors in six files. The three additional errors beyond
the historical 53 are missing annotations in `tests/db/test_band_persistence.py` at lines
70, 252 and 271. No new Milestone 1 diagnostics were introduced; these legacy errors are
not suppressed or treated as a passing full type check. Production code and the new
packages type-check cleanly.

Historical desktop implementation results on 2026-09-24 (not the final Pi-hardening run):

| Check | Result |
|---|---|
| Full regression run, `.venv/bin/python -m pytest -q` | 2,385 passed in 382.95 seconds |
| Final focused run, `.venv/bin/python -m pytest tests/quest_cape -q` | 43 passed; includes three tests added after full-suite collection and the final outstanding-prerequisite fix |
| `make lint` | Passed: lint and formatting |
| `make validate-content` | Passed |
| `.venv/bin/python tools/generate_candidates.py --check` | Passed; legacy generated content unchanged |
| `make validate-quest-cape` | Passed; factual catalog matches pinned inputs |
| `.venv/bin/python -m mypy tracker/accounts tracker/quest_cape tracker/mcp` | Passed: 13 source files |
| `make typecheck` | Same 53 existing errors in five legacy test files; no added errors |
| Live ChatGPT + Secure MCP Tunnel | Desktop tool invocation passed; live Pi account acceptance pending |

The full run had one Pydantic test deprecation warning; that test was corrected and the final
focused run has no warnings. HTTP tests need execution outside this environment's restrictive
sandbox because Starlette TestClient startup stalls inside it; no test code was weakened to
work around the restriction.

### Final Pi-hardening verification (2026-09-24)

| Check | Result |
|---|---|
| Full regression, Python 3.12.10, system temporary directory | **2,425 passed in 351.83 seconds** |
| `tests/quest_cape` with account/Quest Cape/MCP coverage | **77 passed; 94.81% coverage** |
| Entrypoint and CI-policy tests | **7 passed** |
| Ruff lint and formatting | Passed; 270 Python files formatted correctly |
| Content, existing generated candidates, Quest Cape catalog | Passed; 211 Quest Cape nodes |
| New-package mypy | Passed; 14 source files |
| Production mypy | Passed; 139 source files |
| Full mypy including tests | 56 existing errors in six test files; baseline explanation above |
| AMD64 application build and real container smoke | Passed; Python 3.12.14 |
| ARM64 application build and container smoke under emulation | Passed; Python 3.12.14 |
| Actual app-only Compose startup without MCP identifiers/secret | Passed; only the app started, healthy, `/healthz` returned `status: ok` |
| Production image dependency audit | 75 dependencies checked; no known vulnerabilities |
| Pinned official tunnel image | Entrypoint, root user and `wget` verified; ARM64 binary ran under emulation and reported v0.0.14 |
| Real Pi tunnel `/readyz` and ChatGPT acceptance | Pending production deployment and operator-supplied credentials |

The earlier full run reported 2,424 passed and one timing failure in the unchanged
scheduler test, which assumes two refresh attempts finish within an 80 ms sleep.
The scheduler module passed unchanged (five tests), followed by the complete passing
rerun above after concurrent image builds finished. No tests were weakened or skipped.
An initial workspace-temp run was stopped after diagnosing slow SQLite fixture I/O;
the final complete runs used system temp with identical tests.

Both application smoke runs used disposable Docker data and exercised normal migrations,
shared account reads, the exact four tools, prompt discovery 404s, the MCP health probe,
and application health after stopping MCP. These prove image compatibility, including
ARM64 emulation; they do not establish native Pi execution or live-account acceptance.
No production database or tunnel credential was used during local verification.

Future work should prioritize richer factual modeling for the explicitly unknown conditions,
catalog freshness checks against the RuneLite identity source, and account freshness UX.
Authenticated multi-user resolution can replace the adapter if hosting needs change. These are
observations for a later milestone, not implemented goals or a recommendation engine.
