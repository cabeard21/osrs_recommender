# Runic Ledger Gear preview — Milestone 4

Account-connected React/TypeScript/Vite/Tailwind preview with an isolated fixture mode. The architecture authority is
[the redesign plan](../../docs/GEAR_OPTIMIZER_REDESIGN_PLAN.md); the visual authority is
[the Stitch archive](../../docs/ui/runic-ledger.zip), especially its executable CSS.

## Launch

Use Node 22+ and the existing Python development environment.

```bash
cd frontend/gear
npm ci
npm run build
cd ../..
make run
```

Open `http://<configured-host>:<configured-port>/gear-next/`. The existing NiceGUI
`/gear`, dashboard, sync API, and health endpoint retain their existing behavior.
`/gear-next` redirects to `/gear-next/`. Generated JavaScript, CSS and local fonts
are served from `/gear-ui/`; existing local item sprites use `/gear-sprites/`.
The build output is `tracker/ui/gear_static/`, ignored by Git. Without a build,
`/gear-next/` responds with a Gear-specific 503 and build instructions; other routes
still start. Build before starting the server, then refresh the browser after rebuilds.
Image/wheel production packaging and production Gear cutover remain deferred.

For hot reload, keep Python running and use another terminal:

```bash
cd frontend/gear
npm run dev
```

Open `http://127.0.0.1:5173/gear-ui/`. Vite proxies local sprites to Python at
`http://127.0.0.1:8000`. For another Python address:

```bash
GEAR_BACKEND_ORIGIN=http://127.0.0.1:8080 npm run dev
```

Live mode is the default at `/gear-next/`. It uses Python endpoints
under `/ui-api/gear` for account context, equipment observations, physical item
inspection, and real single-style optimization. See [the API contract](../../docs/GEAR_BROWSER_API.md). No API token is
sent to React; these endpoints share the private dashboard network boundary.

Open `/gear-next/?mode=fixture` for the deterministic demonstrations below. The
fixture adapter remains available for tests and local demonstrations. Live mode
never falls back to fixtures. All live optimization metrics and purchase estimates
come from Python. Manual trials use exact Python fixed-loadout evaluation. Live
Multi remains unavailable.
Account context refreshes
on focus, every 30 seconds while visible, and on manual refresh.

## Fixture interactive states

1. Configure Single and inspect the demo equipment baseline.
2. Run the fixture simulation and inspect an immutable result with its submitted context.
3. Select any of eleven slots (including empty slots) to open the contextual inspector.
   Preview alternatives or an empty slot, revert the isolated trial, or edit draft
   locks/exclusions. Lock conflicts use an explicit unlock-and-exclude action.
4. Switch to Multi, edit/add/remove 2–4 configurations, and run the side-by-side fixture.
5. Switch to Interactive, select an active configuration, select a fixture curve point,
   and inspect shared item IDs and directed equipment actions.

A Single result can be copied as a fully locked Multi role, including empty slots.
Subsequent runs retain the previous accepted result for an equipment/metric/context
comparison. The handoff dialog provides selectable JSON and a clipboard action with
success/failure feedback; it does not fabricate chat responses.

Use **Demo outcome** for success, busy, no-solution, and error cases. Use **Demo
equipment observations** for complete, partial, or missing scans. Missing or partial
observations withhold baseline metrics rather than invent empty equipment. A context
failure can also be injected through the client constructor for tests.

The banner, account identity, item facts, metrics, comparisons, and provenance all
identify fixture data. Numbers are authored deterministic examples, not actual combat
calculations. Inputs are recorded in the submitted scenario; the adapter does not
execute optimization, validate production eligibility, or promise that its sample
loadouts satisfy budgets, supply reservations, or action limits. Fixture lock/exclusion
controls demonstrate state changes. Live locks, exclusions and manual trials use
authoritative Python validation.

## State boundaries

