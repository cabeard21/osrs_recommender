# Gear Optimizer Redesign — Milestone 5 delivery

`/gear-next/` supports live **joint multi-style optimization** for two through four
configurations. One call to the existing Python `GearService.optimize` supplies
every loadout, curve point, purchase union, transition and inventory requirement.
Side-by-side and Interactive Switching display the same selected solution.

Runic Ledger styling and completed Single workflows are retained. Production
NiceGUI `/gear`, RuneLite synchronization, MCP contracts and the optimizer's combat
formulas, pruning, beam widths and expansion budget are unchanged. The ammunition
correctness follow-up below adds bounded sharing refinement to completed finalists.
This delivery stops after Milestone 5; no production cutover was performed.

## Implemented behavior

- Ordinary roles retain independent targets, disciplines/attack types, stances,
  supported standard spells, finite active-time weights and equipment locks.
  Repeated disciplines are supported through unique role IDs.
- Global locks, physical-item exclusions, additional acquisition budgets and
  request-local hypothetical assumptions use existing Python semantics. Shared
  purchases are counted once across the complete physical-item union.
- Advanced transition settings expose base round trips, explicit directed edges,
  repeated ordered phases and optional looping. Action limits and supply reservations
  use the existing 0–12 and 0–28 ranges. Role deletion reports removed references and
  a replacement base where needed; dependent utility roles must first be removed or
  reparented. Invalid remaining configuration blocks submission.
- Unscored utility roles retain an ordinary parent and explicit weapon lock. Their
  equipment consumes budget, actions and inventory capacity, with null combat metrics
  and no ordinary active-time share. No special-attack benefit is calculated.
- Two equipment grids show the selected joint solution. Three/four-role results
  offer comparison-pair selectors. Interactive Switching selects an active role and
  a backend-provided directed action sequence, including automatic hand removals.
- Curve selection updates role metrics, aggregate DPS, physical items, shared markers,
  purchases, actions and inventory together, without another optimization request.
  Only returned points exist; null solutions stay unavailable. The backend's 95%
  suggestion is relative to its unrestricted best-found reference and does not
  automatically replace the user's selection.
- The unrestricted reference is **best found without the swap-action limit**.
  Account, requirements, acquisition budget, inventory and model constraints remain.
- Changed equipment slots, equipment actions, gear inventory slots and unique required
  items are separate quantities. `carried_item_ids` includes equipped items; actual
  inventory outside a role is that union minus its equipped items. Base occupancy,
  transient peaks, supply reservations and remaining capacity retain backend values.
- Physical inspection works for the selected role and curve point. Global/role locks
  and exclusions edit the draft and invalidate accepted results. Exact Multi manual
  trials and single-role contextual alternatives are unavailable with an explanation;
  no first-role trial is represented as a joint comparison.
- Single/Multi drafts, submitted scenarios, accepted/previous results and visualization
  selections remain separate. Draft v2 migration preserves old shared target assumptions
  as independent role targets, including incomplete numeric drafts. Context changes,
  edits, cancellation and superseded generations prevent stale publication.

## API and file changes

The complete contract is in [GEAR_BROWSER_API.md](GEAR_BROWSER_API.md).
`POST /ui-api/gear/optimizations` now accepts the existing one-to-four-role domain
request; Single remains compatible. Browser validation examines every role and
returns field paths for invalid combat inputs, references, targets, locks and topology.
The full existing result contract is preserved, with typed transition/action DTOs.

Same-origin protection, private dashboard access, non-cacheable responses, worker
execution, app-scoped concurrency protection, cooperative cancellation, frozen prices,
scenario fingerprint and pre/post snapshot checks remain in place. Multi observed
baseline comparison is unavailable with a clear reason; first-role DPS is not a joint
baseline. `/ui-api/gear/evaluations` independently enforces exactly one ordinary role.

