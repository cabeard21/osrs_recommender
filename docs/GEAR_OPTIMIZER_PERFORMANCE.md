# Gear performance and equipment presentation — 2026-10-19

The [desktop performance analysis and work tracker](GEAR_OPTIMIZER_DESKTOP_PERFORMANCE_PLAN.md)
records the November 8, 2026 architectural assessment, profiling evidence, and
proposed follow-up experiments. The entries below retain historical measurements.

## November 12, 2026: automatic ranged resource-cost frontiers

Ranged now runs the same separate DPS-versus-GP/damage exploration as Magic,
including full weapon, ammunition, cape and permitted combat-option changes.
This adds real search work to fixed-ranged and ranged-only Auto requests. Auto
already permitting Magic previously ran cost exploration in its ranged branch,
so enabling the shared graph alone is not a new search stage in that case.

The implementation keeps the existing 500,000 Fast / 1,500,000 Thorough frontier
expansion limits. Cost preparation now covers compatible supported weapon and
ammunition contexts rather than only the first eight baseline scaffolds. This
can increase preparation work even in requests that already ran cost exploration.
The expanded consumable budget policy and reviewed body-interference rules can
intentionally change feasible or numerically comparable setups; timings therefore
measure the complete behavior change rather than promising byte-identical output.

The comparison below uses archived baseline commit
`0fd073d5cae87e111cb5adbbeed0c80e0ca1d54e` and the changed local sources on Windows.
It uses an explicit 20-item subset of the bundled frozen
`gear_search_quality_account.json` fixture, retaining its account facts, clock and
cached prices. Each request uses a two-action cap and 100% allowed DPS loss.
Measurements are serial direct-optimizer calls, with one warmup followed by three
measured runs and median wall time. This is a small substitute fixture, not the
operator account, full catalog, HTTP, worker-pool or live deployment acceptance.
The two revisions were measured sequentially after development test jobs finished.
No latency threshold or search-budget reduction is inferred from these observations.

| Frozen case | Fast before | Fast after | Change | Thorough before | Thorough after | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed ranged, DPS only | 0.1166 s | 0.3289 s | +182.0% | 0.1360 s | 0.4646 s | +241.5% |
| Fixed ranged, balanced defence | 0.2503 s | 0.4567 s | +82.4% | 0.2995 s | 0.6350 s | +112.0% |
| Fixed ranged, prayer bonus | 0.2325 s | 0.4576 s | +96.8% | 0.2729 s | 0.5989 s | +119.4% |
| Auto, ranged only | 0.1366 s | 0.5429 s | +297.3% | 0.1559 s | 0.6477 s | +315.4% |
| Auto, ranged and Magic | 1.0901 s | 0.9244 s | -15.2% | 1.0940 s | 1.0954 s | +0.1% |
| Ranged, optimized ranging potion | 0.2469 s | 0.7138 s | +189.1% | 0.2981 s | 1.0041 s | +236.8% |
| Mixed Multi, ranged and melee | 2.1733 s | 2.6551 s | +22.2% | 2.2046 s | 3.4043 s | +54.4% |

After-change cost-stage details below are median **sums across executed branches**
for each serial request. P/E/U means preparation, exploration and publication in
seconds. These are stage measurements, not a second end-to-end benchmark.

| Frozen case | Fast cost total | Fast P/E/U | Thorough cost total | Thorough P/E/U | Cost branches |
| --- | ---: | --- | ---: | --- | ---: |
| Fixed ranged, DPS only | 0.2109 s | 0.0005 / 0.2099 / 0.0006 | 0.3240 s | 0.0005 / 0.3229 / 0.0005 | 1 |
| Fixed ranged, balanced defence | 0.2218 s | 0.0005 / 0.2207 / 0.0006 | 0.3227 s | 0.0005 / 0.3216 / 0.0006 | 1 |
| Fixed ranged, prayer bonus | 0.2117 s | 0.0005 / 0.2106 / 0.0006 | 0.3085 s | 0.0006 / 0.3073 / 0.0006 | 1 |
| Auto, ranged only | 0.3887 s | 0.0005 / 0.3872 / 0.0009 | 0.4831 s | 0.0005 / 0.4817 / 0.0009 | 1 |
| Auto, ranged and Magic | 0.6767 s | 0.0006 / 0.6752 / 0.0009 | 0.7880 s | 0.0007 / 0.7864 / 0.0009 | 2 |
| Ranged, optimized ranging potion | 0.4705 s | 0.0010 / 0.4683 / 0.0011 | 0.7138 s | 0.0010 / 0.7117 / 0.0011 | 2 |
| Mixed Multi, ranged and melee | 0.4605 s | 0.0007 / 0.4592 / 0.0007 | 1.1878 s | 0.0006 / 1.1865 / 0.0007 | 1 |

