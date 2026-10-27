# Gear Optimizer Redesign — Milestone 4 delivery

`/gear-next/` now supports **Optimize → Inspect → Preview → Compare → Revert or
Lock → Reoptimize** for one ordinary-attack role. Manual substitutions use the same
Python combat model, equipment eligibility and acquisition rules as the optimizer.
Global concrete physical-item exclusions apply across optimization and alternatives.

The Runic Ledger design, accepted/previous result separation, account synchronization,
NiceGUI `/gear`, and existing MCP tools are preserved. This delivery stops after
Milestone 4. No production cutover, live multi-style workflow or persistent results
were introduced.

## Implemented behavior

- The contextual inspector shows canonical physical item facts, the optimizer's
  validated alternatives, and separate catalog browsing. Missing or unsupported
  metadata remains explicit.
- Preview copies the accepted equipment and changes only the selected slot. It
  never silently removes a shield, changes ammunition, or modifies other equipment.
  Empty-slot trials are supported. Each new preview starts from the accepted result.
- A separate **Manual trial · exact Python evaluation** compares DPS, max hit,
  accuracy, attack interval in seconds, additional purchase GP, and equipment changes.
  Both configurations are reevaluated together; original cached metrics are not
  subtracted from a newly evaluated trial.
- Revert discards only the trial. Locking the alternative or excluding an item edits
  the draft and marks the accepted result outdated. A locked item requires explicit
  **Unlock and exclude**. Reoptimization preserves the previous accepted result and
  identifies the new **Reoptimized result**, retaining **Best configuration found**.
- Actual purchase lists can be copied from accepted results and trials. Clipboard
  failure provides selectable text and an explanation.
- Trial generations and abort controllers protect both live and fixture requests.
  New previews, selection changes, edits, revert, cancellation, navigation, accepted
  result changes, and account/catalog/model/price changes invalidate dependent trials.
  Late successes and errors cannot overwrite newer work. Trials/results are not saved
  in session storage; only versioned drafts are persisted.
- Inspector actions retain keyboard focus when trial content disappears. Escape and
  the existing desktop/mobile dialog behavior remain usable after locking or reverting.

## Backend contracts and shared validation

Full request/response and error details are in [GEAR_BROWSER_API.md](GEAR_BROWSER_API.md).

### Exact evaluation

```text
POST /ui-api/gear/evaluations
{
  scenario: BrowserOptimizationRequest,
  baseline_loadouts: { "<single-role-id>": EquipmentMap },
  proposed_loadouts: { "<single-role-id>": EquipmentMap }
}
```

`scenario` is the normalized domain scenario already returned by optimization.
Physical equipment maps use strict positive numeric IDs and physical slot names,
including `ammunition`; omitted slots are empty. Both maps must contain exactly the
submitted single ordinary-attack role. The service also rejects multi-role direct
evaluation rather than silently evaluating its first role.

The typed response includes:

- Normalized scenario/fingerprint, original account fingerprint, catalog/model
  versions, assumption fingerprint, price revision, calculation time and physical items.
- `baseline` and `proposed`: status (`valid`, `invalid`, `unsupported`), exact
  equipment, nullable performance, structured `{path, message}` reasons, nullable
  additional purchase total, concrete purchases with conditional-ownership flags,
  and hypothetical acquired IDs used by that configuration.
- Nullable `deltas`: signed proposed-minus-baseline DPS, max hit, accuracy, attack
  interval and purchase cost, equipment changes, and added/removed purchase IDs.
  Both configurations must be valid and supported before comparison deltas exist.

One frozen snapshot, hypothetical projection, catalog, price set and time feed both
configurations. Shared helpers cover requirements, access, locks, exclusions, prices,
and distinct purchases; the exact evaluator delegates combat to the existing model
without constructing candidate search. The optimizer calls the same access/cost and
complete-loadout validation policies. Formula code and search limits, traversal,
pruning, scoring and tie-breaking were not changed.

Owned equipment does not need a purchase quote. Unknown ownership remains conditional
acquisition, not free ownership. Unpriced unowned purchases remain unavailable.
Explicit future-mode assumptions remain request-local and cannot waive requirements.
Purchase differences do not assume resale proceeds or the prior purchase of the
original recommendation. The separate observed current-equipment baseline retains
its existing exemption from optimization locks, purchase access and budget.

