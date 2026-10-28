# Gear Milestone 6 deployment

Deployment date: 2026-10-28 UTC (2026-10-27 America/Chicago).

## Packaging and routes

The existing application remains one FastAPI/NiceGUI process on port 8502. Docker's
Node 22 build stage runs `npm ci` against `frontend/gear/package-lock.json`, then
`npm run build`. The Python builder copies that output into `tracker/ui/gear_static`
before building the wheel. Recursive package data includes the index, JavaScript,
CSS and any nested fonts. The runtime installs the wheel and contains no Node or
source frontend. Docker ignores developer output, node_modules, credentials and
SQLite files. A production build does not require a pre-existing local Vite build.

For a standalone wheel, start from tracked source, run `npm ci && npm run build`
inside `frontend/gear`, then `python -m pip wheel --no-deps .` at the repository root.
The Docker build performs these steps automatically.

| URL | Behavior |
| --- | --- |
| `/gear` | Primary React Gear Optimizer, live account mode by default |
| `/gear/` | 307 redirect to `/gear`, preserving query parameters |
| `/gear/{client_path}` | React index for direct navigation and refresh |
| `/gear-next`, `/gear-next/` | Temporary 307 compatibility redirects to `/gear`, preserving queries |
| `/gear-legacy` | Retained NiceGUI Gear implementation |
| `/gear-ui/{asset_path}` | Compiled assets; missing or escaping paths return 404 |
| `/gear-sprites/{item_id}.png` | Existing local physical item sprites |
| `/ui-api/gear/*` | Existing account-aware Python browser API |

React routes register before NiceGUI's root mount. The index uses `Cache-Control:
no-cache`; Vite's absolute `/gear-ui/` base works from deep links. A missing bundle
returns a Gear-specific 503 pointing to `/gear-legacy`. Dashboard navigation already
targets `/gear`; React's Existing Gear link now targets `/gear-legacy`.

No changes were made to sync authentication, browser same-origin checks, MCP tools,
account observations, database schema, combat/search algorithms, Fast/Thorough
limits, secondary priority ordering, or other dashboard page implementations.

## ARM64 deployment method and retained state

Authoritative live stack: `pi@pi.local:/opt/stacks/osrs-recommender/compose.yaml`.
Native architecture: `aarch64`. Published application address remains
`100.117.157.57:8502`; no additional port, server, container, or network is introduced.
Persistent mounts remain `./data:/data` and
`./config/config.yaml:/config/config.yaml:ro`, with UID/GID 10001.

A clean archive was assembled from tracked application files with current intended
edits, excluding ignored/untracked builds and private runtime files. It was transferred
through the approved SSH/SCP execution path, then built natively using:

```bash
cd /tmp/osrs-gear-m6-1bb1914b
docker build --platform linux/arm64 \
  --label org.osrs.gear-m6.source=1bb1914bfbcc4be81bdf8493efe87c75f6f819b610d9d3c7ea1baece3239a953 \
  -t osrs-recommender:gear-m6-1bb1914b .