No measured cost branch exhausted its expansion budget.
The potion case executes no-potion and ranging-potion profiles. Auto allows only
the disciplines named in the table. All measured requests returned a feasible
selected setup; selected DPS remained unchanged in these restricted fixture cases.

The filtered physical IDs are `841, 857, 861, 882, 888, 892, 1059, 1061, 1127, 1129, 1135, 1323, 1333, 1381, 1387, 1704, 1725, 1727, 10499, 21326`.
Fixture SHA-256: `402bbed7834ffe0f4e069f253f24d999f691b41ec7846879a9aa10db7460a46d`.
Raw per-run timings/search diagnostics and the request-defining harness are retained locally
under ignored `.tmp/ranged-cost-benchmark/` (`before-clean.json`, `after-clean.json`,
`run.py`); the baseline source archive is retained there too. The earlier
`before.json` is an exploratory contended run and is not used in these tables.

For this small fixture, adding ranged cost exploration materially increases
DPS-only latency while preserving the existing work budgets. The already-costed
ranged/Magic Auto case changes little or improves because cost-scaffold candidate
scoring now avoids unrelated weapon/ammunition contexts. These observations do not
establish a speedup on larger catalogs or predict current-account latency.

## November 2, 2026: repeated search and frontier work

Single-role optimization now reuses its individual equipment beam for common
equipment and skips action-cap tuple searches: there are no role transitions,
and every feasible finalist applies to every cap. Secondary and running-cost
frontier searches also enumerate Single equipment once. Multi-role searches
retain their separate cap-specific beams.

Frontier diversity selection evaluates each candidate's ranking once and reuses
it for sorting, DPS bands and secondary ordering. Combat-option variants use
small request-local cache overlays instead of copying the entire performance
and option caches; writes remain isolated from other variants and the base search.
Combat formulas, eligibility and final exact validation are unchanged. Node
diagnostics count actual expansions, so Single counts decrease. Removing duplicate
work can leave more of a bounded search's existing budget available.

The following direct-service measurements use Python 3.12.10 on Windows, the
bundled redacted `gear_search_quality_account.json` fixture, its frozen clock and
prices, and the pre-change versus changed optimizer/frontier sources. Each cell
is the median of three calls, with the two versions measured sequentially and
without concurrent tests or profiling. There is no separate warmup; these are
local fixture measurements, not live account, HTTP or Pi acceptance.

| Frozen case | Before | After | Reduction in time |
| --- | ---: | ---: | ---: |
| Owned Slash | 0.5555 s | 0.4564 s | 17.8% |
| Owned Slash, automatic melee options and accuracy frontier | 4.6938 s | 3.5640 s | 24.1% |
| Owned Magic | 3.1554 s | 1.2384 s | 60.8% |
| Joint melee/Ranged, four-action cap | 3.1249 s | 3.0579 s | 2.1% |

Cases come from `tools.benchmark_gear_search_quality.benchmark_case`. The automatic
melee case uses stab/slash/crush, accurate/aggressive/controlled/defensive, and no
spells. All four complete responses match except `explored_nodes` diagnostics;
the small joint timing difference should be treated as noise. Owned Slash's
primary expansion count falls from 18,678 to 8,699. Selected equipment, combat
options, DPS, purchases, transitions, curves and frontier points remain equal.

Focused verification: 236 optimizer and real API tests passed with 95.12% coverage
across `optimizer.py` and `frontier.py`. Regression cases cover Single expansion
counts and cap invariance, stable rank ties and duplicate equality, cache lookup
without enumeration, multi-role option preservation and base-cache isolation.
Ruff lint/format, mypy and independent code review also passed.

## November 2, 2026: incremental combat scoring

The next pass adds immutable prepared equipment in `tracker/gear/scoring.py`.
A request-local prefix cache retains at most 8,192 equipment aggregates. Child
states add integer bonuses to the parent's totals and track weapon/ammunition
metadata directly. Fractional magic damage still uses Python's original ordered
`sum` over item terms, preserving floating-point and max-hit breakpoints. The
ranged ammunition correction is a lazy view, so melee/magic do not build it.

The full evaluator and incremental path share the same legality checks and
combat formulas. Physical slot validation precedes incremental preparation.
Automatic attacks reuse filtered, configured options per role and weapon within
the frozen request; each physical loadout is prepared once across its options.
Frontier combat variants reuse the same scoring and option preparation while
retaining isolated performance/option overrides. Nothing is cached across
account snapshots or optimization requests.

The comparison below starts from the completed repeated-work improvements above,
not the earlier October implementation. It uses Python 3.12.10 on Windows and the
same bundled frozen fixture, with medians of three direct optimizer calls per
case. Versions were measured sequentially without concurrent tests or profiling;
there is no separate warmup. These are local compute measurements, not Pi/API
latency or real-account acceptance.

