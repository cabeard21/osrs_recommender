# Gear Optimizer Redesign — Milestone 3 delivery

`/gear-next/` now runs the existing Python optimizer for one ordinary-attack combat
style. React displays its selected physical equipment, DPS, max hit, accuracy, attack
interval, equipment bonuses, purchase costs and bounded-search diagnostics. A valid
observed loadout is evaluated under the same combat assumptions for comparison.

The Runic Ledger shell and eleven-slot layout remain. The synchronized account panel
now summarizes identity, last sync and equipment status, with critical warnings visible
and detailed observations expandable. `/gear` remains the existing NiceGUI page.

## Backend API and execution

`POST /ui-api/gear/optimizations` accepts the existing domain optimization request,
restricted to one scored ordinary-attack role, with a required expected account
fingerprint. Targets, attack type/stance, standard spells, owned/purchasable/future
access, integer additional GP budget, global/role physical locks, skill/quest overrides,
assumed acquired items and inventory reservations retain the existing semantics.

The browser adapter independently rejects unknown IDs, invalid combat/target values,
unsupported mechanics, conflicting locks, invalid assumptions and negative budgets.
Structured errors include field paths. Cross-origin browser POSTs are rejected; the
documented Vite proxy is supported. Browser route handlers remain separate from the
bearer-protected RuneLite API.

Account/price reads and calculations execute through worker threads. The app-scoped
`GearService.optimize` remains the concurrency boundary. Overlapping requests receive
503 `optimizer_busy`; no background job infrastructure or persistent results were added.
Disconnect and task cancellation set an event passed to the existing cooperative
cancellation callback. Aborting HTTP does not forcibly stop the Python thread.

The endpoint rereads authoritative account observations after calculation and rejects
a changed fingerprint with 409 `snapshot_changed`. Results retain frozen account,
catalog, model, scenario, assumption, price and calculation-time provenance. Requests
and responses are non-cacheable. Hypothetical assumptions never modify the account.

The typed response contains `scenario`, `scenario_fingerprint`, `price_revision`,
the preserved domain `result`, physical `items`, and a single-role `baseline`.
`selected_solution: null` is a completed search with no feasible solution found.
Purchases preserve concrete IDs, conditional ownership and distinct/shared-purchase
semantics. Full contracts and errors are in [GEAR_BROWSER_API.md](GEAR_BROWSER_API.md).

## Shared exact-evaluation foundation

`tracker/gear/evaluation.py` validates physical IDs, slot assignments and handedness,
then delegates to the existing `combat.evaluate_loadout`. The optimizer and baseline
both call this foundation. Formulas, candidate limits, pruning, ordering, scoring and
tie-breaking are unchanged.

The baseline starts from the conservative Milestone 2 equipment projection. All slots
must be observed or known empty, physical metadata must resolve, equipment requirements
must be satisfied, and combat must be supported. The same target, stance, spell and
hypothetical skill/quest assumptions apply. Newly imposed optimization locks, budget
and purchasing restrictions do not reject an otherwise valid observed loadout.

Incomplete scans, unknown IDs, ambiguous slots, unsupported effects or unknown
requirements produce an unavailable baseline with explicit reasons and null performance.
Unknown slots never become guessed empty slots. Optimization can still succeed.
There is no public arbitrary-loadout evaluation endpoint in this milestone.

## React behavior

`HttpGearClient` posts normalized domain requests and validates returned identity,
scenario, physical equipment, metrics and acquisition facts. Live results never call
the fixture optimizer. `FixtureGearClient` retains isolated demonstrations, including
its Multi and manual-trial examples.

The submitted scenario, editable draft, accepted result and previous result remain
separate. Edits abort pending transport, increment generations and mark prior results
outdated. Cancelled/superseded responses cannot publish. Account refreshes reject work
for changed observations; changed catalog/model/price revisions invalidate retained
context. Compatible previous results retain a performance comparison; differing target,
account, assumptions or model/catalog contexts withhold it.

Live configuration offers existing ordinary-attack target metadata or an explicit
custom target, supported discipline/stance/spell, budget/access, physical locks and
request-local hypothetical assumptions. Custom targets currently configure Defence
and name, with explicit Magic-level-1/zero-bonus defaults; the backend accepts the full
supported `CombatTarget`. Progress is indeterminate. Result item inspection reuses the
Milestone 2 API with physical names, sprites, ownership and price provenance.

## Files modified

