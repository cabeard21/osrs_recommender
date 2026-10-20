# Gear performance and equipment presentation — 2026-10-19

The reported 33.62-second full Gear-page calculation was dominated by repeated
serialization of one immutable account snapshot. This pass retains the accepted
physical-variant and melee breakpoint beam fixes, and changes no combat formula,
candidate limits, search ranking, node budget, eligibility gate or MCP response.

## Frozen comparison

The existing correctness investigation's isolated `refreshed.sqlite` was opened
through SQLite `mode=ro`. No production database, scheduler, refresh, or network
price lookup participated. Both versions used the same cached price rows, catalog,
request and evaluation time (`2026-10-19T22:58:27.649697+00:00`). See
[the correctness report](GEAR_OPTIMIZER_CORRECTNESS.md) for account/request provenance.

Each service measurement used a newly constructed snapshot and three repetitions.
The original UI cancellation pattern deliberately remained in the benchmark on both
sides, isolating the fingerprint cache improvement. The final UI also captures its
starting fingerprint once, so its worker callback no longer accesses the snapshot.

| Stage | Before | After |
| --- | ---: | ---: |
| Snapshot construction, including database reads | 0.0480 s | 0.0443 s |
| Cached price-row read | 0.0024 s | 0.0019 s |
| Fingerprint access work, including first serialization | 29.6603 s | 0.0048 s |
| Candidate facts and candidate pools | 0.2643 s | 0.2599 s |
| Search and response, excluding fingerprint/candidate work | 0.4892 s | 0.3424 s |
| Complete service optimization | **30.4119 s** | **0.6064 s** |
| Warm NiceGUI result construction, original/final presentation | 0.0388 s | 0.0407 s |

These are per-stage medians, so columns need not sum exactly. Fingerprint time
includes the initial access outside the optimization timer. The search timer
subtracts only accesses inside optimization. Candidate generation includes all
5,435 factual item evaluations and pool construction, including marginal combat
evaluations. Search includes loadout enumeration, validation, curve construction,
alternatives and response assembly. NiceGUI construction excludes WebSocket
delivery, browser rendering, initial controls and image loading.

The first baseline triplicate was 29.6945–30.0583 seconds (median 29.8818); a repeat
with corrected disjoint timers was 29.3576–31.0034 seconds (median above). Final
service runs were 0.5767, 0.6064 and 0.6701 seconds, approximately **50× faster**.
Small candidate/search timing differences are runtime noise and reduced allocation
pressure; their algorithms are unchanged. Catalog loading was about 0.065 seconds.

The original callback made 15,207 fingerprint accesses per request. Previously each
sorted/serialized all account facts. The immutable snapshot now lazily stores its
identity once. Subsequent accesses return that scalar. Newly read snapshots and
`dataclasses.replace`/hypothetical snapshots start with empty caches. All original
hash inputs and exact JSON hashing bytes are retained. The UI still reads the
account again after the worker completes and refuses publication if its identity or
the page's request generation changed. Cancellation remains checked during search.

Every before/after repeat equals the complete accepted result, not merely its DPS:

- Snapshot: `961a4cca3db25372d4ab5ea7d9c03922f11caeed4bd833da048d9763f147b145`.
- Canonical response SHA-256:
  `6dbc1e103080d23c67717c5b6fb6daed835a9a97a2c85e0da1c5aaee2a921ee6`.
- DPS **3.0363738994067186**, max hit **15**, melee strength **+75**, raw ranged
  strength **+10**, additional purchase cost **0 GP**, **15,076** explored nodes.

## Browser measurement and acceptance

A temporary loopback-only NiceGUI server used the same read-only frozen database
and clock. The original page measured **29.7412 seconds** from optimize click to
visible results; the final page measured **1.1036 seconds**, approximately **27×
faster**. Another final run measured 1.0818 seconds. These are individual Chromium
journeys, not a statistical latency claim or Pi/mobile-device benchmark.

