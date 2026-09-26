# OSRS Account Companion

A private account companion for ChatGPT. RuneLite and imported data supply observed
account state; the application evaluates Quest Cape and Gear facts; ChatGPT helps the
player plan from those facts. The application does not rank all possible activities or
choose a universal "best next action."

See [current architecture](docs/ARCHITECTURE.md) for the product boundary and
[deployment](docs/DEPLOYMENT.md) for the private desktop and Raspberry Pi setup.

## Current capabilities

- **Account:** synchronized skills, quests, unlocks, dated item sightings, separate
  bank/inventory/equipment scans, sync freshness, and cached market observations.
- **Quest Cape:** goal status, available quest and skill actions, and read-only
  hypothetical action evaluation.
- **Gear:** authored progression, factual candidate filters, item details, and
  read-only gear-change evaluation through one `GearService` used by both MCP and the
  dashboard. Prices include their source and age; unknown ownership or compatibility
  remains unknown.
- **Private MCP:** eight factual tools for ChatGPT at exact `/mcp`. The MCP sidecar has
  no dashboard or sync routes.

The dashboard shows account, sync, goal, Gear, skill, unlock, and settings facts.
ChatGPT performs planning and recommendation reasoning from the MCP outputs.

## Getting started

```bash
make install
cp config.example.yaml config.yaml
# Set a private bind_address and the RuneLite sync api_token in config.yaml.
make lint typecheck test
make migrate
make run
```

`config.yaml` is gitignored. For Windows, the repo's `run.bat` and `run-mcp.bat`
launchers use the local Python environment. The MCP sidecar requires an explicit
player ID and is disabled by default; see [deployment](docs/DEPLOYMENT.md).

## Verification

`make test` runs the fast suite. `make browsers` installs Chromium once; then
`make test-full` includes the focused browser tests. `make test-cov` applies the
repository's existing 80% supported-core coverage gate. Run content validation,
lint, and production type checks before committing changes.

Current authoring rules are in [content authoring](docs/CONTENT_AUTHORING.md).
The former weighted recommender design is preserved only as a
[historical specification](docs/SDD.md).
