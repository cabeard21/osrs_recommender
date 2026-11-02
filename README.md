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

Magic setups support all 16 Ancient Magicks combat spells with ancient staff,
including fixed spell selection and automatic search. Access requires the spell's
Magic level and confirmed Desert Treasure I completion; explicit locked or unknown
Ancient unlock observations block eligibility. Damage uses the spell's fixed base
hit and five-tick casting, with per-cast rune costs. Scores cover one target's direct
damage only, excluding healing, poison, freezes, stat drains and area damage.
Spell data follows the [OSRS Wiki](https://oldschool.runescape.wiki/w/Ancient_Magicks).

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

Routine CI runs static validation, frontend build/tests, a focused Python smoke suite,
and container smoke checks before image publication. `make test-smoke` (also
`make test-ci`) reproduces the Python CI subset: startup/configuration, authentication,
sync/API contracts, migrations, and small optimizer/transition regressions. The full
Python suite, expensive account/search-quality regressions, browser tests, and coverage
measurement are left to local verification.

For a full CI run, use **Run workflow** on the Container image workflow and enable
**full_tests**. This adds the complete Python/browser suite and the 80% coverage gate;
a failure blocks publication. Non-browser tests use two workers, followed by a separate
browser process because Playwright and AnyIO retain incompatible session event loops.
The local `make test-cov` command stays serial.

Current authoring rules are in [content authoring](docs/CONTENT_AUTHORING.md).
Equipment metadata is bundled under `content/equipment`; optimization makes no network
requests and saves no computed recommendations. Missing requirements and unvalidated
effects remain inspectable and are excluded from quantified ranking. Prayers, boosts,
complex weapon/set effects, special utility, and damage-cap rerolls remain unsupported.
The preset templates state their phase/order assumptions explicitly. Phase-clear time
and final removal of compatibility tools remain follow-up work after acceptance.
The former weighted recommender design is preserved only as a
[historical specification](docs/SDD.md).