Cold server-side result construction was 0.2693 seconds originally and 0.1146
seconds finally. Initial page readiness was 2.3667 versus 2.2504 seconds, measured
separately from optimization. Final browser response equaled the accepted frozen
result. There were no JavaScript page errors; all selected equipment had local
sprites. Desktop screenshots and the 390-pixel mobile layout were visually
inspected. The mobile chart was checked after its asynchronous responsive resize,
including its SVG bounds, rather than relying solely on document scroll width.

Automated browser journeys cover:

- Future assumptions remaining request-local, correctly labeled eligibility,
  and selection of a validated alternative with role-lock reoptimization.
- Repeated melee/magic transitions, all eleven equipment slots for each role,
  visible inventory requirements, and collapsed diagnostics.
- Actual pointer clicks on the curve, synchronized action picker and selected
  equipment summary, selection through the picker, and mobile chart bounds.
- Editing inputs clearing results and an account identity change during an
  in-flight worker causing rejection rather than stale publication.

Final focused verification: **171 tests passed**, including three Chromium browser
journeys, with **94% combined Gear/snapshot/UI coverage** (snapshot and presentation
modules 100%). The selection includes the accepted variant, bonus, combat,
beam-breakpoint, transition, ownership, service and MCP regressions. Ruff lint and
format checks, mypy over the changed runtime modules and benchmark, and
`git diff --check` passed. Independent review found no unresolved blockers.

## Presentation

The visual/interaction references were
[OSRS Best in Slot](https://www.osrsbestinslot.com/best-in-slot-gear/) and its
[gear picker](https://www.osrsbestinslot.com/gear-picker/). No implementation was copied.

- Familiar head/cape/neck/ammunition/weapon/body/shield/legs/hands/feet/ring layout,
  with keyboard-accessible slot buttons and item inspection beside the layout.
- 231 local numeric-ID item sprites, about 159 KB total, packaged with the app.
  [Source and attribution](../tracker/ui/assets/items/source.json) identify RuneLite's
  public icon cache and Jagex artwork. Other items retain exact names and a fallback.
- Selected equipment and primary DPS, max hit, accuracy, interval, purchase and
  inventory figures precede secondary details. Distinct signed strength labels
  remain visible. Raw bonuses, assumptions and search diagnostics are expandable.
- The multi-style efficiency curve follows the primary metrics, ahead of the
  equipment layouts. Point clicks and an accessible picker update the exact same
  solution, metrics and inventory plan. Single-style equipment appears before its
  flat curve. The existing 95% best-found suggestion is retained unchanged.
- Alternatives show validated DPS differences, whole-setup purchases and dated
  ownership/requirement evidence. They appear only for the selected single-role
  surrounding setup described by the service. A choice sets the named role's slot
  lock and reruns the full validation. Global locks, ownership access modes,
  budgets, supply reservations and role controls remain available.
- Inventory requirements use item names. Transition instructions show exact equip
  and unequip actions, automatically displaced equipment and occupancy after each
  action. Purchase uncertainty is explicit.

## Reproduction and local artifacts

```powershell
.venv\Scripts\python.exe -m tools.benchmark_gear `
  --database .tmp/gear-correctness/refreshed.sqlite `
  --request .tmp/gear-correctness/request.json `
  --at 2026-10-19T22:58:27.649697+00:00 `
  --repeats 3 --output .tmp/gear-performance/after.json
```

Private request/database/full-response artifacts remain ignored in `.tmp/`.
The benchmark uses only read-only input connections and never refreshes facts.
Before data, saved original source, full-page harness and final screenshots are in
`.tmp/gear-performance/` (`before.json`, `before-final.json`, `after.json`,
`browser-before.json`, `browser-after-final.json`, and `browser-after-responsive*`).

Remaining limits: search is still bounded `best_found`, and the previously
documented unsupported combat mechanics and unreviewed equipment remain excluded.
Multi-role slot substitution DPS is not provided by the service; the UI directs
those comparisons through role locks instead of fabricating deltas. Full-page
latency was verified locally in headless Chromium, not on the Pi, a physical phone,
or a deployed MCP tunnel. No commit, push or deployment was performed.
