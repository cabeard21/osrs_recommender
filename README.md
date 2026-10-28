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
- **Gear optimizer:** single-style and joint multi-style equipment search, item locks,
  additional GP budget, explicit future assumptions, inventory reservations, directional
  equipment actions, and a selectable swap-efficiency curve. One `GearService` serves
  the dashboard and MCP. Results are bounded **best found**, with supported-mechanics
  limits and dated ownership/price evidence. Dagannoth Kings and Zulrah presets describe
  a limited ordinary-attack model rather than complete fight simulations.
- **Private MCP:** nine read-only tools, including `optimize_gear`, at exact `/mcp`.
  Legacy factual gear operations remain compatibility adapters during migration.
  The MCP sidecar has
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

CI runs static validation, frontend validation, full Python coverage, and container
smoke checks as independent jobs; all must pass before image publication. Coverage
uses two workers with module-scoped scheduling to reuse catalog/browser fixtures,
combines worker coverage for the same 80% gate, and reports the 25 slowest tests.
To use the same parallel coverage lane locally after installing dev dependencies:
`make test-cov ARGS="-n 2 --dist=loadscope --durations=25"`. The local default stays serial.

Current authoring rules are in [content authoring](docs/CONTENT_AUTHORING.md).
Equipment metadata is bundled under `content/equipment`; optimization makes no network
requests and saves no computed recommendations. Missing requirements and unvalidated
effects remain inspectable and are excluded from quantified ranking. Prayers, boosts,
complex weapon/set effects, special utility, and damage-cap rerolls remain unsupported.
The preset templates state their phase/order assumptions explicitly. Phase-clear time
and final removal of compatibility tools remain follow-up work after acceptance.
The former weighted recommender design is preserved only as a
[historical specification](docs/SDD.md).