| Frozen case | Before incremental scoring | After | Change in time |
| --- | ---: | ---: | ---: |
| Owned Slash | 0.4564 s | 0.4282 s | 6.2% less |
| Automatic melee options, accuracy frontier | 3.4790 s | 1.8504 s | 46.8% less |
| Owned Magic | 1.1851 s | 1.1519 s | 2.8% less |
| Joint melee/Ranged, four-action cap | 3.0849 s | 2.9496 s | 4.4% less |
| Auto melee/Ranged/Magic | 13.2928 s | 4.5540 s | 65.7% less |
| Owned Slash, Thorough | 0.9823 s | 1.0314 s | 5.0% more |

The strongest measured gains are in option-heavy searches: approximately 1.9x
for the accuracy frontier and 2.9x for Auto. Fixed-attack changes are small and
this three-sample comparison does not establish a Thorough improvement. Auto
allows all attack categories, accurate/aggressive/controlled/defensive/rapid,
and Fire Bolt; the accuracy case uses the same filters with no spells. Thorough
uses the existing bounded local refinement. Complete responses for all six
cases match, including node counts, gear, options, purchases, transitions and
frontiers; only observational `duration_seconds` fields are excluded.

Independent review also matched 2,000 randomized cases against the saved original
combat evaluator. Regression coverage includes exact fractional sums and input
order, append/replace/remove, ammo exclusions, invalid physical slots, unsupported
effects/targets, damage caps, Ancient/Iban/powered attacks, request-local cache
bounds, distinct role filters/targets, and preparation reuse across options.
Final focused verification: 376 tests passed with 95.81% coverage across combat,
optimizer, frontier and scoring modules (scoring itself 100%). Ruff lint/format,
mypy, diff checks and independent review passed.

## November 2, 2026: Auto process-parallelism investigation

This section records the local research prototype preceding the desktop integration
described below; these measurements are not serving-process acceptance.
Single Auto currently searches melee, Ranged and Magic sequentially in
`tracker/gear/auto.py`. Those independent alternatives can run concurrently.
Joint multi-role optimization remains coupled by shared purchases, carried gear,
inventory and transitions; independent per-role searches would change its meaning.

An ignored prototype at `.tmp/gear-parallel/benchmark.py` compares the same
three-discipline frozen request used above, using explicit detached payloads and
the existing pure optimizer. Every branch retains `_complete_frontiers=True`
and `_running_frontier=True` because the original Auto request includes Magic.
Complete branch responses are returned to the parent and merged by the actual
Auto merger in canonical melee/Ranged/Magic order. Full output matches ordinary
serial Auto; elapsed-time diagnostics are excluded from equality checks.

Measurements use Windows CPython 3.12.10 on a 12-logical-CPU host. Each warm cell
is a median of three requests. Thread/process pools remain alive across requests;
the first request includes lazy worker startup/imports. Process pools explicitly
use `spawn`, and all strategies use the same process-visible cancellation event.
Payload reconstruction, IPC result return and Auto merging are timed. The frozen
serialized payload plus three requests is 91,292 bytes. No database, network
price refresh, serving API or Pi participates.

| Execution | Warm median | First request with new pool |
| --- | ---: | ---: |
| Serial branches | 4.7811 s | Not measured separately |
| Three threads | 6.2145 s | 6.2178 s |
| Two worker processes | 3.4325 s | 3.5631 s |
| Three worker processes | 2.0829 s | 2.7366 s |