Malformed requests, unknown physical IDs, wrong slots/role keys and contradictory
scenario constraints return field-addressed 422 errors. Recognized infeasible or
unsupported configurations return an explicit status with null performance and
deltas. The browser preserves those explanations instead of inventing numbers.

The route reuses same-origin protection, non-cacheable responses, worker execution,
the app-scoped service concurrency guard, pre/post account fingerprint checks and
cooperative cancellation. Stale accounts return 409, overlapping calculations return
503 `optimizer_busy`, and observed evaluation cancellation uses 499
`evaluation_cancelled`. Unexpected server errors expose a generic message.

### Exclusions

`OptimizationRequest.excluded_item_ids` is an immutable tuple, defaulting to empty,
with at most 500 strict positive concrete IDs. Unknown catalog IDs and conflicts with
global or role locks are rejected. Physical variants remain distinct.

Exclusions apply before candidate/scaffold preparation and during final validation,
covering individual, common and joint searches, special-role seeds, unrestricted and
curve results, and contextual alternatives. Existing domain multi-role search is
covered by regressions; it is not exposed as a new live browser capability. Unknown
hypothetical acquired IDs are now rejected consistently at the shared domain boundary.

## Files changed

| Files | Responsibility |
| --- | --- |
| `tracker/gear/evaluation.py`, `optimizer.py`, `service.py` | Shared fixed-loadout validation/acquisition, exact service evaluation and global exclusions |
| `tracker/api/gear_evaluations.py`, `gear_optimizations.py`, `tracker/app.py` | Typed evaluation route, browser exclusion validation and registration |
| `tests/gear/test_evaluation.py`, `test_exclusions.py`, `tests/api/test_gear_evaluations.py` | Domain/API parity, constraints, exclusions, stale/cancellation and provenance regressions |
| `frontend/gear/src/api/contracts.ts`, `httpClient.ts`, `contextualAlternatives.ts` | Live trial contracts, transport and runtime response validation |
| `frontend/gear/src/state/GearProvider.tsx`, `scenario.ts` | Independent guarded trial requests, invalidation and live exclusion submission |
| `frontend/gear/src/components/ItemInspector.tsx`, `LiveResultWorkspace.tsx`, `TrialComparison.tsx`, `PurchaseListCopy.tsx` | Inspect/preview/refine workflow, comparisons, labels, purchases and focus retention |
| `frontend/gear/src/App.tsx`, `components/ConfigurationPanel.tsx` | Current capability labels and constraint guidance |
| `frontend/gear/src/tests/refinement-state.test.tsx`, `refinement-ui.test.tsx`, `fixture-refinement-races.test.tsx`, `optimization.test.tsx` | Transport/state/UI coverage and updated exclusion expectation |
| `frontend/gear/e2e/server.py`, `refinement.spec.ts`, `vite.config.ts` | Disposable reviewed-item acceptance seed, browser refinement tests and scoped coverage |
| `docs/GEAR_BROWSER_API.md`, `frontend/gear/README.md`, this report | Contracts, workflow, verification and limitations |
| `docs/ui/gear-refinement/*.png` | Six representative desktop/mobile screenshots |

Pre-existing frontend, RuneLite version and contract-fixture changes were preserved.
No dependencies, production account data, database migrations or live configuration
were changed. Generated frontend build output remains ignored by Git.

## Verification

Tests preceded implementation: new endpoint/exclusion tests failed on the missing
behavior; the browser refinement journey failed on absent contextual alternatives.
A keyboard-focus regression was reproduced before its fix. Baseline checks passed
55 Python and 39 frontend tests before the feature was integrated.

Final results:

| Check | Result |
| --- | --- |
| Focused Python Gear, browser API, sync/auth/contracts, app/retained UI and MCP regressions | **306 passed** |
| Exact evaluator/API coverage run | **39 passed; 95% combined coverage** (evaluation module 93%, evaluation route 97%) |
| Frontend unit/integration suite | **97 passed** |
| Scoped frontend coverage | **89.29% lines, 88.74% statements, 82.67% branches, 91.91% functions** |
| Full desktop/mobile React Playwright suite | **12 passed** |
| Final rebuilt refinement browser rerun, including Escape after lock | **4 passed** |
| Retained NiceGUI browser journeys | **3 passed** |
| TypeScript, Prettier and production Vite build | Passed |
| Scoped Python Ruff and mypy | Passed |
| Scoped Python formatting and `git diff --check` | Passed |

