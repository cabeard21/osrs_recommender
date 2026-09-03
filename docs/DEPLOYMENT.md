# Deployment

The app is one process serving one port (SDD §5): the NiceGUI UI at `/`, the sync API at
`/api/sync`, and an unauthenticated liveness check at `/healthz`. There is no second
service to start and no reverse proxy in the design.

```bash
cp config.example.yaml config.yaml     # then edit — see below
make migrate                           # alembic upgrade head
make run
```

## Raspberry Pi Docker Compose

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
value overrides the placeholder in the mounted YAML file. If task guidance or the advisor
is enabled, also provide `ANTHROPIC_API_KEY`; it is otherwise optional. The image runs
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

The app talks to two providers and sends each the minimum it needs (§11.6):

| Provider | Sent | Not sent |
|---|---|---|
| Wise Old Man | your username | anything else |
| OSRS Wiki prices | numeric item ids referenced by your active roadmap | your username, your account state |

**Practice events never leave the machine.** They are the most sensitive thing the app
stores, and nothing outbound carries them.

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
