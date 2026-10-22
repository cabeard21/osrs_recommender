# Gear Optimizer Redesign — Milestone 2 delivery

The React preview now reads account, equipment, ownership, eligibility, physical item
metadata, and cached price provenance from the existing Python backend. The Runic
Ledger shell, eleven-slot grid, Single/Multi workspaces, shared state and responsive
inspector remain in place. `/gear-next/` defaults to live mode; `?mode=fixture` opens
a separate, visibly labeled demonstration. Live mode cannot execute fixture solves.

The three read-only endpoints are documented in [GEAR_BROWSER_API.md](GEAR_BROWSER_API.md).
No combat calculations, optimizer search, sync contracts, MCP behavior, database
schema, or production `/gear` entry point were replaced. No migrations were needed.

## Implementation

Account reads reuse `AccountService` and `AccountSnapshot.summary()`/fingerprints.
Equipment projection uses accepted concrete observations and physical catalog slots.
Ambiguous candidates, impossible nonstackable quantities, two-handed/offhand conflicts,
unmapped IDs and missing scans remain explicit. No slot position is invented. All
live slots open the inspector even when equipment is unknown.

The physical accessor reuses `equipment_fact`, the shared requirement evaluator,
`observed_ownership`, `DatabaseGearPrices`, and `resolve_price`. It preserves numeric
variant identity and requirement coverage flags, and exposes raw and selected quote
provenance. Cached quotes, static authored hints and unavailable prices stay distinct.
The browser does not evaluate requirements or infer ownership.

Context refreshes on focus, every 30 seconds while visible, and manually. Errors do
not trigger fixture fallback. Current equipment has no mock metrics. Fixtures retain
the original deterministic result/trial workflow in their separate mode. Live and
fixture draft storage keys are separate; results are not persisted across reloads.

One configured-content-root-aware `GearService` now serves the app's browser routes
and retained NiceGUI Gear page. Browser errors use the documented typed envelope.
Responses are not cacheable. The existing private dashboard bind policy is unchanged;
RuneLite `/api/sync` remains bearer-protected and tokens are not shipped to React.

## Files changed

| Files | Purpose |
| --- | --- |
| `tracker/api/gear_ui.py` | Read-only routes, validated DTOs, error envelope, conservative equipment projection |
| `tracker/gear/service.py` | Concrete physical-item accessor and physical catalog name/ID search |
| `tracker/app.py`, `tracker/ui/pages.py` | App-scoped service and route registration before NiceGUI |
| `frontend/gear/src/api/contracts.ts`, `httpClient.ts` | Live DTO mapping, runtime validation, browsing, disabled live solve/evaluation |
| `frontend/gear/src/main.tsx`, `state/GearProvider.tsx` | Explicit live/fixture adapter selection and live execution guard |
| `frontend/gear/src/App.tsx` | Account identity, scans, skill observations, refresh/error states and mode labels |
| `frontend/gear/src/components/EquipmentGrid.tsx`, `ResultWorkspace.tsx` | Observed/empty/unknown/ambiguous slots; no fabricated live metrics |
| `frontend/gear/src/components/ItemInspector.tsx` | Physical details, candidates, ownership/requirements/provenance, search/pagination |
| `frontend/gear/src/components/ConfigurationPanel.tsx`, `styles/index.css` | Draft labels, wrapping and accessible mode-switch links |
| `tests/api/test_gear_ui.py` | Account/scan/ownership/variant/requirements/pricing/API coverage |
| `frontend/gear/src/tests/live.test.tsx`, `live-context.json` | Real API-shaped contract sample, live rendering/errors/validation and mode isolation |
| `frontend/gear/e2e/live.spec.ts`, `server.py`, `workflows.spec.ts` | Disposable real-backend live journeys and retained fixture/browser regressions |
| `frontend/gear/README.md`, `docs/GEAR_BROWSER_API.md`, this report | Launch, contract, implementation and limitations |
| `docs/ui/gear-live/*.png` | Representative live-mode screenshots |

## Verification

- Full Python regression suite: **667 passed**, including existing NiceGUI browser,
  account/sync/authentication, Gear calculations/search, pricing, and MCP regressions.
- Frontend Vitest suite: **33 passed**.
- Playwright: **6 passed** across desktop (1600px) and mobile (390px), including real
  sync → context refresh → ambiguous-candidate inspection, fixture isolation,
  retained NiceGUI/dashboard routes and bearer rejection.
- Browser accessibility checks: no axe violations in inspected fixture/live states.
- No page-wide overflow at 390px in the checked workspaces.
- Strict TypeScript, Prettier, production Vite build, focused Ruff and mypy passed.

Python FastAPI tests and Chromium needed execution outside this environment's socket
sandbox. Tests use disposable databases; no operator account or schema was changed.
The screenshots below are test-account observations served by the actual Python APIs,
not screenshots of the operator's account or simulated optimization results.

## Screenshots

| State | Desktop | Mobile |
| --- | --- | --- |
| Missing equipment scan / configured account before sync | [View](ui/gear-live/desktop-missing-scan.png) | [View](ui/gear-live/mobile-missing-scan.png) |
| Partial metadata and ambiguous weapon observations | [View](ui/gear-live/desktop-partial-observations.png) | [View](ui/gear-live/mobile-partial-observations.png) |
| Authoritative physical candidate inspection | [View](ui/gear-live/desktop-physical-inspector.png) | [View](ui/gear-live/mobile-physical-inspector.png) |

Reproduce with `npm run build --prefix frontend/gear` followed by
`npm run test:e2e --prefix frontend/gear`. The test server's reset route exists only
in `e2e/server.py` against its disposable database; it is not installed by the app.

## Known limitations

- Sync does not preserve equipment slot indices. Projection cannot manufacture them;
  unknown physical IDs and conflicting candidates prevent a complete layout.
- The observation store retains latest accepted sightings and scan anchors, not a full
  ownership history. Historical possession after a sighting disappears remains unknown.
  Old bank/inventory/equipment sightings retain their dates and never imply online status.
- Missing/incomplete eligibility or effects review stays visible. Imported catalog
  coverage does not imply that every item can be scored by the combat model.
- Prices are cache-only. Static hints remain labeled estimates; missing quotes stay null.
- Account selection matches the existing dashboard's first-player policy. No new account
  selector, authentication scheme, or public deployment boundary was introduced.
- The preview build remains local/generated. Production packaging and `/gear` cutover
  remain later milestones.

## Milestone 3 remains unstarted

The next milestone is real single-style optimization: expose the existing service,
implement the shared exact baseline-evaluation foundation, execute solves outside the
event loop, guard publication against changed account fingerprints, support cancellation,
and render real metrics, diagnostics and comparable current-equipment results.

Manual trials, exclusions, joint multi-style integration and production cutover remain
in their separately scoped later milestones. This delivery stops at Milestone 2.