```

Archive: `/tmp/osrs-gear-m6-1bb1914b.tar.gz`; SHA-256:
`1bb1914bfbcc4be81bdf8493efe87c75f6f819b610d9d3c7ea1baece3239a953`.
It contains 429 tracked files and no local frontend output or database.
This is a locally built release artifact, not a newly published Git/GHCR release.

Before cutover, the application container `65a7b3687456b05fdb88514aeffc9b0aa01fe03bdd1248117e5d066cd3d4e6a5`
was healthy, using
`ghcr.io/cabeard21/osrs_recommender:sha-d34095646725aab905cfa4b3211d7e1809b37765`:

```text
sha256:668ba2a01bdb2fa864c69d51ed88772c083d818a17bf801f7862d08ea3b86dc2
```

That image is retained locally as `osrs-recommender:gear-m6-rollback-20261028`.
Private environment and Compose copies are retained on the Pi at
`/home/pi/osrs-gear-m6-20261028/env.before` (mode 0600) and
`/home/pi/osrs-gear-m6-20261028/compose.before.yaml`.

The online SQLite backup is
`/opt/stacks/osrs-recommender/data/gear-m6-20261028-before.sqlite` (mode 0600).
Integrity check: `ok`. SHA-256:
`3e3d7342645fd61fedba7ebd869768abae7f0a225361f5be09d1e07a848bef25`.
Pre-deployment counts: 1 player, 6429 skill snapshots, 847 observed items,
3 container scans, 252 sync events, 190 cached item prices.
Production and repository migration heads both equal `7c9a4e10d2f6`;
the normal entrypoint therefore requires no schema migration for this release.

## Verification

Pre-deployment checks completed:

- Backend Gear/API, sync, MCP and focused UI regression selection: **812 passed**.
- React: **185 passed**; statements 90.07%, branches 85.94%, functions 91.34%, lines 90.47%.
- Locked `npm ci`: no reported vulnerabilities; production TypeScript/Vite build passed.
- React desktop/mobile browser workflows: **22 passed**.
- Added canonical URL and deep-link refresh smoke: **2 passed**.
- Retained NiceGUI browser journeys plus isolated wheel packaging test: **4 passed**.
- Updated React fallback-link regression: **12 passed** after observing the expected failure first.
- Route module coverage: **100%**; focused Ruff and Prettier checks passed.

Native ARM64 verification passed from the clean source archive. The disposable
container smoke used its own Docker volume/network, created only a disposable
test account, and removed those resources afterward. It checked actual installed
wheel routes, JS/CSS/sprites, absence of Node/source frontend, NiceGUI pages, and
MCP tool discovery/account reads and non-MCP route isolation. Production data was
never mounted into that smoke container. The installed production distribution's
RECORD also contains the actual index, hashed JavaScript/CSS and item sprites.

## Actual deployed artifact and functional results

The live `.env` now sets `OSRS_RECOMMENDER_IMAGE=osrs-recommender:gear-m6-1bb1914b`.
Only that setting changed. Cutover used the existing Compose workflow:

```bash
cd /opt/stacks/osrs-recommender
docker compose up -d --no-deps osrs-recommender
```

Actual deployed image ID:

```text
sha256:f09ce3b5d14ab0e5cdd366351000217bb574080ddaf6f8a577ce1f05ee047709
```

Container:
`4a2513f9bce1658351f32af520a69ea95c290e5ef11f3bc6db31d6502f0c57fc`.
Architecture: `arm64`. Final status: **healthy**, restart count **0**, OOM killed
**false**. The publish address and both existing mounts were verified unchanged.
No new frontend server or persistent container was created.

Actual private production HTTP/browser checks:

- `/`, `/gear`, `/gear-legacy`, `/skills`, `/unlocks`, `/settings`, `/healthz`,
  `/ui-api/gear/context`, `/ui-api/gear/items`, and `/gear-sprites/4151.png`: **200**.
- Dashboard, legacy Gear and settings also rendered their expected live NiceGUI
  controls in Chromium. React loaded the real account and synchronized skills and
  physical equipment. Desktop and mobile views loaded without browser errors;
  the mobile deep link refreshed successfully without horizontal overflow.
- `/gear/?check=canonical` redirected to `/gear?check=canonical`.
  `/gear/results/example` loaded and refreshed in live account mode.
- Fast single-style optimization: **200**, about **5.39 s** wall time in this smoke.
- Thorough single-style optimization with `prayer_bonus`: **200**, about **8.52 s**.
  Request, submitted scenario, result and selected solution identified the chosen
  priority; the Python work budget and priority semantics remained unchanged.
- Physical weapon inspection and preview of Rune scimitar against the selected
  loadout: evaluation **200**, baseline and proposal both `valid`. The manual trial
  comparison rendered, reverted, and left the accepted recommendation intact.
- Locking the physical weapon and rerunning Fast: **200**, about **6.59 s**;
  the submitted lock was present in the returned scenario.
- Two-style joint optimization (melee/ranged): **200**, about **35.67 s**.
  Side-by-side and Interactive switching rendered the same returned solution.
  The view displayed directed equip sequences, automatic removals, inventory
  peaks, shared physical items and acquisition requirements. This zero-budget
  scenario correctly reported zero additional purchases.
- During an active search, `/healthz` stayed responsive. A concurrent valid solve
  received **503 `optimizer_busy`**. Cancel restored UI control; a subsequent Fast
  solve succeeded, demonstrating release of the backend single-flight gate.
- An intentionally outdated request fingerprint received **409 `snapshot_changed`**;
  a cross-origin optimization request received **403**. These were request-local
  checks; no observations were changed.
- The real observed Graceful top/gloves and Boots of lightness correctly produced
  an unavailable baseline with explicit unknown-equipment-requirement reasons.
  Joint results also identified the unavailable joint baseline. Unknown ownership,
  partial/missing scans and stale-result behavior remain covered by local regression
  and disposable browser cases; production observations were not altered to force them.
- Production MCP health check returned `MCP ready`. Account summary and Gear
  candidate tools also returned real data through the existing ChatGPT connector.
  Sidecar `a412b9c080ae` and tunnel `e18c7d185085` were not recreated and remained healthy.
  The sidecar retains image ID
  `sha256:79859681ad77fe6b338802d8e3b9ec4660f2a26031a2862ea454dcbd0e9694b1`.
- Cached price access worked in the browser/MCP; the existing scheduler refreshed
  prices normally. Final cache count was 222 (previously 190).

Read-only comparisons against the backup confirmed that player data, observed
items, container scans and sync audit rows were unchanged. Every prior skill
snapshot was unchanged; the normal Wise Old Man refresh appended 21 rows, bringing
the skill history count to 6450. SQLite `quick_check` returned `ok`.
The last genuine accepted RuneLite sync was `2026-10-28 02:53:25.991942` UTC,
payload version 1. No fabricated, rejected-test, or replayed sync events were sent
to production; sync audit count remained 252.

## Remaining limitations

- A fresh interactive RuneLite client sync was not forced during deployment.
  Existing token/configuration and observations were preserved; sync compatibility
  and bearer authentication passed the focused backend tests. The live evidence is
  the retained genuine sync history and functional account reads, not a newly
  generated gameplay event.
- Runtime smoke used Windows Chromium against the actual Pi; no browser or Node
  runtime was installed on the Pi. Physical phone interaction was not performed.
- The image was built natively on the Pi and was not published to GHCR or committed
  to Git. Retain the recorded local image and rollback tag. The repository changes
  update CI so future image builds include React automatically.
- Timings above describe these smoke scenarios only. They are not a performance
  guarantee or an exhaustive Thorough/joint benchmark. The application stayed healthy;
  observed app memory was about 198 MiB during search and 188 MiB afterward.
- The full production rollback was documented and its prior artifact retained;
  production was not interrupted a second time to rehearse rollback.

## Rollback

If React alone is unavailable, open `/gear-legacy` immediately.

For image rollback, SSH to the Pi and restore the previous image setting, then
recreate only the app. This preserves the production database and leaves the MCP
sidecar and tunnel running:

```bash
cd /opt/stacks/osrs-recommender
cp /home/pi/osrs-gear-m6-20261028/env.before .env
docker compose up -d --no-deps osrs-recommender
docker inspect osrs-recommender-osrs-recommender-1 --format '{{.Image}} {{.State.Health.Status}}'
curl -fsS http://100.117.157.57:8502/healthz
docker exec osrs-recommender-osrs-mcp-1 python -m tracker.mcp.healthcheck
```

Expected rollback image ID:
`sha256:668ba2a01bdb2fa864c69d51ed88772c083d818a17bf801f7862d08ea3b86dc2`.
If the old tag needs restoring locally, use:

```bash
docker tag osrs-recommender:gear-m6-rollback-20261028 \
  ghcr.io/cabeard21/osrs_recommender:sha-d34095646725aab905cfa4b3211d7e1809b37765
```

No database restore or migration reversal is required for image rollback. The
backup is a precaution; do not overwrite newer account observations during rollback.

## Files changed

`Dockerfile`, `.dockerignore`, `pyproject.toml`, `.github/workflows/container.yml`,
`tracker/ui/gear_preview.py`, `tracker/ui/pages.py`, `frontend/gear/src/App.tsx`,
`frontend/gear/src/tests/App.test.tsx`, `frontend/gear/e2e/workflows.spec.ts`,
`tests/ui/test_gear_preview.py`, `tests/ui/test_gear_packaging.py`,
`tests/ui/test_pages_browser.py`, `tools/container_smoke.py`,
`frontend/gear/README.md`, `docs/DEPLOYMENT.md`, and this record.