`GearProvider` owns read-only account or fixture context and separate Single/Multi workspaces.
Each workspace keeps draft configuration, submitted scenario, accepted/previous
results, manual trial, and UI selections separately. Draft edits invalidate an existing
result, preserve its original context, clear trials, and invalidate pending generations.
Cancel and superseded responses cannot publish. A changed context fingerprint rejects
publication. Changing result views or active configuration changes visualization only.

Only versioned draft configuration is saved in `sessionStorage`, keyed by the mode and
player ID. Results, account facts, and trial evaluations are not persisted. Reload
restores incomplete draft fields and prominently labels hypothetical assumptions.
Assumed skills, quest completion, and item acquisitions remain request-local.

## Live single-style workflow

1. Synchronize an account through the existing RuneLite integration and open `/gear-next/`.
2. Choose an ordinary-attack target, discipline, supported stance/spell, equipment access,
   additional integer GP budget and reserved supply slots. Requirements always apply.
3. Optional locks use exact physical IDs: a missing lock optimizes the slot and an empty
   lock forces it empty. In hypothetical mode, enter explicit skill levels, completed
   quest IDs and acquired physical IDs; these never modify the account.
4. Run optimization. Progress is indeterminate; cancel/edit aborts obsolete requests and
   signals cooperative backend cancellation. Busy and validation errors retain the draft.
5. Inspect the **Best configuration found**, Python DPS/max hit/accuracy/interval in
   seconds, equipment bonuses, required purchases, reused owned equipment and provenance.
6. Compare current equipment only when its projection and metadata support exact Python
   evaluation. Missing/ambiguous equipment produces reasons and unavailable metrics.
7. Inspect a slot, choose a contextual alternative or browse another physical item,
   and preview an exact manual trial. Compare DPS, max hit, accuracy, attack interval,
   equipment changes and additional purchase GP against a freshly evaluated original
   configuration. Invalid or unsupported trials show reasons with unavailable metrics.
8. Revert without changing the result or draft, or lock the alternative into the draft.
   Exclude items globally; a locked item requires explicit unlock-and-exclude.
9. Change the budget or constraints and reoptimize. Old results retain their submitted
   scenario and are marked outdated. Compatible previous results can be compared.

The synced account panel is a compact identity/sync/equipment summary with important
warnings visible. Expand **Detailed account observations** for container times, skills,
snapshot identity and diagnostics. Live Multi, alternate objectives, prayers and potions
remain unavailable. Fixture demos keep their existing scope.

Account, catalog/model and price revisions are retained with results. Refreshes invalidate
changed account/results and acquisition estimates; a changed account during a solve returns
a stale-context error. An HTTP abort does not forcibly terminate Python computation; the
existing optimizer checks cancellation cooperatively and holds its service lock until exit.

## Checks and screenshots

```bash
cd frontend/gear
npm test                 # Reducer, validation, persistence, UI and fixture failures
npm run check            # Strict TypeScript and formatting
npm run build
npm run test:coverage    # Coverage for live transport, result, provider and scenario state
npx playwright install chromium  # Once, if the pinned browser is not installed
npm run test:e2e          # Real FastAPI + NiceGUI, desktop and 390px Chromium, axe
cd ../..
.venv/bin/python -m pytest -m 'not browser' -q
.venv/bin/python -m pytest tests/ui/test_pages_browser.py -m browser -q
```

Verified Milestone 1 results: **28 frontend tests passed**, **4 browser checks passed**
(desktop/mobile workflows plus retained application routes), **650 non-browser Python
tests passed**, and **3 existing NiceGUI browser tests passed**. Strict TypeScript,
frontend formatting, production build, and focused Python lint/format checks passed.
No existing test regressions were found. The inspected browser states had no axe
violations and no page-wide overflow at 390px.

