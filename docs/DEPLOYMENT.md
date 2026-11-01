# Deployment

The normal app is one process serving one port: the NiceGUI UI at `/`, the sync
API at `/api/sync`, and an unauthenticated liveness check at `/healthz`. Optional
Milestone 1 MCP runs as a separate process and never mounts those routes. Neither
service requires a public reverse proxy.

React Gear is served by that same process at `/gear`, with the NiceGUI fallback at
`/gear-legacy`. `/gear/` and `/gear-next/` redirect to `/gear`. The Docker build runs
locked `npm ci` and Vite in a Node build stage, then packages the assets in the Python
wheel; Node is absent at runtime. For the actual ARM64 image, verification and exact
image rollback commands, see [Milestone 6 deployment](GEAR_MILESTONE_6_DEPLOYMENT.md).

```bash
cp config.example.yaml config.yaml     # then edit — see below
make migrate                           # alembic upgrade head
make run
```

## Desktop Gear using live Pi data

The desktop Gear mode runs the Python optimizer and React UI on Windows and reads
account observations and cached prices from the Pi over Tailscale. RuneLite continues
sending updates to the Pi. Quest Cape, history, and account-setting edits remain on the
Pi. This mode does not copy or open the Pi's SQLite file across the network.

### Provision the Pi endpoint

Deploy an application image containing the read-only Gear data endpoint before starting
the desktop. Verify the live stack, selected player, and Tailscale address first. Generate
a fresh secret locally without committing or publishing it:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set `TRACKER_GEAR_DATA_TOKEN` in the Pi stack's private `.env` file, or set
`gear_data_token` in its private application YAML. Recreate only the
`osrs-recommender` Compose service after changing its image or environment. Preserve the
existing data/config mounts and RuneLite token. The endpoint is disabled when no read
token is configured. The read token must differ from the RuneLite write token.

The endpoint is `GET /api/gear-data/v1/players/{player_id}/snapshot`, authenticated with
`Authorization: Bearer <read token>`. Its dedicated credential cannot authorize
`/api/sync`. It returns raw account facts and prices, rather than Pi-calculated Gear
results. Restrict the service to the existing Tailscale/private publication; do not add
public ingress. Desktop and Pi must use compatible data-transport versions, but their
Gear catalogs and optimizer code need not match.

### Start on Windows

Use Python 3.12 or newer, the repository's `.venv` with project dependencies installed,
Node 22, npm, and an active Tailscale connection. If needed, create the environment with
`py -3.12 -m venv .venv` and install using
`.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.

Copy `config.gear-desktop.example.yaml` to `config.gear-desktop.yaml`. Set the Pi URL,
the account's numeric `player_id`, and `read_token` to the dedicated token provisioned
above. The default player ID is an example: confirm the correct ID in the Pi database.
Keep this file private. Alternatively, supply the token through
`TRACKER_DESKTOP_READ_TOKEN`; all desktop fields support a `TRACKER_DESKTOP_` environment
override. The launcher selects this file through `TRACKER_CONFIG_FILE` and leaves the
normal `config.yaml` alone.

```powershell
.\run-gear-desktop.bat
```

The launcher validates settings, runs locked `npm ci` and the React production build,
fetches missing sprites, and starts `http://127.0.0.1:8502/gear`. It runs no local
database migrations or provider refresh scheduler and exposes no RuneLite ingestion
endpoint. Stop any normal local app using port 8502 first, or change the desktop port.
The Pi token stays in the Python process and is never delivered to React.

Gear checks for updates on focus and through its existing 30-second refresh cycle.
Calculations fetch current facts before and after running. Account changes during a
calculation require refreshing and rerunning; prices remain frozen for that calculation.
Connection failures retain scenario drafts and mark the view unavailable/stale rather
than silently substituting a local database. Restore Tailscale/Pi connectivity to resume.
Authentication errors require checking the dedicated token; compatibility errors require
updating the endpoint or desktop to a compatible transport version.