The final four browser cases are a rerun of cases included in the twelve, not sixteen
unique cases. The coverage run is a subset of backend regression coverage. The tests
cover evaluator/search parity, handedness/ammo/slots, requirements and hypothetical
assumptions, ownership/budgets/prices, exclusion paths and conflicts, acquisition
differences, cancellation, stale accounts and trials, provenance, invalid responses,
fixture/live isolation, revert, navigation and clipboard failures.

Browser acceptance uses a disposable SQLite account, real FastAPI/NiceGUI routes,
existing reviewed Rune/Adamant scimitar and Fury definitions, and deterministic cached
prices. The test-only seed/reset routes are not registered by the production app.
No axe violations or page-wide mobile overflow were found in comparison states.
Final screenshots were visually inspected. Windows process/temporary-directory
restrictions required focused test/check execution outside the sandbox; tests then
passed against disposable data. No operator-account or physical desktop acceptance
is implied. The whole repository test suite and Java plugin tests were not rerun;
the focused surrounding Python/MCP/sync/NiceGUI regressions above were run.

Reproduce the frontend checks from `frontend/gear` with `npm.cmd run check`,
`npm.cmd run test:coverage`, `npm.cmd run build`, and `npm.cmd run test:e2e`.
The targeted browser subset is `npm.cmd run test:e2e -- refinement.spec.ts`.
Use the existing Python environment for `pytest tests/gear`, the Gear browser API
tests, sync/auth/contracts, retained UI/app and MCP regressions; the NiceGUI browser
journeys remain `pytest tests/ui/test_pages_browser.py -m browser`.

## Representative screenshots

These depict disposable acceptance data, not the operator's account or a production
performance benchmark. The browser displayed the actual Python response values.

| State | Desktop | Mobile |
| --- | --- | --- |
| Exact manual comparison and acquisition difference | [View](ui/gear-refinement/desktop-comparison.png) | [View](ui/gear-refinement/mobile-comparison.png) |
| Reoptimized locked alternative with previous result | [View](ui/gear-refinement/desktop-reoptimized.png) | [View](ui/gear-refinement/mobile-reoptimized.png) |
| Invalid budget replacement with reasons | [View](ui/gear-refinement/desktop-invalid-trial.png) | [View](ui/gear-refinement/mobile-invalid-trial.png) |

## Limitations, architecture adjustments and Milestone 5

Catalog review coverage, tri-state ownership and aggregated equipment observations
retain their existing limits. Cached purchase quotes are estimates. Unsupported
effects, unknown requirements and unavailable acquisition prices remain explicit.
The combat model still excludes prayers, boosts, scored specials, defensive/survival
optimization, supply endurance and encounter-completion estimates. Search is bounded
and remains **best found**, with existing diagnostics.

Trials are independent single-slot substitutions into the accepted setup. A locked
slot cannot be replaced under that submitted scenario; change its draft constraint
and reoptimize. Two-handed and ammunition conflicts are explained without companion
slot edits. Changed account/catalog/model/price provenance invalidates dependent
trials; users must refresh and reoptimize. Cancellation is cooperative and does not
forcibly kill a worker thread. Results are ephemeral.

The evaluation request retains Milestone 3's raw normalized domain scenario inside
`scenario`, rather than adding the redesign document's extra `SubmittedScenario`
wrapper. Its role-keyed baseline/proposal maps follow the architecture shape while
the endpoint remains restricted to one ordinary role. Typed DTOs use a focused
evaluation route beside optimization. These are transport organization choices;
there is no combat/search architecture deviation. Source correctness/security review
found no unresolved high or medium issues.

Milestone 5 still owns live joint multi-style submission, shared purchase unions,
existing exact directional equipment transitions/inventory constraints, curve-point
selection and cross-role comparisons with matching provenance. This delivery does
not begin that integration. Production packaging/deployment and replacing `/gear`
remain later, separately authorized work.