Three processes achieve about 2.3x versus serial in this fixture. The serial
branch imbalance alone limits ideal speedup to roughly 2.5x, before overhead.
Thread timings varied from 5.94 to 7.39 seconds and did not improve CPU throughput.
Python's process pool bypasses the GIL, while requiring serializable inputs:
[official Python 3.12 documentation](https://docs.python.org/3.12/library/concurrent.futures.html#processpoolexecutor).

Sampled child resident memory is approximately 100 MiB per worker. Summed
per-worker lifetime peak working sets were 203.3 MiB for two workers and 306.6
MiB for three, in addition to the parent. These sums are not simultaneous
whole-service peaks, and the small fixture does not establish full-catalog RAM
needs. A separate warmed three-process cancellation probe signaled after 0.2s;
all three branches raised `optimization_cancelled` and drained in 0.0315s.
The pool accepted a subsequent lightweight task. This does not measure browser
disconnect latency, API lock release or cancellation recovery under worker death.

Recommended implementation boundaries:

- Use an optional app-owned warm pool with configurable capacity up to three,
  explicit `spawn`, startup/shutdown ownership and broken-worker recovery.
- Keep `GearService` and its busy lock in the parent. Children invoke the pure
  optimizer and receive frozen account/request/prices/time; they do not access
  the database, scheduler or price refresh clients.
- Snapshot, request and catalog objects cannot be submitted directly because
  their `MappingProxyType` fields are not picklable. Reuse the existing
  `AccountFacts.from_snapshot()/snapshot()` transport and request model dumps;
  load or reconstruct a catalog/content revision matching the parent's context.
- Merge in the original discipline order, preserve all Auto flags and exact
  result semantics, and retain fresh-snapshot acceptance checks in the API.
- Give each request its own process-visible cancellation state. Cancel pending
  jobs and drain active branches before releasing the service lock or reusing
  worker state. Cancelling a running future alone cannot stop the calculation.
- Leave joint multi-role search intact. Account for separate web/MCP services:
  creating an independent three-worker pool in both can double child RAM.
- Before selecting Pi defaults, measure the full catalog through the actual API,
  including total parent/child/container memory, responsiveness, disconnects,
  pool failures and serial fallback. No Pi latency or memory claim follows from
  these Windows prototype results.

## November 2, 2026: desktop integration

Desktop Gear now defaults to native execution and a persistent six-process pool.
Native release binaries are required; explicit Python selection and baseline/lazy
profiles provide rollback. See [deployment](DEPLOYMENT.md) for provisioning. Its lifespan
warms every child with the same content/catalog context and closes the pool on
shutdown. `optimization_workers` accepts integers from one (serial) through six; the existing
launcher and private desktop config remain the entry point. Normal app/MCP
services retain their default serial execution. Pi optimizer performance is not
a gate for this desktop feature; the Pi continues supplying authoritative facts.

Independent Single/Multi Auto assignments and potion branches use the pool. The
existing Auto merger consumes complete branch results in canonical discipline
order, preserves the running/secondary frontier flags, and refuses partial or
duplicate result sets. Fixed-discipline and joint multi-role searches retain
their existing paths. Account facts, explicit assumptions, quoted prices and
the evaluation clock are frozen per request. Worker contexts are content-hashed;
authored requirement expressions, community metadata and verified catalogs are
preserved by the detached transport. Browser-only fields stay in the parent.

The parent retains the service busy guard until all work drains. Cancellation
uses a process-visible byte flag without per-node semaphore locking. After a
five-second cooperative grace, cleanup terminates/kills only the pool's own
children and checks their exit. A broken pool rebuilds for a fresh request;
the failed calculation is never silently recomputed. A child or executor
management thread that cannot be stopped poisons the pool and prevents reuse.
In Python mode startup failures fall back to serial only after cleanup; required
native startup failures stop startup. Running-worker and
context failures return sanitized retryable HTTP 503 responses. The API's fresh
snapshot acceptance check remains in the parent.

Validation includes actual Windows spawn, full authored-catalog transport,
serial/parallel Fast and Thorough API response parity, cancellation/reuse,
real worker crashes, forced cleanup of an unresponsive child, and surviving
child/manager guards. The 368-case focused regression selection exposed four
stale replay fixtures that omitted the existing running-price/time context;
restoring that context preserved their exact tie-key assertions and all four
replays passed. The selection's coverage gate reached 90.25%; the final process
and payload suite separately passed 20 tests with 89.75% combined coverage
(87% pool, 100% payload). Ruff lint/format, mypy and independent review passed.

The actual desktop HTTP path was then measured on unique loopback ports using
the full 5,435-item catalog, an isolated public level-99 account, deterministic
quotes and a 5,000,000 GP budget. Account/prices came from frozen synthetic
facts, not the Pi or operator database. Both serial and parallel servers used
the real desktop lifespan, API, service guard and result serialization. Each
cell is one measured request with concurrent health/context probes, not a
statistical latency estimate or real-account acceptance.

| Desktop HTTP execution | Auto Fast | Auto Thorough |
| --- | ---: | ---: |
| Serial, one worker setting | 8.518 s | 11.249 s |
| Three worker processes | 3.249 s | 4.232 s |

Complete HTTP responses matched except observational `duration_seconds` fields.
These samples are approximately 2.6x faster with processes. Initial app readiness
took 1.260s serial versus 4.352s with all workers warmed. Maximum sampled summed
parent/child resident memory was 216 MiB serial versus 732 MiB parallel; sampling
does not establish an exact allocation peak. All concurrent health/context probes
returned 200. Context-probe medians during the process-backed requests were about
4ms, compared with 253–316ms during serial requests.

Real HTTP disconnect probes first established an overlapping `optimizer_busy`
503, then measured reuse of the same service guard through a valid exact-loadout
evaluation: 0.352s after disconnect serial and 0.322s parallel. The parallel probe
observed six busy responses before the successful valid evaluation; invalid
responses did not count as guard release. Both test servers shut down normally,
and all observed parent/worker PIDs exited. Ignored local evidence lives under
`.tmp/gear-pool/desktop-http/`; no production process was restarted.

## October 19, 2026 investigation

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