No database schema migration is needed for this feature. Roll back by stopping desktop
Gear and removing the Pi read-token setting, then recreating only the application
service. Existing Pi UI, RuneLite synchronization, and MCP remain the normal workflow.

## Raspberry Pi Docker Compose

The production Compose source is `home-app-deployment/stacks/osrs-recommender/compose.yaml`;
the live stack is `/opt/stacks/osrs-recommender/compose.yaml`. Preserve local settings when
updating it. The verified deployment uses `./data:/data`,
`./config/config.yaml:/config/config.yaml:ro`, SQLite at `/data/tracker.db`, UID/GID
`10001:10001`, and private publication at `100.117.157.57:8502`.

For the optional `mcp` profile, existing OpenAI tunnel reuse, secret provisioning,
health checks, production acceptance, and rollback, follow
[the Milestone 1 production runbook](Refactor_Milestone1_Implementation.md#production-raspberry-pi-deployment).
The same immutable application image runs both the app and `python -m tracker.mcp`.
Only the default application startup runs migrations; explicit command overrides do not.
The sidecar uses the existing database and does not publish port 8503. Its failure does
not prevent normal dashboard or RuneLite synchronization.

The production image is published as `ghcr.io/OWNER/osrs_recommender:sha-COMMIT` for both
`linux/amd64` and `linux/arm64`. Replace `OWNER` and `COMMIT` with the GitHub repository
owner and the immutable full commit SHA produced by CI. Release pushes also publish a
version tag; the workflow deliberately does not publish `latest`.

The container serves port `8502`; its unauthenticated liveness URL is `/healthz`. This
Compose example publishes the port only on an explicitly selected private Pi address.
Set `TRACKER_PUBLISH_ADDRESS` to the Pi's Tailscale or private LAN address in a private
`.env` file next to the Compose file. Do not use `0.0.0.0` and do not forward this port
from the router.

```yaml
services:
  osrs-recommender:
    image: ghcr.io/OWNER/osrs_recommender:sha-COMMIT
    restart: unless-stopped
    ports:
      - "${TRACKER_PUBLISH_ADDRESS:?set a private Pi address}:8502:8502"
    environment:
      TRACKER_API_TOKEN: "${TRACKER_API_TOKEN:?set a private token}"
      TRACKER_BIND_ADDRESS: 0.0.0.0
      TRACKER_ALLOW_ALL_INTERFACES: "true"
      TRACKER_DATABASE_URL: sqlite:////data/tracker.db
      TRACKER_CONFIG_FILE: /config/config.yaml
      NICEGUI_STORAGE_PATH: /data/nicegui
    volumes:
      - ./data:/data
      - ./config/config.yaml:/config/config.yaml:ro
```

`TRACKER_ALLOW_ALL_INTERFACES=true` is a narrow, explicit opt-in for Docker bridge
networking. It changes only the address inside the container; the host-side publish
address above still controls which private interface accepts traffic. Direct host runs
continue to reject `0.0.0.0` by default.

Before the first start, create the private paths and make the data directory writable by
the image's non-root UID. Never commit either path:

```bash
mkdir -p data config
cp /path/to/osrs_recommender/config.example.yaml config/config.yaml
sudo chown -R 10001:10001 data config
chmod 700 data config
chmod 600 config/config.yaml
```

The example requires `TRACKER_API_TOKEN` through the private Compose environment; its
value overrides the placeholder in the mounted YAML file. The image runs
`alembic upgrade head` against `TRACKER_DATABASE_URL` before starting the app, and startup
stops if migration fails.

Mount the entire `./data` directory rather than only a pre-created database file. SQLite
uses WAL mode and needs its `tracker.db-wal` and `tracker.db-shm` sidecars beside the
database. NiceGUI's own runtime storage is also kept there at `/data/nicegui`, outside the
container writable layer. Back up a live database with the `.backup` command in section 7
below, not by copying the files.

Monitor `http://PRIVATE_PI_ADDRESS:8502/healthz` from Uptime Kuma on the private network.
The image also declares an equivalent Docker health check.

---

## 1. Choose a bind address deliberately

`bind_address` has **no default**, and the app refuses to start without it. This is SDD
§11.1, and the reason is worth stating plainly: v0.1 of the design claimed both "localhost
only" and "reachable from my phone via Tailscale", and those are incompatible. Tailscale
reachability means binding beyond loopback, and at that moment every device on the tailnet
can POST to `/api/sync` and rewrite your account state.

**"No public exposure" is a deployment property, not an access control.**

| Value | What it means |
|---|---|
| `127.0.0.1` | This machine only. The plugin and the browser must both be local. |
| Your Tailscale interface address (e.g. `100.x.y.z`) | Reachable from your tailnet — your phone, your laptop. |
| Your Tailscale MagicDNS name | The same, resolved by name. |
| `0.0.0.0` | Rejected unless `allow_all_interfaces` is explicitly enabled for an isolated container network. |

Find your tailnet address with `tailscale ip -4`.

## 2. Set an API token

`api_token` is required and has no default. Every `/api/*` request carries it as a bearer
token, **enforced regardless of source address** (§11.2) — being on the tailnet is not
authentication. The same value goes in the RuneLite plugin's settings.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`config.yaml` is gitignored because it holds this value. The token can also come from the
environment as `TRACKER_API_TOKEN`, which is the better option if you run the app under a
service manager.

Rejected requests are recorded in the `sync_event` table with `player_id = NULL` and the
caller's address (§11.3, §6.11) — that table is where to look if the plugin stops syncing,
or if something starts probing the port.

## 3. Restrict the tailnet with ACLs — as defense in depth (§11.4)

Tailscale ACLs decide which devices may reach the port at all. They are a **second** layer,
not the primary control: the bearer token is the primary control, and it holds even if the
ACL is wrong or absent.

In your tailnet policy file, allow only the devices that actually need the tracker:

```jsonc
{
  "acls": [
    {
      "action": "accept",
      "src":    ["tag:osrs-tracker-client"],   // your phone, your laptop
      "dst":    ["tag:osrs-tracker:8502"]      // the machine running the app
    }
  ]
}
```

Tag the host running the app and the devices that consume it, rather than listing users:
tags survive re-installs, and a lost phone can be untagged without touching the policy's
shape.

## 4. Never forward a port (§11.5)

**No inbound port forwarding, ever. There is no public deployment story.**

That is the whole rule, and it has no exceptions in v1. Concretely:

- no port-forward rule on your router;
- no `--publish` on a container reachable from the internet;
- no ngrok, Cloudflare Tunnel, or other public ingress;
- no putting it behind a public reverse proxy "just to add TLS".

The app holds your account's progression state and accepts writes that rewrite it. It has
one shared secret, no rate limiting on authentication attempts, no account recovery, and no
audit surface designed for hostile traffic. Tailscale exists precisely so that "reachable
from my phone" does not have to mean "reachable from the internet".

If you want the tracker on a device that is not on your tailnet, the answer is to add the
device to the tailnet.

## 5. Outbound traffic

The account companion uses these providers:

| Provider | Sent | Not sent |
|---|---|---|
| Wise Old Man | your username | anything else |
| OSRS Wiki prices | numeric item ids in authored tradeable Gear ladders | your username, your account state |

Deployed version 1 RuneLite clients may still send the optional `practice_events`
field. The server validates and ignores it; new clients omit it.

When the optional MCP profile is enabled, the separate tunnel makes outbound HTTPS
connections to OpenAI and delivers the nine Account/Quest Cape/Gear tools to
ChatGPT. This does not publish the dashboard or synchronization API. Its runtime key
is a tunnel-only file secret, separate from the RuneLite bearer token; never put it in
the stack's `.env`, which the existing application imports wholesale.

Both clients send a descriptive `User-Agent` that you configure (§7.5) — set it to
something that identifies your install, and include a contact only if you want to.

## 6. Running it as a service

Nothing about the app requires a service manager; `make run` in a terminal is a supported
way to use it. If you want it to survive a reboot, a user-level systemd unit is enough:

```ini
[Unit]
Description=OSRS PvP progression tracker
After=network-online.target tailscaled.service

[Service]
WorkingDirectory=%h/osrs_recommender
Environment=TRACKER_API_TOKEN=…
ExecStart=%h/osrs_recommender/.venv/bin/python -m tracker.app
Restart=on-failure

[Install]
WantedBy=default.target
```

`After=tailscaled.service` matters when you bind to a Tailscale address: the interface does
not exist yet at early boot, so the app would fail to bind rather than silently falling back
to a wider address.

## 7. Backups

Everything lives in one SQLite file (`database_url`, default `./tracker.db`). It is worth
copying: `skill_snapshot` accumulates the XP history §15's charts are drawn from, and
self-attested milestones are answers you gave that nothing else can reconstruct.

```bash
sqlite3 tracker.db ".backup 'tracker-backup.db'"
```

Use `.backup` rather than `cp` — the app runs SQLite in WAL mode, so a plain copy taken
while it is running can miss committed transactions still sitting in the write-ahead log.

### Refresh dev DB from production

Stop the local app and MCP, keep the repo's `.venv` and `config.yaml` configured,
and ensure SSH access to the Pi works. The script uses the same SSH authentication;
authorized SSH keys allow passwordless access, otherwise it may prompt repeatedly
for your password. The Pi stack
must be at `/opt/stacks/osrs-recommender`, with the running `osrs-recommender` service
using `./data:/data` and `sqlite:////data/tracker.db`. On Linux, from the repository
root, use the Pi's Tailscale IP and the `pi` SSH user:

```bash
.venv/bin/python scripts/refresh_dev_db.py --production-host pi@100.117.157.57 --dry-run
.venv/bin/python scripts/refresh_dev_db.py --production-host pi@100.117.157.57
```

The dry run verifies the connection and Compose identity without creating a snapshot
or replacing the local database. On Windows, use PowerShell:

```powershell
.\scripts\refresh-dev-db.ps1 -DryRun
.\scripts\refresh-dev-db.ps1                 # or -ProductionHost pi@pi.local
```

The script verifies Compose identity, uses SQLite's online backup API inside the running
container, streams the complete snapshot over SSH, checks size/SHA-256 and SQLite
`quick_check`, and verifies core account tables. It migrates the **staged local copy**
with the repository's Alembic head, then backs up the existing dev DB to
`backups/dev-before-refresh-YYYYMMDD-HHMMSS.sqlite` before installing it. The previous
physical DB and any WAL sidecars are also retained beside that backup with an
`.original-` suffix. A snapshot or migration failure leaves the current dev DB alone.
No production migration, upload, container restart, or raw live-DB copy occurs.

### Milestone 3 schema retirement

Before upgrading an existing database to the M3 Alembic head, take and verify an online
SQLite backup using the procedure above. The forward migration deletes legacy
recommendation, capability, roadmap, guidance, advisor, practice, and milestone rows,
plus persisted selected-price outputs. It retains account observations, separate
container scan timestamps, raw market prices and provenance, sync audit, and the
`gp_sensitivity` preference. The removed rows have no archive table. Alembic cannot
restore their contents on downgrade; rollback requires stopping the app and MCP and
restoring the verified pre-M3 backup. Do not substitute a raw copy of a live WAL-mode
database.

To restore, stop the local app/MCP again and use the retained backup (adjust timestamp):

```powershell
Copy-Item .\backups\dev-before-refresh-YYYYMMDD-HHMMSS.sqlite .\tracker.db
```

Remove or move aside any `tracker.db-wal` and `tracker.db-shm` from the refreshed DB
before restoring. If `config.yaml` selects another database path inside the repository,
restore to that path instead. Treat backups as private account data; `backups/` is ignored
by Git.