| Files | Responsibility |
| --- | --- |
| `tracker/api/gear_optimizations.py`, `gear_scenario_validation.py`, `gear_evaluations.py` | Joint browser requests, field validation, typed actions and retained Single evaluation boundary |
| `frontend/gear/src/api/contracts.ts`, `httpClient.ts`, `jointResults.ts`, `runtime.ts` | Full typed transport, runtime validation, nullable metrics and exact joint facts |
| `frontend/gear/src/state/scenario.ts`, `GearProvider.tsx` | Domain normalization, selections, draft migration and context/generation guards |
| `ConfigurationPanel.tsx`, `RoleTargetEditor.tsx`, `MultiTransitions.tsx`, `MultiLockEditor.tsx`, `multiDraft.ts` | Role targets, topology, locks and visible reference cleanup |
| `LiveMultiResultWorkspace.tsx`, `JointSolutionDetails.tsx`, `ResultWorkspace.tsx`, `EquipmentGrid.tsx` | Joint equipment, curve, actions, inventory, purchases and accessible shared/difference indicators |
| `ItemInspector.tsx`, `LiveResultWorkspace.tsx`, `App.tsx`, fixture client | Selected-role inspection, Multi trial restriction, Single nullable guards and live Multi shell |
| `tests/api/test_gear_joint_optimizations.py`, existing optimization tests | Domain/API parity, constraints, provenance and request lifecycle coverage |
| Frontend joint transport/state/configuration/result/inspector test suites | Live joint editing, result consistency, invalidation, migration and race coverage |
| `frontend/gear/e2e/joint.spec.ts`, `e2e/server.py` | Disposable real-backend desktop/mobile two-, three- and four-role acceptance |
| `tools/benchmark_gear_joint.py`, `tests/test_benchmark_gear_joint.py` | Reproducible synthetic full-catalog performance matrix |
| API docs, frontend README, this report, `docs/ui/gear-joint/*.png` | Contracts, usage, verification and screenshots |

Pre-existing unrelated work was preserved. No dependencies, account data, database
migrations, production configuration, authored equipment definitions or production
routes were changed. Generated frontend assets remain ignored.

## Verification

Tests preceded implementation: 24 joint API cases failed against the former
single-role boundary; inspector tests failed on first-role lookup and absent scope
controls; result/configuration tests failed on missing joint UI. Browser acceptance
also reproduced an accessible-name mismatch for equipment differences before its fix.

Independent review identified and resolved supported-but-unscored utility parsing,
unintended base-to-utility edges, and effective-target preservation when copying a
Single result into an existing Multi draft. Final review found no unresolved high or
medium correctness/security findings in the reviewed changes.

| Check | Result |
| --- | --- |
| Focused Gear, API, sync/auth/contracts, retained UI/app and MCP regressions | **391 passed** |
| Focused API, optimizer and transition coverage run | **129 passed; 97.22% touched API coverage** |
| Frontend unit/integration coverage run | **166 passed** |
| Frontend scoped coverage | **89.79% lines, 89.41% statements, 85.77% branches, 90.71% functions** |
| Complete React desktop/mobile Playwright suite | **18 passed**, including six joint cases |
| Retained NiceGUI browser journeys | **3 passed** |
| Benchmark tooling tests | **5 passed; 98% branch-aware coverage** |
| Strict TypeScript, frontend formatting and production Vite build | Passed |
| Scoped backend Ruff, formatting and mypy | Passed |
| `git diff --check` | Passed |

The 129-case API coverage run and five benchmark tests are subsets of the 391-case
regression selection. A final six-case joint browser rerun captured readable mobile
viewport screenshots; those cases are included in the eighteen, not additional
unique journeys. Representative desktop comparison and mobile equipment/transition
screenshots were visually inspected.

The joint browser journey configures two roles with different targets/weights, sets
an action limit, submits one solve, checks the returned weighted score, selects a
computed point, checks inventory, switches views, inspects the actual directed
sequence and item-inspector limitations, and returns to side-by-side. It asserts
exactly one optimization POST and zero evaluation POSTs. Three/four-role cases verify
real joint loadout counts and two-grid comparison selection. Both desktop and 390px
mobile states pass axe checks and page-width overflow checks.