The browser suite uses a disposable SQLite database and local server on port 8766.
It exercises all five states, all equipment slots, Enter/Escape, focus restoration,
mobile modal focus containment, Single/Multi navigation, reload persistence, no page
horizontal overflow, accessibility scans, `/gear`, dashboard, `/healthz`, and the
unauthenticated sync rejection. It writes screenshots for each state at desktop
1600px and mobile 390px to [docs/ui/gear-preview](../../docs/ui/gear-preview/).

## Files and responsibilities

- `src/api/`: typed contracts, runtime validation, client boundary, and live HTTP adapter.
- `src/fixtures/`: deterministic context, item, result, transition and trial examples.
- `src/state/`: reducer, normalization, versioned draft persistence, context/provider.
- `src/components/`: shared configuration, eleven-slot grid, telemetry, inspector,
  Single/Multi results and native dialog behavior.
- `src/App.tsx`, `src/styles/`: reusable Runic Ledger shell and prototype visual tokens.
- `src/tests/`, `e2e/`: reducer/component tests and real-browser acceptance checks.
- `public/fonts/`: local font assets and SIL Open Font License notices.
- `tracker/ui/gear_preview.py`: static preview, bundle and sprite serving only.
- `tracker/app.py`: registers preview before NiceGUI's root mount.
- `tests/ui/test_gear_preview.py`: missing-build, static serving and route isolation tests.
- `.gitignore`: ignores frontend dependencies, generated bundle and test reports.

## Documented adjustments from Stitch

The original palette, typography families, spacing, surfaces, sidebar/header, gold
primary action, equipment-first hierarchy, eleven-slot arrangement, and Single/Multi
comparison patterns are retained. Readable wrapping replaces item-name truncation;
the fixed sidebar becomes a mobile menu; cards stack on phones; the inspector uses
an accessible dialog on small screens and a contextual right panel on desktop.

As required by the plan, generic targets and backend-aligned defaults replace
hardcoded Vorkath/account claims; local numeric-ID sprites replace Material Symbols
for equipment; fixture labels replace live connection claims; unsupported objectives,
degradable filtering and tag export are unavailable; the Space shortcut is removed;
and a copyable handoff replaces the scripted chatbot. Repeated screens share components
and reducer state. Motion is omitted because these state changes do not need animation.
The prototype's font families are bundled locally for offline rendering. Outline
Lucide icons replace the shell's Material Symbols to avoid a runtime icon-font
request while preserving the line-icon treatment.

Game artwork remains copyright Jagex Ltd.; sprites come from the existing RuneLite
cache bundle and retain [its attribution](../../tracker/ui/assets/items/source.json).
Fonts retain their notices in `public/fonts/`. No screenshot/HTML reference exports
are copied into the runtime bundle.

## Milestone deliveries and remaining work

See [the implementation report](../../docs/GEAR_MILESTONE_2.md) for verification,
files changed, representative live-mode screenshots, and observation limitations.
The screenshots use a disposable database and the real sync/read endpoints; they do
not depict the operator's account.

See [the Milestone 3 report](../../docs/GEAR_MILESTONE_3.md) for the real optimization
contract, exact baseline foundation, verification and screenshots. The disposable browser
server uses bundled equipment definitions and fixed cached prices; its test-only seed/reset
routes are never mounted by the production application. Windows and Unix virtual-environment
Python paths are supported by the Playwright launcher.

See [the Milestone 4 report](../../docs/GEAR_MILESTONE_4.md) for exact manual trials,
global exclusions, verification, representative screenshots and limitations. Each trial
changes only its selected slot. Other equipment, including shields and ammunition,
stays fixed; conflicts produce reasons rather than silent repairs. Trial cancellation,
revert, newer previews and relevant context changes invalidate pending responses.
Only draft configuration is persisted. Purchase lists can be copied with explicit
clipboard success/failure feedback.

Live joint optimization belongs to Milestone 5. Packaging and `/gear` cutover remain
later work; Milestone 4 does not change the production Gear entry point.