| Files | Purpose |
| --- | --- |
| `tracker/api/gear_optimizations.py` | Typed single-role browser request/result, validation, origins, execution, cancellation, snapshot guards and baseline |
| `tracker/api/gear_ui.py`, `tracker/app.py` | Local structured field errors, DPS capability and route registration |
| `tracker/gear/evaluation.py`, `tracker/gear/optimizer.py` | Shared exact physical/combat validation without search changes |
| `tests/api/test_gear_optimizations.py`, `tests/api/test_gear_ui.py`, `tests/gear/test_evaluation.py` | Endpoint/service parity, malformed scenarios, cancellation/busy/stale state, provenance and baseline regressions |
| `frontend/gear/src/api/contracts.ts`, `httpClient.ts` | Typed live result, normalization, runtime contract validation and transport |
| `frontend/gear/src/state/GearProvider.tsx`, `scenario.ts` | Live submission, immutable contexts, cancellation, invalidation and previous results |
| `frontend/gear/src/App.tsx` | Compact account summary, live action/progress and result provenance |
| `frontend/gear/src/components/LiveResultWorkspace.tsx`, `ResultWorkspace.tsx`, `PerformanceSummary.tsx` | Backend results, exact baseline and previous-result comparisons |
| `frontend/gear/src/components/ConfigurationPanel.tsx`, `EquipmentGrid.tsx`, `ItemInspector.tsx` | Supported live controls, selected physical equipment, locks and inspection |
| `frontend/gear/src/tests/optimization.test.tsx`, `live.test.tsx` | Transport, submission/results/errors, cancellation, stale responses, context races and isolation |
| `frontend/gear/e2e/optimization.spec.ts`, `live.spec.ts`, `server.py`, `playwright.config.ts` | Disposable deterministic live workflow, real sync/retained routes, desktop/mobile and Windows launcher |
| `frontend/gear/package.json`, `package-lock.json`, `vite.config.ts`, `.gitignore` | Reproducible scoped coverage and development-tool security fix; ignored generated coverage |
| `docs/GEAR_BROWSER_API.md`, `frontend/gear/README.md`, this report | API, usage, verification and limitations |
| `docs/ui/gear-optimization/*.png` | Representative desktop/mobile results, inspection and unavailable baseline |

## Verification

Tests were written before implementation: the new browser workflow initially failed
on the disabled optimization action, and the new backend endpoint tests initially
returned 404. The completed implementation passes direct service/browser numerical
parity using existing validated Python combat code; no frontend formula supplies
expected combat results.

- Focused Python regressions: **298 passed** across the 293-case regression run and
  the final five exact-evaluator/cached-quote cases, covering Gear, browser API,
  sync/auth, retained UI/app boundaries and MCP contracts.
- Retained NiceGUI browser journeys: **3 passed**.
- Playwright preview acceptance: **8 passed**, across desktop 1600px and mobile 390px.
  Includes real configure → optimize → inspect → change budget → reoptimize → compare,
  unavailable baseline, authoritative sync, fixture isolation and retained routes.
- No axe violations or page-wide mobile overflow in the inspected result/inspector states.
- Backend new-module coverage: **95%**, above the 80% requirement.
- Frontend: **44 tests passed**; scoped live-path coverage **89.47% lines**, **88.45%
  statements**, **81.89% branches**, **89.77% functions**, with enforced 80% aggregate
  thresholds for transport, provider/scenario state and the live result component.
- Strict TypeScript, Prettier, production Vite build and `git diff --check` passed.
- Development dependency audit after the scoped tooling remediation: **0 vulnerabilities**.

Backend focused Ruff and mypy checks passed. Disposable SQLite databases and local
servers were used; no operator account, production data or migrations were involved.
Windows subprocess/socket restrictions required focused checks outside the sandbox.

## Representative screenshots

These are actual Python optimizer responses against a disposable account and a tiny
subset of existing bundled equipment definitions. They do not depict the operator's
account or a production benchmark.

| State | Desktop | Mobile |
| --- | --- | --- |
| Best found, exact baseline, purchases and previous result | [View](ui/gear-optimization/desktop-optimized.png) | [View](ui/gear-optimization/mobile-optimized.png) |
| Physical item and cached price provenance | [View](ui/gear-optimization/desktop-inspector.png) | [View](ui/gear-optimization/mobile-inspector.png) |
| Successful optimization with unavailable observed baseline | [View](ui/gear-optimization/desktop-unavailable-baseline.png) | [View](ui/gear-optimization/mobile-unavailable-baseline.png) |

## Performance observations and limitations

The complete deterministic configure/reoptimize/inspect/partial-baseline browser journey
took **2.7 seconds on desktop** and **1.7 seconds on mobile** in the final local run;
all eight preview checks completed in 25.4 seconds. These totals include browser actions
and use only two existing physical definitions. They are not full-catalog production
latency measurements. Tests also verify request responsiveness while a worker runs.

Search remains bounded and reports **Best configuration found**, candidate truncation
and termination details. No mathematical/global optimum or infeasibility proof is claimed.
Cancellation is cooperative and may wait through candidate preparation until an existing
checkpoint; stale/cancelled work cannot overwrite newer browser state.

Physical catalog coverage, aggregated equipment observations and tri-state ownership
retain their prior limitations. Cached purchases are estimates rather than guaranteed
fills. Unsupported effects or missing prices are not approximated. The model still
excludes prayers, boosts, scored specials, survival, combat downtime, supply endurance,
full boss mechanics and encounter completion time. Account selection remains the
dashboard's first-player policy.

## Adjustments and remaining work

The response uses a single-role `baseline` object rather than the architecture plan's
proposed role-keyed baseline record; the domain `result` is preserved in full. Browser
DTOs/execution live in a focused `gear_optimizations.py` module beside the existing
read routes. These are transport organization choices, not optimizer changes.

Coverage tooling exposed pre-existing vulnerabilities in development-only Vitest 3,
its mocker and Tinypool. Security review selected a scoped Vitest/coverage update to
4.1.12, retaining the existing Vite and React versions. No application runtime exploit
was demonstrated; this is a development-tool remediation, not a new runtime feature.

Milestone 4 still owns arbitrary fixed-loadout evaluation, manual replacement/trial
integration and global physical-item exclusions. Milestone 5 owns live multi-style
optimization. Packaging, deployment and production `/gear` cutover remain separate.
This delivery stops after Milestone 3.