Browser data is disposable: seven reviewed bundled physical definitions, synthetic
observations and deterministic cached prices, served by the real FastAPI/NiceGUI app.
Test-only reset/seed endpoints are never mounted by production `create_app`.
Screenshots depict this disposable account, not the operator's account.

Reproduce frontend verification in `frontend/gear` with `npm.cmd run check`,
`npm.cmd run test:coverage`, `npm.cmd run build`, and `npm.cmd run test:e2e`.
Run retained browser journeys with `.venv\Scripts\python.exe -m pytest
tests/ui/test_pages_browser.py -m browser`. Windows sandbox process/temp restrictions
required scoped execution outside the sandbox; all data stayed disposable/local.

## Full-catalog performance measurements

Measured October 27, 2026 on Windows 10 Home 64-bit build 19045, Python 3.12.10,
AMD Ryzen 5 5600X (6 physical/12 logical cores). Concurrent development activity was
present; CPU scheduling was not isolated. These are local measurements, not Pi or
production acceptance evidence.

The reproducible synthetic level-99 member account has authored quests complete,
four owned starter items, deterministic cached quotes, a 5,000,000 GP budget, twelve
reserved supply slots and base round-trip topology. Roles are slash, ranged, magic,
and a second melee role where applicable. Each case ran three times with a frozen
clock and identical repeated results.

The full bundled catalog had **5,435 physical definitions, 188 eligible items**;
revision `df16ae83df6462b2607934f53e244ea8993d671849b9ff5ab485ea1342f03850`.
Retained candidate pool sizes, including empty choices, were weapon 12, shield 10,
ammunition 11, head 12, cape 3, neck 12, body 12, legs 12, hands 8, feet 12, ring 4.

| Roles | Action limit | Median optimizer seconds | Observed range | Explored nodes |
| --- | --- | --- | --- | --- |
| 2 | 0 | 2.249 | 2.195–2.345 | 55,635 |
| 2 | 4 | 3.254 | 2.908–3.588 | 128,133 |
| 2 | 8 | 3.882 | 3.601–4.037 | 201,333 |
| 3 | 0 | 4.613 | 4.563–4.811 | 88,724 |
| 3 | 4 | 5.421 | 5.373–5.472 | 183,828 |
| 3 | 8 | 8.427 | 7.951–9.066 | 317,012 |
| 4 | 0 | 4.011 | 3.879–4.023 | 132,884 |
| 4 | 4 | 5.907 | 5.735–6.691 | 292,820 |
| 4 | 8 | 11.313 | 10.783–16.367 | 510,100 |

All cases reported `candidate_truncation: true` and `bounded_search_complete`.
Zero-action cases found no selected solution in this fixture; that is not a proof
of mathematical infeasibility. Successful bounded search does not prove optimality.
The four-role/eight-action median candidate-generation stage was 0.457 seconds and
search/response stage 10.765 seconds. Separately measured NiceGUI construction was
0.125 seconds and is excluded from optimizer duration; medians are not additive.

Reproduce with `.venv\Scripts\python.exe -m tools.benchmark_gear_joint --directory
.tmp/m5-joint-fresh --repeats 3`. The harness refuses to overwrite its synthetic DB.
Raw local reports are in ignored `.tmp/m5-joint-measurements/summary.json` and per-case
files. Browser subset timings are not used as representative optimizer measurements.

Four-role latency merits follow-up profiling and ARM64 measurements before production
integration. This milestone does not change search limits or algorithms to reduce it.

## Screenshots and remaining work

| State | Desktop | Mobile |
| --- | --- | --- |
| Two-role joint side-by-side | [View](ui/gear-joint/desktop-side-by-side.png) | [View](ui/gear-joint/mobile-side-by-side.png) |
| Selected curve, active role and directed transition | [View](ui/gear-joint/desktop-switching.png) | [View](ui/gear-joint/mobile-switching.png) |
| Three-role comparison | [View](ui/gear-joint/desktop-3-role.png) | [View](ui/gear-joint/mobile-3-role.png) |
| Four-role comparison | [View](ui/gear-joint/desktop-4-role.png) | [View](ui/gear-joint/mobile-4-role.png) |

Catalog review limits, tri-state ownership, cached-price estimates, one-instance/stack
physical identity and cooperative cancellation remain unchanged. Unsupported combat
mechanics, survivability, consumption simulation and per-item multi-role attribution
remain unavailable. Results/history are not persisted.

Production static packaging, container/ARM64 verification, deployment and replacing
`/gear` remain separately authorized Milestone 6 work. No operator-account, physical
gameplay, live RuneLite or deployed Pi acceptance is claimed. The whole repository
and Java plugin suites were not rerun; verification targets the affected browser/API
surface and surrounding Gear, sync, contracts, MCP and retained UI behavior.

## Correctness follow-up — redundant ammunition switches

A reproduced melee/ranged case chose Iron arrows for melee and Adamant arrows for
ranged even though sharing Adamant preserved every attack metric. It also left the
one-action curve point empty despite a legal equally strong one-action configuration.
The issue was search retention: role-specific slot branches keep only a few choices,
and melee ammunition ties can discard the ranged role's useful shared arrow before
final comparison. Final action tie-breaking cannot recover an assignment already lost.

`tracker/gear/refinement.py` now checks ammunition assignments among distinct completed
curve/unrestricted finalists. Choices are only already-required ammunition IDs and
empty, bounded by five choices across four roles (625 assignments per finalist).
Explicit role/global locks and utility-role equipment remain fixed. Each ordinary
role retains exact DPS, max hit, accuracy, interval and attack/defence rolls, including
zero-weight roles; defensive and prayer bonuses cannot decrease.

Every proposal passes the existing complete solution validator. Purchase unions,
directed action sequences, automatic removals and transient inventory are recomputed.
Purchase cost, base/peak inventory, each transition's actions and each transition's
peak occupancy cannot increase. Otherwise tied ammunition choices prefer fewer
required items, which also removes irrelevant unlocked arrows from Single melee or
melee/magic results. Protective ammunition bonuses are preserved. No other slots are
changed by this refinement, and no new purchases or catalog candidates are introduced.

Improved finalists are reconsidered for every compatible action limit. The regression
now shares Adamant, removes the ammunition action and populates the missing one-action
curve point without reducing performance. Diagnostics expose
`search.ammunition_refinement.evaluated_assignments` and `improved_finalists`.
Cancellation is checked during enumeration. This is a bounded local correction,
not a global-optimality guarantee or a general replacement search algorithm.

Follow-up verification: **247** focused Gear/API/UI-helper/MCP regressions passed.
The final expanded ammunition and joint API selection passed **62 tests**, including
18 targeted safeguards, with **100% statement and branch coverage** of the refinement
module. It covers explicit global/role/empty locks, harmful donor bonuses, prayer and
defence preservation, utility equipment, tight directed capacity, exact shared purchase
budgets, cancellation, determinism, and requested action limits one and four.
**12** desktop/mobile joint and Single optimize/inspection/refinement browser journeys
passed. These overlapping follow-up runs are not additions to the milestone's
unique-test totals above. Scoped Ruff, formatting, mypy and whitespace checks passed.

On the same frozen four-role/eight-action catalog scenario, three alternating runs
with refinement disabled/enabled measured optimizer medians **9.792 s / 10.415 s**.
Direct refinement time was **0.065 s median**, eight distinct-finalist calls and 56
evaluated assignments. The total-time difference includes concurrent-machine noise.
All selected/unrestricted/curve solutions were identical because this scenario already
shared ammunition; explored nodes remained 510,100. Raw comparison reports are in
ignored `.tmp/ammo-sharing-performance/summary.json`. The original nine-case table
above records the pre-follow-up integration measurements.

Pre-commit security review found no unresolved high/medium source findings. Frontend
dependency audit reported zero vulnerabilities. The local Python audit initially
flagged `msgpack` 1.2.2 in the audit tool's CacheControl dependency chain; an
environment-only update to 1.2.3 cleared it. `pip check`, serialization/cache smoke
checks and a fresh audit passed. No repository dependency constraints were changed;
the two local editable project packages have no PyPI entries and cannot be audited
as published third-party distributions.
