# Desktop gear optimizer: performance analysis and work tracker

**Analysis date:** 2026-11-08  
**Assessed revision:** `3fad336`  
**Status:** Original P1 complete and enabled in the desktop `combined` profile. Prepared melee/ranged/magic constants, lazy configured/fixed Single and Multi scoring, lazy frontier combat variants, compact running-cost ranking, and ranged score finalization are implemented. Full parity, timing, memory, worker, cancellation/recovery and automated live desktop/rollback acceptance passed on 2026-11-09. The bounded closeout proposal is superseded; no original P1 scope is deferred. See [final acceptance](#final-p1-acceptance-revision-2026-11-09). P2-P6 remain separate future work.
**Scope:** Desktop optimization, including Single, Multi, Auto disciplines,
potion selection, secondary frontiers, and running-cost frontiers.

This document records the original performance analysis and subsequent authorized
implementation. Historical proposals and failed experiments remain below; current
completion and acceptance are stated separately.
Pi execution is outside this plan. Existing performance history is recorded in
[GEAR_OPTIMIZER_PERFORMANCE.md](GEAR_OPTIMIZER_PERFORMANCE.md). The older
[GEAR_OPTIMIZER_REDESIGN_PLAN.md](GEAR_OPTIMIZER_REDESIGN_PLAN.md) concerns the
Gear interface redesign and is a separate assessment.

## Recommendation

Separate search policy, numerical evaluation, and public result construction.
Use compact immutable equipment states and independently reusable calculations
for damage, defensive rolls, and resource consumption. Let objective-specific
searches share those calculations while retaining their own option winners,
beam retention, and work budgets.

Then prototype a specialized Single-mode numerical solver and a batched native
execution core. Compact representations provide a foundation for both better
search algorithms and effective use of desktop cores.

At the original assessed revision, no end-to-end speedup from these proposals
had been measured. Later sections record measured improvements and adoption.
The original analysis below is historical. The repeated-signature counts below are not
a validated cache design or an application speedup prediction.

## Current architecture and cost drivers

Relevant implementation entry points at the assessed revision:

| Responsibility | Source |
| --- | --- |
| Candidate pools, beams, evaluation cache, full solutions | [`optimizer.py`](../tracker/gear/optimizer.py) |
| Lightweight and full ordinary combat evaluation | [`combat.py`](../tracker/gear/combat.py) |
| Equipment-prefix aggregation | [`scoring.py`](../tracker/gear/scoring.py) |
| Secondary exploration, diversity, combat variants | [`frontier.py`](../tracker/gear/frontier.py) |
| Resource-cost frontier and cost-specific ranking | [`running_frontier.py`](../tracker/gear/running_frontier.py) |
| Resource calculations and descriptions | [`running_costs.py`](../tracker/gear/running_costs.py) |
| Discipline and potion orchestration | [`auto.py`](../tracker/gear/auto.py), [`potion_search.py`](../tracker/gear/potion_search.py) |
| Warm desktop workers and dispatch | [`parallel.py`](../tracker/gear/parallel.py), [`service.py`](../tracker/gear/service.py) |
| Desktop worker configuration | [`gear_desktop.py`](../tracker/gear_desktop.py) |

Runtime grows with discipline/potion branches, explored equipment states, attack
and prayer variants, objective passes, and the overhead of evaluating each
candidate. Frontier exploration adds metric-first and diverse searches, combat
variants, and finalist refinement beyond the main DPS search.

Several useful optimizations already exist: multiprocessing, shared eligibility
preparation across potion branches, incremental equipment aggregates, equivalent
attack/prayer reduction, Single action-cap reuse, rank-once diversity selection,
incremental Pareto insertion, and selected forms of metric-lane reuse. Generic
recommendations to add caching or multiprocessing should account for this work.

Current searches are bounded and return best-found results. Candidate truncation,
beam widths, and frontier work budgets do not establish global optimality.

## Measurements collected during this analysis

### Provenance and limits

The benchmark used the bundled `melee_1m` account/catalog fixture as an explicit
substitute, with the scenario loaded from the local `temp.txt` result dump:

- 119 catalog items; fixture snapshot
  `0a007dd90defdaac5ef67190fd4bbdcb4d03b4d5ee306990fb8015920409ebae`.
- Frozen fixture time: `2026-10-28T02:14:30.010365+00:00`.
- Single ranged discipline; fixed `divine_ranging` potion.
- Fast mode, automatic combat options and prayer selection, balanced-defence
  secondary priority, 1,000,000 GP budget, and 100% allowed DPS loss.
- Complete frontiers requested and running-cost frontier explicitly forced.
- Direct serial optimizer execution on Windows using the repository virtualenv.

This is not an exact replay of the original account or a full-catalog desktop
service benchmark. In particular, forcing the running-cost frontier means the
measurement does not describe every fixed-ranged request's default behavior.
Each timing below is one exploratory run, not a repeated median or percentile.

### Unprofiled phase timings

| Phase | Seconds |
| --- | ---: |
| Candidate ranking | 0.569 |
| Main gear search | 3.275 |
| Secondary frontier | 13.856 |
| Running-cost frontier, including preparation/publication | about 16.37 |
| Other work | about 0.04 |
| Total wall time | **34.112** |

Combined frontier work took 30.237 seconds, approximately 89% of total runtime.
Within those frontiers, combat-variant phases took about 8.22 and 8.79 seconds.

### Function profile

The cProfile run took 64.352 seconds and recorded 103,158,798 calls, including:

| Work | Count | Cumulative profiled seconds |
| --- | ---: | ---: |
| Lightweight combat scoring | 849,240 | 17.758 |
| Full combat evaluation | 118,746 | 7.319 |
| JSON serialization | 257,385 | 6.749 |
| Solution construction | 50,870 | 12.168 |
| Running-cost evaluation | 135,355 | 3.172 |

Cumulative timings overlap and must not be summed. Profiling materially changes
execution time. These figures identify work to investigate; they are not normal
desktop latencies or additive savings estimates. Moving only the damage formula
would leave candidate expansion, validation, ranking, and object construction.

### Scoring-dependency cardinality experiment

A counting wrapper observed inputs without substituting or caching results:

| Signature | Distinct inputs |
| --- | ---: |
| Equipment IDs in preparation order plus combat-option context | 746,016 |
| Full bonus vector plus physical dependencies and option context | 695,772 |
| Ranged outgoing-damage inputs plus physical dependencies and option context | **106,080** |
| Total scoring calls | **849,240** |

The reduced outgoing signature retained weapon/ammunition IDs, ranged accuracy
and strength totals, occupied slots, unsupported effects, style, stance, spell,
powered attack, active prayers, and the defence-inclusion flag. Target and levels
were fixed for this single scenario. Defence inclusion was false for the observed
lightweight calls. Candidate-specific bonuses and reporting were not replaced.

Approximately 87.5% of calls repeated this reduced signature. This supports
investigating calculation-specific dependencies rather than whole-loadout caches.
It does not prove general equivalence, useful bounded-cache hit rates, or net
runtime savings after key construction and memory costs.

The unprofiled, cProfile, and final counting runs had the same solution digest:

```text
b3568a9b8a923fb6ad3d8481f62d7a49ed09b56354ba85a23d1db448f71a73de
```

This digest covers selected solution, unrestricted solution, curve, secondary
frontiers, and running-cost frontiers through the existing profiling helper.
Matching digests validate that observation did not change those outputs in this
fixture; they do not validate a proposed replacement evaluator.

### Local artifacts and reproduction

Analysis artifacts are ignored local files under `.tmp/optimizer-deep-dive/`:
`ranged-timing/report.json`, `ranged-profile/report.json`,
`ranged-profile/calls.txt`, `ranged-profile/calls.prof`, `reuse-probe.json`, and
`probe_reuse.py`. They are not required tracked dependencies of this document.
Their essential measurements and limitations are retained above.

From the repository root, with the original local dump available:

```powershell
.\.venv\Scripts\python.exe -m tools.profile_gear_frontiers --dump temp.txt --fixture melee_1m --discipline ranged --potion divine_ranging --output .tmp/optimizer-deep-dive/ranged-timing
.\.venv\Scripts\python.exe -m tools.profile_gear_frontiers --dump temp.txt --fixture melee_1m --discipline ranged --potion divine_ranging --output .tmp/optimizer-deep-dive/ranged-profile --cprofile
```

The dump is untracked and does not contain complete original account facts.
Exact future reproduction needs a frozen scenario plus snapshot/catalog/prices
or a reviewed, redacted fixture. Do not commit private account dumps merely to
make these commands portable. The one-off cardinality probe also remains local;
a reusable version is a tracked follow-up below.

## Proposed work

### Current increment: full P3 (2026-11-10)

The authorized next increment refreshes profiling against the P1-enabled revision
including Multi Auto, then implements all P3 equipment and solution representations.
Broader P2 sharing and P4-P6 remain separate. Full P3 implementation, qualification
and desktop adoption are complete. The final revision-9 acceptance and adoption
record below supersedes the intermediate statuses in this development history.

The reference is `combined` with P1 enabled and compact states disabled. The
candidate differs only by a private compact-state execution switch. Fixed slot
records must retain equipment insertion order separately for exact fractional
magic sums. Solution interning remains bounded within a concrete execution leaf;
independent objective winners, physical identities, search order and budgets stay
unchanged. Complete normalized result parity is mandatory.

Preselected timing configurations are fixed melee Single (one worker), fixed magic
Single (one), configured ranged Single (one), fixed-style Multi (one), configured
Auto (three), and Multi Auto (three). Fixed-style Multi is the primary intended
improvement. Memory qualification covers magic, Multi and Multi Auto separately.
Apply the staged validation standard below, including its predeclared extension
from three to five timing pairs when variability is inconclusive. Historical P1
acceptance policy and evidence retain their original meaning.

Initial P3 diagnostic profiling of the P1 reference found roughly 1.08 million
purchase-cost calls in the configured Multi case, with 14.05 seconds cumulative
instrumented time (including 12.57 seconds in purchase-report construction).
The full profile recorded 171.9 million calls and 79.3 seconds instrumented time.
These are hotspot observations, not uninstrumented runtime or adoption evidence.
The profiles live under `.tmp/p3/reference-profile`; implementation files were
being edited during development, so final qualification requires a fresh frozen
source cohort. Numeric acquisition facts must preserve market-alias deduplication
and the existing sorted-physical-ID overwrite rule, as well as ownership,
assumptions, untradeables, exemptions and unknown-price behavior.

The first isolated fixed-Multi service screen retained complete result parity but
regressed from 22.975 to 31.180 seconds; it is not accepted. Matched diagnostic
profiles identified repeated assignment construction as the principal offset to
numeric acquisition savings. Subsequent work batches joint state construction.
A full-catalog constructor probe observed 190,059 reusable equipment constructions
out of 329,977 with 1,024 entries, versus 200,869 with 8,192 entries. The equipment
pool therefore uses 1,024 entries; at this stage complete-solution interning
retained its 8,192 bound (revised after memory qualification below). Assignment
constructor reuse was only 16.9% even at 8,192 entries, so that
additional pool is not introduced. These counts motivate implementation choices;
they do not prove a runtime or memory gain. Screen and probe evidence is retained
under `.tmp/p3-screen`.

The fourth isolated screen, after delayed assignment allocation and inventory
fast paths, measured 22.611 seconds reference and 22.591 seconds candidate with
identical complete result digests. This is effectively equal performance, not a
qualified gain. These diagnostic screens explicitly fixed combat options and
disabled prayers. The declared `multi` acceptance case fixes the role disciplines
but retains configured combat options; the screens are substitute workloads and
cannot establish that acceptance case's performance. The stable candidate passed
816 focused tests with 94% combined
coverage across the new state, solution, acquisition and acceptance-tool modules;
the production modules individually covered 99%, 98% and 100%. An additional
24 boundary tests covered workers, HTTP, cancellation/recovery, rollback and
automated Chrome. Ruff and focused mypy passed. Independent review found no
remaining correctness or original-P3 implementation-scope blockers.

Acceptance revision 1 under `.tmp/p3/acceptance-v1` passed all 21 full parity
configurations (42 complete outputs), then failed the first timing configuration.
Fixed melee used the predeclared extension to five pairs: median 6.925103 seconds
reference versus 7.290294 seconds candidate, a 5.27% regression with unresolved
tolerance uncertainty. All 12 warm-up/timed outputs matched exactly. Remaining
timing configurations and memory qualification were not run. This revision is
unqualified; its source snapshot and all observations remain unchanged.

Further revisions may reuse that explicitly identified frozen reference-output
cohort as a correctness oracle, with verified raw-output, source, normalizer and
per-case input hashes. Every one of the 21 candidate cases must still execute
again and match its complete reference output. Timing and memory cannot reuse
old measurements: both modes must run afresh, and their outputs must also match
the oracle. A changed input, case definition or normalization contract requires
new reviewed reference evidence. This preserves full parity coverage while
avoiding repeated execution of the unchanged reference implementation.

The desktop default remains unchanged until all gates pass. Earlier screens and
historical P1 results are not retroactively qualified by this evidence.

Revision 2 adds incremental Single equipment metadata, restricts optional equipment
interning to Multi (the measured Single hit rate was below 1%), and reuses bounded,
context-specific materialized role reports. All compact representations remain
enabled for Single. Four declared timing configurations passed the 5% tolerance:
fixed melee +1.26%, fixed magic +2.20%, configured ranged +2.68%, and configured
Multi +2.95%. Each retained three pairs and exact reference-output parity, with
no extensions. None demonstrated an improvement. Work paused before Auto/Multi
Auto timing, the full revision-2 candidate matrix and memory qualification to
address the unmet primary Multi improvement goal. This is not adoption evidence;
the complete checkpoint remains under `.tmp/p3/acceptance-v2`.

Revision 3 compacts transition BFS queue records while retaining FIFO expansion,
lexical action order and exact capacity/automatic-removal behavior, and defers
partial-assignment JSON until numeric rank keys tie. Its 850 focused tests passed
with 96% combined coverage, including 3,042 exhaustive transition comparisons.
Primary Multi timing used the declared five-pair extension: median 31.612474
seconds reference versus 31.439064 seconds candidate (0.55% faster). The median
difference (0.173410 seconds) was below reference MAD (0.208916), and paired median
gain (0.232726) was below paired-gain MAD (0.268232). Regression tolerance passed,
but improvement remains unqualified. No other revision-3 qualification cases ran;
all observations remain under `.tmp/p3/acceptance-v3`.

Revision 4 factors unchanged equipment out of transition queue states and caches
canonical transition problems behind the existing 8,192-entry full-key cache.
The measured outer-miss stream contained 5,685 problems: an inner cache of 1,024
entries required 2,204 BFS executions, compared with 2,172 at 8,192 entries. The
smaller inner bound retains approximately 99% of the avoided BFS work. Both
caches clear together and remain scoped to the frozen catalog/search context.
The focused lane passed 863 tests with 96% combined coverage; transition and
ranking modules have 100% coverage, with 4,386 exact transition comparisons.

Revision-4 primary Multi timing passed with three pairs: median 31.571304 seconds
reference versus 30.988209 seconds candidate (1.85% faster). The median difference
of 0.583096 seconds exceeded reference MAD of 0.256162, and paired median gain of
0.566313 exceeded paired-gain MAD of 0.239379. All eight warm-up/timed outputs
matched the frozen reference. Revision 4 subsequently failed the Multi memory
gate: three fresh processes per mode produced median sampled process-tree working
sets of 444.03 MiB reference and 545.98 MiB candidate (+22.96%, exceeding 5%).
All six outputs matched the frozen reference, with no sampling failures; 6–7
samples per observation make these coarse sampled peaks. Remaining qualification
was stopped. Revision 4 is not adopted; retained candidate reports are under
investigation. Evidence is retained under `.tmp/p3/acceptance-v4`.

The subsequent exact-Multi retention diagnostic found three live search owners
at leaf teardown, with 2,466 cached solution records and 2,083 unresolved report
factories. These factories retained their search owners, whose deduplicated
numerical caches occupied approximately 96.77 MB. The solution lookup trace had
identical 338 hits at bounds of 256, 1,024 and 8,192 entries. Revision 5 therefore
targets weak solution interning with a 256-key bound: active archive/beam records
remain reusable, while rejected records no longer keep whole searches alive.
The instrumented run preserved exact output parity; its timing and memory are
diagnostic only. Evidence is under `.tmp/p3-v5/solution-retention/`; fresh resource
qualification is required after the fix.

Revision 5 implements this weak interning and passed 869 focused tests. Its
solution module has 98% coverage, including prompt release without cyclic GC,
live archive/cap reuse, stale weak-reference callbacks, bounded negative results,
and rank/report lifetime. Independent review, Ruff and focused mypy passed.
Fresh Multi memory nevertheless failed: median 444.410 MiB reference versus
535.211 MiB candidate (+20.43%), with three fresh processes per mode, exact
output parity, no sampling failures and 6–7 samples per observation. No revision-5
timing was run. Evidence remains under `.tmp/p3/acceptance-v5`; matching-phase
retention analysis is required before another qualification attempt.

The matching-phase comparison isolated a larger lifetime issue: the final
role-product `expanded` list retained 65,536 candidates through later frontier
work, despite only the selected beam being needed. At refinement entry the
candidate had 66,399 live assignment records but only seven compact solutions;
its numerical cache matched the reference at approximately 69.4 MiB. The compact
assignment metadata made this unnecessary retention substantially more expensive.
Revision 6 releases the temporary expansion list after beam selection in both
execution paths, preserving candidate order, search budgets and surviving rows.
Instrumented phase evidence is under `.tmp/p3-v5/phase-memory/` and does not count
as resource acceptance.

Revision 6 passed the fresh Multi memory gate: median 430.535 MiB reference and
431.238 MiB candidate (+0.163%), with three processes per mode, exact output
parity and no sampling failures. Samples numbered 6–7 per observation. Both modes
include the temporary-list cleanup; this is not a comparison against the older,
more memory-intensive reference. Primary Multi timing also passed: median
32.126934 seconds reference versus 31.186635 candidate (2.93% faster), with a
0.940299-second difference exceeding reference MAD 0.266919 and paired-gain
median 0.940299 exceeding paired-gain MAD 0.309053. Three pairs were sufficient;
all eight outputs matched the reference. Remaining gates are pending under
`.tmp/p3/acceptance-v6`.

Revision 6 subsequently passed fixed-melee timing (6.744811 to 6.581517 seconds)
and fixed-magic timing (12.369887 to 12.774577 seconds, +3.27%), but failed configured
ranged after the declared five-pair extension: 10.228951 to 10.749181 seconds
(+5.086%). Paired-gain MAD was 0.205781 seconds, leaving tolerance uncertainty
unresolved. All 12 ranged outputs matched exactly. Qualification stopped before
the remaining cases; revision 6 is not adopted. The next diagnostic targets the
Single configured-ranged path rather than repeating the same source measurements.

The matched configured-ranged profiles retained exact output parity and identified
mapping-view creation and inherited lookup overhead in compact equipment
validation. Revision 7 provides direct fixed-slot `get`/membership operations
and iterates the cached ordered pairs during validation. Keyword arguments,
defaults, unknown/unhashable keys and validation message order are preserved.
Seventy-eight focused tests, Ruff and mypy passed. Profile timings are diagnostic
only; revision 7 requires fresh qualification, starting with configured ranged.
That gate passed with three pairs: median 10.455350 seconds reference versus
10.645507 candidate (+1.82%), with clear tolerance and all eight outputs matching.
Remaining revision-7 gates are pending under `.tmp/p3/acceptance-v7`.
Fresh Multi memory passed at 430.836 MiB reference versus 435.875 MiB candidate
(+1.17%), with three processes per mode, exact parity and no sampling failures.
Primary Multi timing passed with three pairs: 32.044030 to 31.073571 seconds
(3.03% faster). The 0.970459-second median difference exceeded reference MAD
0.284115; paired median gain 0.816075 exceeded paired-gain MAD 0.129732.
Fixed melee also passed its regression gate (6.827423 to 6.647664 seconds; no
convincing gain claimed), but fixed magic failed clearly after three pairs:
12.116171 to 13.008782 seconds (+7.37%). Tolerance was not inconclusive, so no
extension applied. All eight magic outputs matched exactly. Revision 7 is not
adopted; remaining qualification stopped, and the next profile targets fixed magic.

Matched fixed-magic profiles found 156,846 slot updates and 1,305,640 compact
equipment equality calls from frontier diversity selection. Revision 8 specializes
append-only slot updates, removes unnecessary storage from mapping views, and
uses exact cached equality keys for homogeneous compact-state diversity selection.
Mixed/custom rows retain the prior equality path; representatives, band order,
limits and rank-call counts remain unchanged. An optional fixed-score cache reuse
was rejected during review because canonical cache keys can conceal different
first-seen fractional-sum orders. Independent numerical cache behavior is retained.
These are diagnostic findings, not qualified speedups; fresh acceptance is required.
Revision 8 passed 916 focused tests and independent review. Its first acceptance
gate, fixed magic, passed with three pairs: 12.603365 seconds reference versus
12.266688 candidate. Regression tolerance is clear; the apparent speedup is not
convincing relative to variability and is not claimed. All eight outputs matched.
Remaining gates are pending under `.tmp/p3/acceptance-v8`.
Configured ranged passed its declared five-pair extension at 10.356346 seconds
reference versus 10.612452 candidate (+2.47%). Fresh Multi memory passed at
431.711 versus 432.496 MiB (+0.18%), with six distinct processes, no sampling
failures and 6–7 samples per observation. Multi timing passed with three pairs:
32.168248 to 30.761677 seconds (4.37% faster), exceeding both the reference-MAD
and paired-gain-MAD thresholds. Every recorded output matched the frozen oracle.
Fixed melee also passed at 6.776694 versus 6.412262 seconds. Configured Auto with
three workers remained unqualified after the allowed five-pair extension:
26.216433 versus 27.374648 seconds (+4.42%). Although the median is within 5%,
paired-gain MAD of 0.641270 seconds leaves tolerance uncertainty unresolved.
All 12 Auto outputs matched exactly. Qualification stopped before remaining
memory, full parity and Multi Auto checks; revision 8 is not adopted. The next
diagnostic examines concrete Auto worker leaves rather than parent wait time.

The exact Auto magic-leaf profile located redundant compact wrapping at the full
variant-report boundary: `_report_variant` seeded complete performance reports,
created another compact solution, then immediately expanded it for a lexical tie.
Revision 9 uses the existing report-only bypass on that copied search. Outer
compact search and variant scoring remain enabled, and the original validation
and full-report path supplies the requested payload. Ninety-three focused tests
passed, including boundary parity across styles, joint roles, defence objectives
and cancellation. Profiles and exact leaf outputs remain under
`.tmp/p3/auto-v8-diagnosis`; new qualification starts with worker Auto.
Revision-9 configured Auto with three workers passed three pairs: 26.818943
seconds reference versus 25.485668 candidate (4.97% faster), with clear regression
tolerance and convincing gain. All eight outputs matched exactly. Remaining
qualification is pending under `.tmp/p3/acceptance-v9`.
The remaining short timing controls also passed: fixed magic 12.305247 to
12.156499 seconds, configured ranged 10.352461 to 10.255747, and fixed melee
6.826825 to 6.406330. Primary Multi passed at 32.107796 to 30.617329 seconds
(4.64% faster), exceeding both variability thresholds. Fresh Multi memory passed
at 429.465 versus 431.395 MiB (+0.45%). All outputs matched exactly. Fixed-magic
memory, the complete current-candidate parity matrix and Multi Auto resource
checks remain pending.

Fixed-magic memory subsequently passed: 348,905,472 bytes reference median versus
333,647,872 candidate (-4.37%), with six fresh processes, exact parity and zero
sampling failures. There were 4–5 samples per process; these remain coarse sampled
peaks. All 17 original P1 parity configurations also passed on revision 9. The
four additional Multi Auto correctness cases and Multi Auto resource gates are
still pending; no desktop activation has occurred.

All four additional Multi Auto cases subsequently passed, completing all 21
revision-9 candidate parity configurations against the sealed reference cohort.
Each raw output was revalidated. This includes full serial/three-worker Multi
Auto, mixed configured options and an Auto role with a fixed-options partner.
Multi Auto memory and timing remain the final resource gates before selection
and desktop activation.

Multi Auto memory passed with six fresh process trees: median 2,040,049,664 bytes
reference versus 2,086,154,240 candidate (+2.26%, within 5%). Every output matched
the golden result, with zero sampling failures and 3,722–3,803 samples per run.
All 21 correctness configurations and all three memory cases now pass. Multi
Auto timing remains the final resource gate before selection and desktop adoption.

### P3 accepted resource and correctness cohort (revision 9)

The final Multi Auto timing gate passed with three pairs: 251.481723 seconds
reference versus 248.404350 candidate (1.22% faster), with convincing gain and
clear regression tolerance. The selector returned `adopt: true`, `reasons: []`.
All six timing cases used three alternating pairs after one warm-up per mode;
no revision-9 extension was required. Every measured output matched the sealed
reference, as did all 21 current-candidate parity configurations.

| Case | Workers | Reference median (s) | P3 median (s) | Change |
| --- | ---: | ---: | ---: | ---: |
| Fixed melee | 1 | 6.827 | 6.406 | -6.16% |
| Fixed magic | 1 | 12.305 | 12.156 | -1.21% |
| Configured ranged | 1 | 10.352 | 10.256 | -0.93% |
| Configured Auto | 3 | 26.819 | 25.486 | -4.97% |
| Multi | 1 | 32.108 | 30.617 | -4.64% |
| Multi Auto | 3 | 251.482 | 248.404 | -1.22% |

Every case passes the regression gate. The small apparent fixed-magic and
configured-ranged gains are not claimed as convincing speedups. Both intended
Multi workloads pass the separate variability-aware gain requirement.

| Memory case | Workers | Reference median (MiB) | P3 median (MiB) | Change |
| --- | ---: | ---: | ---: | ---: |
| Fixed magic | 1 | 332.74 | 318.19 | -4.37% |
| Multi | 1 | 429.46 | 431.39 | +0.45% |
| Multi Auto | 3 | 1,945.54 | 1,989.51 | +2.26% |

All 18 fresh-process observations passed exact output validation with no sampling
failures. These are sampled process-tree working sets, including shared pages
in each process, not exact allocation high-water marks. Single/Multi sampling was
coarse (4–7 observations per run); Multi Auto produced 3,722–3,803 observations.
Raw evidence, source snapshots and the selector result are retained under
`.tmp/p3/acceptance-v9/`; revisions 1–8 retain their original rejected status.
Independent audit passed: 62 measured current/snapshot source files and 144 sealed
reference files verified, with independently recomputed normalized digests for
21 candidate outputs, 21 golden outputs, 48 warm-up/timing outputs and 18 memory
outputs. Input/cohort identities, observation order, serial/worker equality and
18 distinct memory PIDs were verified. All gates recomputed successfully and
source hashes remained unchanged through the audit.

Final focused verification passed 923 tests. New production modules have 99–100%
coverage; the reference-cohort tool has 100% and acceptance driver 89% (96%
combined). Ruff passed every changed/new Python file and mypy passed 19 production
and tooling files. Two additional ammunition-sharing assertions were reproduced
against HEAD during development (consumable-exempt purchase cost and the existing
empty utility combat-option shape); these pre-existing failures are outside P3
and were not changed. This is focused local validation, not a full-suite or hosted
CI claim.

Desktop `combined` now enables P3 and logs compact-state activation. `baseline`
and `lazy` leave P3 off; startup worker fallback preserves the selected profile.
Generic service/direct/Pi defaults retain their existing behavior. The accepted
numerical modules are unchanged; desktop factory activation/logging is the only
production change after the accepted source snapshot.

Forty-two desktop/factory/HTTP tests and two automated Chrome browser tests passed,
covering profile activation, startup fallback, baseline rollback, cancellation,
recovery and result publication. P3 HTTP/browser fixtures use the actual factory
flag; an explicit P1-only fixture remains for comparison. Ruff, focused mypy and
the final whitespace check passed. This is automated local browser evidence.

Full original P3 is complete with no implementation scope deferred. No existing
desktop process was restarted, private configuration edited, commit/push made,
or hosted CI/deployment claimed. A normal desktop restart loads the adopted code.

### P1: Factored numerical evaluation and lazy reporting

Create immutable internal records for equipment totals, legal attack contexts,
outgoing damage, defensive rolls, and resource consumption. Each calculation
should depend only on the inputs it actually uses. Retain physical identities,
ownership, acquisition cost, and transition information separately.

`_Search.performance()` currently selects an option with lightweight scores and
then constructs and serializes full performance for each cache miss. Defer rich
models and explanations until they are needed. Apply the same separation to
fixed-option scoring and frontier combat variants.

Prepare invariant attack/target/prayer constants and resource-consumption costs.
Running-cost ranking should use compact numeric values; final results can expand
those values into resource descriptions with complete provenance and unknowns.

### P2: Shared evaluator across independent search policies

Keep DPS, metric-first, diverse, running-cost, and action-cap policies independent,
but let them reuse raw numerical evaluations and structural equipment facts.
Equipment aggregation can also be reused across potion profiles; boosted scores
must retain the appropriate level/context identity.

Do not share an objective's selected combat-option winner indiscriminately.
Identical gear can prefer different attacks, stances, spells, or prayers for DPS,
defence, accuracy, and cost. Start with shared calculations under existing search
order and budgets. Later experiments can share expansions with independent
retention quotas for each objective and cap.

A single weighted DPS/defence/cost score is unsuitable for preserving all tradeoffs.
A shared finite beam also risks allowing one objective to crowd out another.

### P3: Compact equipment and solution states

Replace hot-path string-keyed dictionaries with fixed slot tuples and compact
constraint/score records. Compute canonical identities and ranking information
once, and intern repeated solutions across action caps and result archives.

`_solution_key()` currently serializes rich loadouts for its final tie-breaker.
Preserve that ordering during a parity-preserving migration; numeric tuple order
is not automatically equivalent to lexical JSON order.

Multi must retain physical item identities or reference counts for union purchase
cost, inventory occupancy, and directional transitions. Equipment-prefix scoring
already increments integer bonuses; preserve its ordered fractional magic-damage
sum rather than introducing different rounding behavior.

### P4: Specialized Single-mode numerical search

Prototype a sparse dynamic program within fixed weapon/ammunition and combat
contexts. Build relevant stat vectors slot by slot with backpointers to item IDs.
Merge equivalent vectors and prune only states with proven dominance under the
remaining constraints. Preserve all components needed by the chosen secondary
metric, including both components of weakest-component objectives.

Keep raw partial strength totals: equal current max hit does not imply equal
future max hit. Partition by compatibility, powered effects, and resource rules.
Damage-cap support rules can invalidate the assumption that more strength always
dominates. Sparse nondominated sets can still explode, so measure state growth.

Experiment with optimistic completion bounds using remaining-slot maxima and
known feasible frontiers. A branch may be pruned only when no supported completion
can improve the required archive. The existing beam can provide initial incumbents.

This fits Single better than Multi, where equal combat stats do not imply equal
item sharing or transitions. It is a new search policy and can return different,
potentially better results even when its pruning is mathematically sound.

### P5: Native batches and desktop scheduling

After compact data is established, prototype batches containing expansion,
compatibility, scoring, and ranking work. Avoid one native call per candidate.
Keep Python responsible for input contracts, provenance, and public reporting.
Preserve integer floors, floating-point order, support rules, and deterministic
ties; use the Python evaluator as a differential reference.

Cython is a possible prototype route; Rust or C++ are other implementation options.
Efficient native numerical execution can also enable threads sharing immutable
contexts. Releasing the GIL alone does not accelerate single-threaded execution;
see [Cython's explanation](https://docs.cython.org/en/latest/src/userguide/nogil.html).

The current desktop worker limit is three, and tasks generally contain complete
discipline/potion branches. A fixed-discipline, fixed-potion request has limited
parallelism through that mechanism. Investigate a global scheduler with CPU and
memory limits, stable task IDs, deterministic merges, and dependency-aware stages.
Respect dependencies such as running-cost exploration receiving secondary-updated
winners. Avoid oversubscribing native threads and process workers together.

### P6: Time to useful results and repeated interactions

Publish explicitly provisional loadouts and then improving tradeoff archives.
Existing progress telemetry does not itself provide those usable results.
Investigate reuse of complete archives for changes that only affect publication,
such as allowed DPS-loss filtering. These improve interaction latency separately
from the time required to complete the initial search.

## Alternatives and shortcuts

| Approach | Assessment |
| --- | --- |
| GPU evaluation | Revisit after demonstrating sufficiently large, regular numerical batches. Current irregular Python-object work is a poor starting point. |
| Generic solver replacement | Useful as a reduced-problem oracle; combat floors, rational accuracy, item unions, and transitions need substantial modeling. [CP-SAT requires integer models](https://developers.google.com/optimization/cp/cp_solver). |
| Meet-in-the-middle enumeration | Potentially useful after strong pruning; tables and multiobjective joins can otherwise be very large. |
| Smaller beams, pools, or refinement budgets | An explicit search-quality tradeoff, not equivalent computation performed faster. |
| Skipping zero-cost melee cost exploration | Mathematical cost-frontier simplification is tempting, but the extra bounded search can discover DPS improvements missed by the main lane. Preserve that exploration elsewhere or treat this as a policy change. |
| Large whole-loadout caches | Measure actual reuse and memory; the cardinality experiment favors investigating narrower calculation dependencies. |

## Acceptance and tracking

**Current standard (adopted 2026-11-10):** use the staged validation workflow below
for subsequent performance work. It replaces the stricter repeated timing/memory
qualification used during P1. Historical P1 gates, measurements and rejected
revisions remain unchanged as evidence of the decisions made at that time.

Two distinct acceptance standards apply. Refactors that preserve search policy
must retain full result parity, excluding observational timing. New search policies
must demonstrate correctness and frontier quality; exact historical IDs need not
be the only acceptance measure if a better feasible result replaces an old point.

### Staged validation without reducing result quality

The reduced validation cost comes from fewer repeated measurements and practical
resource tolerances. It does not authorize smaller beams, reduced work budgets,
missing frontier points, weaker eligibility checks or less accurate arithmetic.
Completion still covers the full implementation scope of the selected phase.

1. **During development:** run focused differential tests, reduced fixtures and
   affected integration tests after relevant changes. Keep exact checks for combat
   arithmetic, rounding, ties/IDs, legal attacks, prayers/potions, ownership,
   acquisition costs, unknown resource state, inventory and transitions. Preserve
   independent objective winners and existing search budgets for P2/P3 refactors.
   Retain bounded-cache, invalidation, memory-lifetime and context-cleanup tests.
2. **At a stable candidate:** run one complete frozen-scenario parity matrix,
   including Single, Multi, Auto, Multi Auto, configured/fixed options, potions,
   secondary objectives, running-cost frontiers and refinement where supported.
   Compare complete normalized results, not only the selected winner: all archives,
   curves, costs, actions, options and IDs must match for parity-preserving work.
   Exclude only declared observational fields. A correctness failure blocks adoption.
3. **Performance qualification:** choose 4-6 representative timing configurations
   before measuring, covering the intended benefit, a likely regression/control
   case and relevant serial/worker paths. Use frozen inputs, one warm-up per mode
   and three paired runs with alternating reference/candidate order. Do not run
   profiling, memory sampling or competing heavy tests during timing. Require a
   convincing improvement in an intended workload as well as acceptable regressions
   in the selected controls; do not claim a gain from an isolated fastest run.
4. **Memory qualification:** measure relevant high-memory and changed-lifetime
   cases separately from timing, with three fresh processes per mode/case and
   descendant processes included. Report sampled peak process-tree memory, sample
   density and its limitations. Keep explicit resource ceilings where deployment
   constraints require them, even if the percentage tolerance would pass.
5. **Execution and UI checks:** reuse still-applicable worker parity, cancellation,
   recovery, rollback and browser evidence. Rerun affected checks when dispatch,
   context lifetime, serialization, activation, API or UI boundaries change. Record
   why reused evidence remains applicable; do not rerun the entire browser/worker
   suite after every isolated numerical adjustment.

Runtime and memory each allow a **5% regression**: candidate median must be at
most `1.05 * reference median` for the corresponding case and measurement type.
Runtime uses measured paired-run wall times; memory uses the three fresh-process
sampled peaks. MAD remains a variability diagnostic, not an additional allowance
on top of the 5% tolerance. These gates deliberately accept small resource
regressions; they do not relax output correctness or search quality.

Predeclare the intended improvement case and the interpretation of variability.
By default, call a timing gain convincing only when both the difference of medians
and the median paired gain are positive and exceed their respective reference-time
and paired-gain MADs. This is a practical repeatability heuristic, not a formal
statistical guarantee. If variability leaves the gain or tolerance decision
inconclusive, use a predeclared single extension from three to five total timing
pairs. Retain every initial observation and complete all added pairs; never retry
until a favorable result appears. Larger or reproducible regressions require
investigation. An unresolved gate remains unqualified; record uncertainty honestly.

Freeze and identify the implementation and inputs used for final evidence. Repeat
the complete parity matrix after subsequent numerical/search changes before
adoption, but use focused checks during intermediate fixes. Repeat only affected
performance configurations after a fix, broadening when shared hot paths change.
Documentation-only changes do not invalidate numerical measurements; activation
or wiring-only changes need their affected integration checks. Record source/input
hashes, retained evidence, coverage decisions and any bounded extension so that
results from different revisions are not silently combined.

For P4 and any other new search policy, exhaustive reduced-case oracles and
comparison against every baseline tradeoff remain mandatory. Each old tradeoff
must be matched or improved under the same feasibility constraints, including
offensive and defensive extremes. Exact old IDs alone are not the acceptance
criterion for an intentionally changed search policy. Native evaluation in P5
still requires numerical differential checks; scheduling and P6 publication/reuse
changes retain their execution and invalidation correctness requirements.

Existing P1 acceptance tools encode the historical stricter gates. They are not
silently reinterpreted by this documentation change: subsequent implementation
work must explicitly select or adapt tooling for this standard and test the new
gate logic. No historical failed result is retroactively accepted.

### Phase tracking

| Work item | Completion evidence | Status |
| --- | --- | --- |
| Representative desktop benchmark suite | Frozen Single/Multi/Auto cases, option/potion variants, bonus and defence-roll metrics, repeated timings, peak memory, cancellation, complete result fingerprints | Delivered; combined adoption matrix qualified |
| Reusable dependency probe | Tracked portable fixture and counting harness; equivalence checks; bounded-cache hit/miss, key-cost, and memory measurements | Delivered; private full-catalog inputs remain ignored |
| P1 factored evaluator | Differential scalar/full-model tests; complete archive parity; measured runtime and memory | Complete: all original P1 scope adopted in desktop combined; final matrix and live browser/rollback passed |
| P2 shared evaluation | Lane winner isolation; context invalidation tests; stable logical work budgets; observed reuse | Partial: bounded ranged numerical sharing; broader evaluator sharing pending |
| P3 compact states | Exact acquisition, transition, inventory, tie-order and fractional-sum parity; allocation/serialization reduction | Complete and adopted in desktop combined; v9 passed all 21 parity, six timing and three memory cases, independent audit and desktop/HTTP/browser checks |
| P4 Single solver prototype | Small exhaustive oracles; state-count curves; feasibility and comparison against every existing tradeoff and both extremes | Pending |
| P5 native batch prototype | Python differential oracle; deterministic arithmetic/ties; end-to-end and batch measurements | Pending |
| P5 desktop scheduler | CPU/memory scaling, serial/parallel parity, startup/tail latency, cancellation and failure isolation | Pending |
| P6 provisional results/archive reuse | Correct provisional labels and baselines; verified publication-only invalidation boundaries | Pending |

Recommended sequence: establish benchmarks and P1/P3 representations, add P2
sharing, then evaluate the P4 solver and P5 native experiments. Choose further
investment using measured end-to-end results. P6 can proceed independently once
its publication and cache boundaries are established.

- [x] Inspect current architecture and existing optimizations.
- [x] Collect exploratory phase/profile measurements and dependency counts.
- [x] Verify matching solution digests for the observation runs.
- [x] Record evidence, limits, proposals, and acceptance criteria in the repository.
- [x] Establish the representative desktop baseline and portable probe.
- [x] Implement and differentially validate an opt-in ranged numerical experiment.
- [x] Record completed experiments' revision, environment, scenario provenance,
  timings, memory, correctness/quality evidence, and keep/reject decision here.

For parity work, compare selected and unrestricted solutions, every action-cap
curve, complete secondary/running-cost archives, attack/prayer/potion choices,
purchase costs, inventory occupancy, directional actions, and deterministic IDs.
Retain eligibility, ownership, unknown cost/charge state, and support semantics.

For new policies, require each old tradeoff to be matched or improved under the
relevant feasibility and acquisition constraints, check offensive and defensive
extremes, and use exhaustive reduced cases. Keep bounded-search claims explicit.
Removing dominated prefixes can free beam positions or work budget, so preserving
the mathematical objective does not automatically preserve current bounded output.

## First milestone implementation (2026-11-08)

The portable tooling and an **opt-in** ranged numerical experiment are implemented.
The default evaluator retains the original path. This is not full-catalog desktop
acceptance and does not enable caching in the service or spawned workers.

### Reproduction

From the repository root, using the repository virtualenv:

```powershell
.\.venv\Scripts\python.exe -m tools.benchmark_gear_desktop --case single_ranged --output .tmp/desktop-performance/baseline
.\.venv\Scripts\python.exe -m tools.benchmark_gear_desktop --case single_ranged --ranged-cache 4096 --output .tmp/desktop-performance/cache-4096
.\.venv\Scripts\python.exe -m tools.probe_gear_dependencies --case single_ranged --output .tmp/desktop-performance/probe
```

The runner defaults to one warm-up and five measured repetitions. Other named
cases cover melee, magic, Multi, Auto, potion search, defence rolls, and forced
frontiers; `--thorough` selects refinement. `ranged_diagnostic` forces complete
and running-cost frontiers. These are substitute-fixture cases, not the original
private account. The fixture includes 119 items, so results cannot establish
full-catalog desktop latency.

Use `--dump <dump> --snapshot <snapshot>` for private frozen observations and
prices. Each run archives catalog/content and job inputs in `inputs.json`, with
execution settings for `--frozen <inputs.json>` replay. Keep these artifacts
ignored. `--workers 2` supports baseline branch execution; combining workers
with the context-local experiment is rejected explicitly.

Reports retain environment, input hashes, individual timings, phase/work counters,
and recursive complete-result fingerprints including Auto branches. Only named
observational timing/progress fields are removed. `--memory` runs a separate
Python allocation measurement; **it does not measure process-tree RSS or worker
memory**. cProfile remains available through the existing profiling helper.

### Experiment boundaries and evidence

The immutable ranged outgoing record is reused only after legality checks.
Candidate bonus vectors, defensive rolls, public reports and objective-specific
option winners remain independent. Its bounded cache is local to an explicit
experiment context and defaults off. Numerical keys contain the level, offensive
prayer modifiers, stance, adjusted attack/strength bonuses, weapon identity and
behavior, target defence/subtype, signed armour and damage cap.

The first portable probe observed 278,105 accesses and 9,803 distinct keys.
Chronological LRU simulation recorded 264,171 hits at 4,096 entries and 268,302
hits at 16,384/65,536 entries. Complete recursive result fingerprints matched
with observation enabled. The trace plus simulation peaked at 282,093,070 Python
allocation bytes; this is instrumentation memory, not cache size or RSS. Key
cardinality and simulated hits are not application speedup evidence.

Focused tests cover original-versus-experimental scalar/full results, ammunition
adjustment, subtypes, signed armour, caps, patterns, stance/prayer/level changes,
eviction and unsupported equipment. Tooling tests cover complete nested digests,
frozen replay settings, worker lifecycle, provenance and memory-pass separation.

### Remaining acceptance work

- Freeze and measure representative private full-catalog inputs; none were present
  in this checkout during implementation.
- Run the full named matrix with serial/worker comparisons and cancellation checks.
- Measure process-tree peak RSS and retained-cache/key-construction memory costs.
- Keep any production-enable decision pending until repeatable end-to-end gains,
  complete parity and realistic memory evidence are available.

The existing `test_real_spawn_branches_match_serial_and_reuse_pool` compares
unfiltered timing dictionaries and fails on observational timing differences.
A separate real-spawn check confirmed recursive result parity after removing
observations. The existing test was left unchanged.


### Repeated portable timing experiment

On the uncommitted implementation based on revision `6c1fbec`, Python 3.12.10
on this Windows desktop, two sequential batches each ran one warm-up plus five
unprofiled repetitions per configuration. All 40 measured responses had the same
complete recursive result fingerprint:
`312277421b31fb7f3bc7bd325e9afee7e546e8623668e2ac1e13258d178d06a0`.
Inputs and reports are ignored under `.tmp/desktop-performance/batch-*`.

| Configuration | Batch 1 median seconds | Batch 2 median seconds |
| --- | ---: | ---: |
| Original path | 9.646 | 8.480 |
| 4,096 entries | 8.650 | 8.629 |
| 16,384 entries | 8.113 | 8.753 |
| 65,536 entries | 7.380 | 8.094 |

**Decision: no production adoption.** The smaller capacities regressed in the
confirmation batch. The largest improved both medians, but its second-batch gain
(0.386 seconds) was smaller than the original path's median absolute deviation
(0.478 seconds). This does not satisfy the repeatable-gain criterion. The
prototype remains explicitly opt-in for further investigation, with no default
cache or service/worker integration. No winning capacity is selected. These
sequential batches are exploratory evidence, not controlled interleaved trials.

Validation: 155 focused tooling/combat tests passed before the observer timing
addition; its subsequent focused lane passed 90 tests. Tooling coverage was 92%
and the numerical module 100%. Focused mypy, Ruff and diff whitespace checks
passed. The frontier/Auto/potion/parallel lane had 110 passes and the one existing
timing-comparison failure described above. No hosted CI or live desktop-service
acceptance is claimed.

## Controlled full-catalog follow-up (2026-11-08)

A subsequent read-only capture from the configured desktop source supplied
5,435 catalog items and 1,045 cached prices. The account observations were last
synced at `2026-11-08T16:28:40+00:00`; evaluation time was frozen at
`2026-11-08T16:29:00.537886+00:00`. This uses real account facts with the named
`single_ranged` request (Fast, fixed divine ranging, optimized allowed prayers,
balanced-defence frontier and 100% allowed loss), **not an exact replay of a
previous user request**. Complete/running-cost frontiers were not forced.

- Snapshot: `a22a32f7617fd4f42759f39c3ea210c520a093c4ceeff1f4c980cd568cc69d1b`.
- Catalog: `c002eaec8081cf97cc8994cc0dd8a7b3f81145aec69972c30238bd3a10720604`.
- Frozen input hash: `618d8095127da404cfd7e6dcee6bb01341ffbf1e8da869da7738e86cb1df3429`.
- Complete result: `30bff44d076f865e4e4cc7ed718efd515d26b6b8728b6411a74aabb7250f7f6d`.

The JSON replay path now restores price timestamps before worker decoding and
recomputes derived provenance so archived metadata cannot override current input
hashes. Regression tests cover both issues; the worker IPC contract is unchanged.

### Interleaved timing result

`tools.compare_gear_desktop` runs one warm-up per mode and at least five pairs,
alternating original/cache and cache/original order. Each result, including work
counters and nested archives, must match one recursive fingerprint. Memory and
key instrumentation run separately. This run used a 65,536-entry upper bound.

| Pair | Original seconds | Cached seconds | Original minus cached |
| --- | ---: | ---: | ---: |
| 1 | 13.787 | 14.132 | -0.345 |
| 2 | 15.081 | 14.589 | 0.492 |
| 3 | 14.377 | 14.083 | 0.294 |
| 4 | 14.707 | 14.293 | 0.414 |
| 5 | 14.763 | 13.981 | 0.783 |

Original/cached medians were **14.707/14.132 seconds**, a 0.576-second (3.9%)
reduction. Median paired gain was 0.414 seconds. Original timing MAD was 0.330
seconds and paired-gain MAD 0.120 seconds. The timing criterion passed, although
one pair regressed and the effect is modest. This is a single scenario on one
Windows desktop, not a general speedup estimate.

### Separate memory, dependency and cancellation evidence

A Windows working-set sampler now includes the measured process and descendants,
rejects failed samples, and closes native handles. A native integration test
verifies detection of a child allocation. For these measurements an external
controller sampled a fresh optimizer process, avoiding the GIL contention seen
with in-process sampling. Original/cached sampled peaks were **326,529,024 /
326,627,328 bytes**, with 231/235 successful samples and no sampling failures.
Shared pages count in each process; sampled peaks can miss short spikes. These
similar totals do not establish exact retained-cache overhead.

An independent observer pass recorded **392,078 accesses**, **382,364 hits** and
**9,714 misses/retained entries**. Key construction consumed 0.370 seconds in that
instrumented pass; this time is not subtracted from uninstrumented runtimes.
Memory and observer passes retained the same complete result fingerprint.

A full-catalog request was cancelled when it reached frontier exploration, then
a fresh request completed with the reference fingerprint. Four focused worker
cancellation/recovery tests and four API cancellation tests passed; worker
lifecycle evidence uses focused fixtures, not a full-account Auto performance run.
New/updated tooling and numerical tests passed 75 tests with 96% combined coverage.
Focused native-memory/combat mypy, Ruff and whitespace checks passed.

### Decision and reproduction

**Keep the prototype opt-in for further work; do not enable production caching.**
The full-catalog timing and sampled-memory evidence justify retaining this narrow
experiment, superseding the earlier fixture-only inconclusive result. Full
Single/Multi/Auto, potion, prayer and defence-roll acceptance remains necessary
before broader adoption. No public API, service dispatch, or worker-cache setting
has changed. The next substantial P1 experiment should defer rich reports only
for partial beam states, preserving full solution construction and lexical ties.

Private artifacts, including snapshots and detailed result archives, remain
ignored under `.tmp/desktop-controlled/`. With the captured input available:

```powershell
.\.venv\Scripts\python.exe -m tools.compare_gear_desktop --frozen .tmp/desktop-controlled/inputs.json --output .tmp/desktop-controlled/interleaved --pairs 5
.\.venv\Scripts\python.exe .tmp/desktop-controlled/measure_external.py
.\.venv\Scripts\python.exe .tmp/desktop-controlled/measure.py keys
.\.venv\Scripts\python.exe .tmp/desktop-controlled/cancel.py
```

The latter three are local experiment scripts, not tracked dependencies. The
reusable tracked memory API is `tools.gear_process_memory.measure_process_tree`;
use a controller process with the optimizer PID for dense sampling. A fresh
capture must be frozen again and identified separately; changing facts or prices
invalidates direct comparison with these recorded timings.

## P1 partial-state lazy reporting experiment (2026-11-08)

Implemented a separate opt-in `tracker.gear.lazy_reporting.lazy_reporting()`
context. Only ordinary Single searches with configured options/prayers use the
compact path. Fixed-option, special, Multi, and running-cost subclass behavior
retains the full-report path. Serial Auto/potion branches can use the experiment
with independent search instances; experimental context is not propagated into
spawned workers.

Immutable winner records preserve configured role, option and lightweight score.
Partial beam legality/DPS/secondary ranking uses projections. Full performance
cache entries, including preseeded frontier variants, remain authoritative.
Completed loadouts/solutions retain their existing reports, IDs and lexical ties;
materialization reuses the selected winner. Every frontier copy resets its compact
cache. Defensive projections needed by secondary ranking are computed for the
chosen winner without changing option selection. No-legal-option states preserve
their historical zero secondary score.

Review caught and fixed duplicate equipment preparation on the default full path;
a regression test now requires exactly one preparation. The initial timing batch
was discarded. The final batch below includes that fix and had no concurrent
benchmarks. Comparator isolation guards reject ambient lazy/numerical experiment
contexts that could contaminate the reference path. Thorough parity normalization
now excludes only `search.local_refinement.duration_seconds` in addition to the
previous observational fields; solution fields and work counters remain hashed.

### Standalone full-catalog evidence

Reused the controlled full-catalog inputs and request above, with the ranged
numerical cache disabled in both modes. One warm-up per mode and five AB/BA pairs
preserved the historical complete result fingerprint
`30bff44d076f865e4e4cc7ed718efd515d26b6b8728b6411a74aabb7250f7f6d`.

- Original median: **13.754 seconds**; lazy median: **12.083 seconds**.
- Reduction: **1.671 seconds (12.2%)**; paired median gain: 1.740 seconds.
- Original timing MAD: 0.051 seconds; paired-gain MAD: 0.068 seconds.
- Independent instrumentation counted **60,017 -> 9,131** full combat performance
  model serializations (84.8% fewer), with the same result fingerprint.

External-controller memory passes sampled three fresh processes per mode:

| Mode | Sampled peak bytes, runs 1 / 2 / 3 | Median bytes |
| --- | --- | ---: |
| Original | 326389760 / 326746112 / 326979584 | 326746112 |
| Lazy | 319016960 / 319377408 / 319950848 | 319377408 |

All six measurements completed without failed samples, with 211-239 samples per
run. Lazy median peak was below the largest baseline peak, satisfying the agreed
memory gate. Working-set sums count shared pages per process and can miss short
spikes; these are sampled process-tree peaks, not exact cache allocation costs.

Full-catalog frontier cancellation followed by a fresh request preserved the
reference fingerprint. The focused optimizer/frontier/options/prayer/potion/Auto
and tooling lane passed **153 tests**. A separate coverage pass covered **59/62
added executable lines (95.2%)** in optimizer/frontier, and the new context module
had 100% coverage; comparator coverage was 98%. Tests cover Fast/Thorough,
defence-roll projections, authoritative cache overrides, unsupported states,
selected winner reuse, fallback paths and cancellation. Ruff, focused mypy,
whitespace checks and code review passed.

**Decision: retain lazy reporting as an opt-in experiment.** Standalone parity,
report reduction, timing and sampled-memory gates passed on this frozen ranged
scenario. This does not establish production enablement or general full-catalog
Single/Multi/Auto performance. Public interfaces, search budgets and production
settings are unchanged.

Reproduction with the existing ignored inputs:

```powershell
.\.venv\Scripts\python.exe -m tools.compare_gear_desktop --frozen .tmp/desktop-controlled/inputs.json --experiment lazy-reporting --output .tmp/lazy-reporting/interleaved-final --pairs 5
.\.venv\Scripts\python.exe .tmp/lazy-reporting/memory.py
.\.venv\Scripts\python.exe .tmp/lazy-reporting/cancel.py
```

The latter commands are local experiment scripts using the tracked memory API.
All private snapshots and detailed results remain ignored under `.tmp/`.

### Separate combination comparison

After standalone acceptance, a second five-pair AB/BA comparison tested lazy
reporting alone against lazy reporting plus the 65,536-entry ranged numerical
cache. The runner applied lazy reporting on both sides and ranged reuse only on
the candidate side. This comparison preserved the same complete fingerprint.

Lazy-alone/combined medians were **11.543/10.927 seconds**, an additional
0.616-second (5.3%) reduction within this batch. Median paired gain was 0.714
seconds, exceeding baseline MAD 0.194 seconds and paired-gain MAD 0.071 seconds.
This passed the timing gate. Do not add or multiply this percentage with the
standalone result: the batches ran separately under different timing conditions.
No combined-mode memory or broader scenario acceptance is claimed.

Artifacts are ignored under `.tmp/lazy-reporting/combined/`. The local reproduction
script is `.tmp/lazy-reporting/combined.py`, using the tracked comparator's injected
runner. Both experiments remain disabled by default; no commit, publication or
deployment was performed.

## Desktop execution-profile integration (2026-11-08)

Server-owned `optimization_profile` now accepts `baseline`, `lazy`, and `combined`
in desktop settings. `TRACKER_DESKTOP_OPTIMIZATION_PROFILE` overrides it. The
configured value is injected into GearService and explicitly passed through
serial Auto/potion orchestration and both worker dispatch paths. Existing boolean
worker flags remain strictly validated; profile is the only admitted string option.
Generic services and direct optimizer calls default to baseline.

Each concrete Single branch creates fresh contexts. Combined adds bounded ranged
numerical reuse only for ranged branches; lazy restrictions and all existing
Multi/special/fixed/cost fallbacks remain unchanged. Contexts reset on completion
and exceptions, and do not join warm-worker preparation reuse. Timing estimates
include profile identity. Startup serial fallback preserves the selected profile;
optimization failures are never silently retried under baseline.

The desktop default is now **combined**, after the acceptance gates below passed.
Normal desktop use can explicitly select a profile; rollback is baseline followed
by the normal desktop restart, as documented in DEPLOYMENT.md. No live service
restart, Pi setting change, publication, or commit is included.

Tracked acceptance tooling:

```powershell
.\.venv\Scripts\python.exe -m tools.accept_gear_desktop_profiles --frozen .tmp/desktop-controlled/inputs.json --output .tmp/desktop-adoption/ranged-lazy --case ranged --candidate lazy --pairs 5
```

Named cases cover ranged, melee, magic, defence_roll, auto, potions, thorough,
diagnostic, and multi. Branching cases support `--workers 3`; diagnostics use a
separately labeled direct optimizer path to force complete/running frontiers.
All other comparisons call the actual GearService, using frozen catalog, account,
prices and evaluation time.

`select_default` requires a complete matrix, exact recursive parity, recomputed
paired-time gates, and fresh-process memory evidence before returning an optimized
default. It rejects malformed/duplicated observations, inconsistent frozen cohorts
or per-case hashes, invalid durations and reused memory measurement identifiers.
Missing evidence retains baseline with explicit reasons. Timing reports generated
before cohort metadata was added must be verified against their archived inputs
before enrichment; they cannot simply be relabeled.

### Desktop adoption acceptance and default selection

The complete gate selected **combined** for DesktopSettings. Generic GearService
and direct optimizer defaults remain baseline; explicit baseline rollback is
available through the desktop environment/YAML setting. No live process was
restarted and no private configuration was edited.

The same frozen account/catalog/prices were used for all named request variants.
Each comparison ran one warm-up per profile and five AB/BA pairs. All eleven
required case/worker configurations passed exact logical parity and the
no-material-regression gate. The comparison is local to this Windows desktop
and representative account, not a latency guarantee for every request.

| Case | Workers | Baseline median seconds | Combined median seconds |
| --- | ---: | ---: | ---: |
| ranged | 1 | 13.399 | 10.639 |
| melee | 1 | 12.521 | 10.648 |
| magic | 1 | 36.374 | 34.829 |
| defence_roll | 1 | 17.588 | 13.500 |
| auto | 1 | 97.800 | 86.277 |
| auto | 3 | 42.644 | 41.455 |
| potions | 1 | 24.189 | 19.275 |
| potions | 3 | 16.300 | 13.624 |
| thorough | 1 | 17.804 | 15.345 |
| diagnostic | 1 | 21.618 | 19.046 |
| multi | 1 | 33.277 | 33.320 |

Magic and three-worker Auto did not establish repeatable timing gains, but
passed nonregression. Multi uses the original path; its small median difference
was within baseline variation. Forced diagnostics are direct optimizer calls;
other rows exercise GearService and the normal worker-dispatch paths.

The incremental GearService comparison of lazy versus combined passed:
**10.046 -> 9.081 seconds**. Do not combine percentages across separate batches.

Twenty-seven fresh-process memory passes covered three profiles, three repeats,
and ranged/1-worker, Auto/3-worker, potion/3-worker cases. Every measurement
had a unique process measurement ID, matching input/result identity and no failed
samples. Baseline and combined medians follow (decimal MB):

| Case | Workers | Baseline sampled peak MB | Combined sampled peak MB |
| --- | ---: | ---: | ---: |
| ranged | 1 | 327.40 | 323.96 |
| auto | 3 | 1706.95 | 1342.98 |
| potions | 3 | 929.29 | 920.00 |

Every combined median was below the largest matching baseline peak. Working-set
sums count shared pages per process and sampling can miss brief spikes; these
are process-tree samples, not exact private-allocation measurements. Serial and
three-worker complete-result fingerprints also matched for Auto and potions.

Thorough initially differed only in refinement `performance_cache_misses`
(9,774 -> 9,919), which measures growth of the full-report cache. Lazy reporting
moves materialization between phases, so this instrumentation is retained in raw
reports but excluded specifically at `search.local_refinement` from logical
parity. Assignment/expansion budgets, seeds, solutions and every other normalized
field remained identical. A regression test protects that distinction. The first
diagnostic timing batch overlapped cohort verification and was discarded; the
table uses its clean replacement.

All archived inputs were independently checked against their recorded hashes
and one common cohort. Strict selection recomputed timing gates from complete
distinct pairs, checked per-case identities, memory freshness/completeness, and
the incremental gain. Lazy was retained as an available control profile; only
combined received the full timing matrix and qualified for the desktop default.

Detailed private artifacts and the gate decision remain ignored under
.tmp/desktop-adoption/ (selection.json, memory.json, serial-worker-parity.json,
per-case report.json and inputs.json). Reproduction uses the tracked acceptance
tool, memory sampler, and selection helper; the local memory/finish scripts are
experiment artifacts rather than tracked dependencies.

Final checks after selecting the desktop default: **214 focused tests passed**,
plus **79 worker/service/API tests passed** with the one previously identified
legacy timing-dictionary comparison deselected. Its timing-only failure was
already diagnosed before this adoption work; source was left unchanged. New
normalized profile comparisons cover real spawned workers and serial/worker
complete-result parity. Execution-profile module coverage was 100%, acceptance
tooling 97% (98% combined). Ruff, focused mypy across seven changed modules,
whitespace checks and review passed. No hosted CI, live desktop restart, commit,
push, or deployment is claimed.


## Desktop user acceptance and remaining P1 work (2026-11-08)

The user confirmed normal desktop acceptance checks, followed by a successful
baseline rollback and restoration to combined using the environment override.
This records user-observed UI, optimization, cancellation/recovery and rollback
acceptance; it is separate from automated frozen-data measurements. No live
restart or deployment by the coding agent is claimed.

The first live startup hid the profile INFO message because application logging
was not configured. The desktop entrypoint now initializes INFO logging. A fresh
subprocess test exercises startup and verifies the profile appears without the
test credential. All 28 desktop tests passed after this correction.

P1 is partially complete. The adopted work covers ranged numerical reuse and
lazy partial reporting for ordinary Single configured-option/prayer selection.
At this stage fixed-option partial scoring was experimental; the later desktop
adoption section supersedes that status. Combat-variant and running-cost reporting remain opportunities.
P3-P6 remain pending. This bounded P1 experiment first profiled current combined
with fixed combat options and prayers disabled, and proceeded after the full
report path ranked among the top five cumulative costs in two passes. Both
comparison sides retain combined; the candidate stays opt-in pending separate
adoption.


### Fixed-option profiling gate

Two serial cProfile passes replayed the same frozen full-catalog cohort with
fixed ranged combat options, disabled prayers, combined execution, and forced
complete secondary/running-cost frontiers. The full `performance()` path ranked
fifth by cumulative time in both passes: 15.139 and 14.661 seconds. Both recorded
114,395 full `evaluate_prepared_loadout` calls and the same logical fingerprint
`194316821c7a049f23997faa4bd1e69233c83264b51605ddcc0b11fb6c58ca97`.
This passes the investigation gate. Those cumulative times include numerical
work and overlap callers; they are not a prediction of serialization savings.
The separately instrumented comparison below determines actual benefit.

Private profiles and the fixed ranged/melee/magic request inputs are archived
under `.tmp/fixed-reporting/`. These are request variants on the frozen cohort,
not an exact replay of a newly captured live request. No search budgets or
eligibility rules were reduced.


### Fixed-option experiment boundaries and reproduction

The separate `fixed_reporting()` context enables lightweight partial reports for
exact ordinary `_Search` Single searches with fixed combat options and disabled
prayers. It does not route through option selection. Prepared physical-slot
validation, extra ancient-spell eligibility, full-cache overrides, secondary
metrics and final full reporting remain authoritative. Existing frontier copies
reset the compact cache. Multi, special and CostSearch retain their prior paths.
There is no worker flag, desktop setting, public schema or default change.

The tracked comparator now accepts `--experiment fixed-reporting`. Both sides
use current combined; only the candidate enters the fixed-reporting context.
It rejects ambient experiment contexts that could contaminate the comparison.
For example, with the ignored frozen request variant available:

```powershell
.\.venv\Scripts\python.exe -m tools.compare_gear_desktop --frozen .tmp/fixed-reporting/ranged/inputs.json --experiment fixed-reporting --diagnostic --pairs 5 --output .tmp/fixed-reporting/ranged/comparison
```

Measurements and acceptance below concern this serial opt-in experiment only.
Desktop adoption of an extension would require separate propagation and broader
acceptance; the existing combined profile keeps its qualified behavior.


### Fixed-option controlled results

Each serial forced-frontier case ran one warm-up per mode and five alternating
AB/BA pairs against current combined. Every run retained complete logical parity.

| Fixed discipline | Combined median seconds | Candidate median seconds | Repeatable gain | Full reports combined -> candidate (separate count pass) |
| --- | ---: | ---: | --- | ---: |
| ranged | 16.7061 | 14.2525 | Yes | 114395 -> 60029 |
| melee | 17.7276 | 15.5689 | Yes | 128385 -> 64902 |
| magic | 20.5857 | 19.3684 | No; nonregression passed | 129913 -> 68549 |

Ranged paired median gain was 2.4046 seconds, exceeding reference MAD 0.0508
and paired-gain MAD 0.1768 seconds. Melee paired gain was 2.0867 seconds,
exceeding reference MAD 1.0661 and paired-gain MAD 0.4534 seconds. Magic paired
gain 0.9517 seconds did not exceed paired-gain MAD 1.2570 seconds. Do not
interpret its lower median as an established repeatable gain.

Separate construction counts preserved the matching complete fingerprints.
Ranged constructed 47.5% fewer full reports. These counts are instrumentation;
the latency table comes from uninstrumented runs. Timings are local to this
Windows machine and frozen cohort, not general latency guarantees.


Six separately sampled fresh processes covered fixed ranged, three per mode.
Combined sampled peak bytes were 460075008 / 460742656 / 460976128; candidate
353824768 / 354074624 / 353439744. Medians were 460742656 and 353824768 bytes.
All measurements had unique identifiers, matching input/result identity, 217-269
samples and zero errors. Candidate median was below the largest reference peak,
passing the agreed memory gate. Shared pages count per process; sampled working
sets can miss short spikes and are not exact private-allocation measurements.

**Decision: retain fixed-option reporting as an opt-in P1 experiment.** Complete
parity, repeatable ranged/melee gains, all-case nonregression, fewer full reports,
and the primary sampled-memory gate passed. Magic's timing gain remains noisy.
This is not desktop adoption: combined, generic baseline behavior, public APIs,
worker dispatch and search budgets are unchanged. No agent restart, commit, push,
Pi change or deployment was performed.

Ignored evidence is under `.tmp/fixed-reporting/`: per-discipline frozen inputs,
comparison reports and raw results, `report-counts.json`, `memory.json`, and
`validated-summary.json`. The latter independently checks recorded hashes,
fingerprints, comparison gates, distinct memory identifiers and sample validity.
Local measurement orchestration scripts are private experiment artifacts; the
comparator and memory API are tracked reusable tooling.


Final focused verification passed **86 tests** (44 fixed-reporting, 28 existing
lazy-reporting and 14 comparator tests). Added fixed-score methods had 17/17
executable lines covered; the new context module had 100% coverage and comparator
coverage was 98.3%. Cases include Fast/Thorough complete archives, nonempty
supported powered results, real ancient rejection, ammunition/slot failures,
damage caps, flat armour, unsupported mechanics, secondary values, authoritative
cache overrides and nested/cancellation context cleanup. Ruff, focused mypy
across three modules, whitespace checks and independent review passed. This is
local Windows evidence; no hosted CI or broader deployment acceptance is claimed.


## Fixed-option desktop integration and adoption gate (2026-11-08)

A private boolean execution flag now carries the fixed-option path explicitly
through GearService, serial orchestration and spawned potion/Auto jobs. It is
strictly validated, effective only with combined, and included in timing-model
identity. Each concrete eligible branch enters a fresh context. Generic service
and direct optimizer calls keep the flag disabled; baseline/lazy do not enable it.
No public request field or profile name was added.

Auto requires explicit combat-option filters at request validation. Consequently
Auto controls preserve those filters and exercise fallback/dispatch isolation;
they do not demonstrate fixed-option execution. Fixed Single and potion branches
exercise the new path. Multi and CostSearch preserve their prior behavior.

The tracked `tools.accept_fixed_reporting` compares reference combined with the
flag disabled against candidate combined with it enabled, through actual
GearService and real warm workers. Only forced diagnostics use direct optimizer
calls. Fourteen configurations include fixed ranged/melee/magic/defence-roll/
Thorough/diagnostic, fixed potions with one/three workers, Auto controls with
one/three workers, Multi and configured ranged/Auto/potion controls. Every
comparison uses one warm-up and five alternating pairs on the same frozen
account/catalog/prices/time cohort. Publication and search budgets are unchanged.
The separate memory gate requires three fresh processes per mode for fixed
ranged/one-worker, Auto-control/three-worker and fixed-potion/three-worker cases.
Missing or invalid evidence prevents activation.


### Broader fixed-option adoption timing results

All fourteen configurations passed complete logical parity and the recomputed
no-material-regression gate. There were 140 measured runs plus 28 warm-ups.
Reference is combined without the private fixed flag; candidate enables it.
These are normal service paths except the explicitly forced diagnostic row.

| Case | Workers | Reference median seconds | Candidate median seconds |
| --- | ---: | ---: | ---: |
| fixed_ranged | 1 | 6.863 | 5.359 |
| fixed_melee | 1 | 7.489 | 5.896 |
| fixed_magic | 1 | 15.612 | 14.451 |
| fixed_defence_roll | 1 | 7.364 | 5.794 |
| fixed_thorough | 1 | 10.850 | 9.330 |
| fixed_diagnostic | 1 | 12.231 | 10.788 |
| auto_control | 1 | 56.396 | 56.210 |
| auto_control | 3 | 24.997 | 25.054 |
| fixed_potions | 1 | 12.927 | 9.887 |
| fixed_potions | 3 | 6.524 | 5.222 |
| multi | 1 | 30.866 | 30.941 |
| configured_ranged | 1 | 8.990 | 8.883 |
| configured_auto | 3 | 28.779 | 28.165 |
| configured_potions | 3 | 8.919 | 8.894 |

Fixed ranged, melee, magic, defence-roll, Thorough, diagnostics and potion cases
established repeatable timing gains in this matrix. Auto/configured/Multi controls
exercise unchanged evaluation paths; their timing differences are not evidence
of fixed-path savings. Serial and three-worker Auto controls and fixed potions
must additionally retain identical complete fingerprints. Reported timings are
local observations on one frozen representative cohort, not universal guarantees.


### Fixed-option adoption decision

The strict selector returned `adopt: true` with no rejection reasons. It
recomputed all paired timing gates, checked every required configuration, and
required valid matching input/result identities for fresh-process memory evidence.
All fourteen archived inputs were independently replay-decoded and checked against
their recorded hashes and one common frozen cohort. Auto controls and fixed
potions retained exact serial/three-worker fingerprints for both modes (4/4).
No measurement batch was discarded or repeated to obtain this result.

Eighteen fresh-process memory measurements covered three runs per mode/case.
All had unique measurement identifiers, matching result/input identities,
113-482 samples and zero errors. Sampled process-tree peak medians (decimal MB):

| Case | Workers | Reference median MB | Candidate median MB |
| --- | ---: | ---: | ---: |
| fixed ranged | 1 | 332.091 | 323.604 |
| Auto control | 3 | 1330.192 | 1329.541 |
| fixed potions | 3 | 935.391 | 921.698 |

Each candidate median was below the largest matching reference peak. One Auto
candidate sample was higher, but the complete three-run median passed the
unchanged gate. Shared pages count per process; sampling can miss brief spikes.
These are working-set observations, not exact private-allocation costs.

**Decision: enable fixed-option reporting for desktop combined.** Desktop
creation injects the qualified private flag only when profile is combined.
Startup logs both the selected profile and effective fixed-option enabled/disabled
state. Baseline and lazy disable the extension; normal environment/YAML baseline
rollback remains available. Generic services and direct optimizer calls keep the
flag disabled unless explicitly opted in, retaining the old combined reference
for controlled reproduction. There is no public request/schema/profile addition.
Worker startup serial fallback preserves the qualified setting; execution failures
are not silently retried with another profile.

Private artifacts remain ignored under `.tmp/fixed-adoption/`: per-case
`inputs.json`, raw results, paired `report.json`, `memory.json`,
`serial-worker-parity.json`, `selection.json` and `validated-summary.json`.
Reproduction uses tracked `tools.accept_fixed_reporting` and the existing memory
sampler; ignored orchestration scripts are not tracked dependencies.
For example:

```powershell
.\.venv\Scripts\python.exe -m tools.accept_fixed_reporting --frozen .tmp/desktop-controlled/inputs.json --case fixed_ranged --workers 1 --pairs 5 --output .tmp/fixed-adoption/reproduction
```

The earlier user desktop acceptance applies to the previous combined behavior.
This extension has automated local acceptance; its live desktop restart and user
acceptance remain pending. No live process restart, private-config edit, commit,
push, Pi change, hosted CI or deployment is included.


Post-activation focused checks passed **186 tests**, including real spawned
workers, in-flight potion cancellation with abort/drain assertions followed by
baseline recovery, desktop profile injection, environment rollback, startup
serial fallback and startup logging. Execution-profile and fixed-reporting context
modules had 100% coverage; acceptance tooling 98% (99% combined). Ruff, focused
mypy across six source modules, whitespace checks and independent review passed.
The selector also rejects malformed/duplicated evidence and boolean values where
integer worker/pair counts are required. Only local Windows validation is claimed.


## Running-cost numeric/report investigation gate (2026-11-08)

The next bounded P1 task required fresh profiling before implementing compact
running-cost ranking. Two cProfile passes each replayed configured ranged and
fixed ranged from the existing full-catalog frozen adoption cohort. All four
explicitly enabled combined execution and fixed-option reporting, complete
secondary frontiers and the running-cost frontier. These are serial forced
diagnostics, not normal service latency measurements. Both requests use Fast
mode; account, catalog, prices and evaluation time stayed frozen. The older
profiling helper defaults to baseline, so these runs explicitly passed the
current desktop execution options instead.

The agreed gate required running-cost evaluation/report construction to rank
among the top five cumulative function costs in both passes before proceeding.

| Case | Pass | Profile wall seconds | Cost evaluator calls | Cost evaluator cumulative seconds | Cumulative rank |
| --- | ---: | ---: | ---: | ---: | ---: |
| Configured ranged | 1 | 37.874 | 63186 | 1.324 | 35 |
| Configured ranged | 2 | 38.753 | 63186 | 1.346 | 40 |
| Fixed ranged | 1 | 19.934 | 50995 | 1.011 | 31 |
| Fixed ranged | 2 | 20.098 | 50995 | 1.011 | 32 |

`evaluate_running_cost` failed the gate in every pass. `aggregate_cost` also
ranked below the threshold (68/70 configured, 54/56 fixed). The enclosing
`explore_running_costs` includes equipment search, combat scoring, retention and
publication; its high cumulative rank is not evidence that resource-report
construction itself dominates. Cumulative times overlap and must not be summed
or interpreted as achievable savings. Instrumented wall times are not a timing
comparison or a desktop speedup claim.

**Decision: defer the compact running-cost prototype.** Per the approved plan,
no numeric-cost implementation, experiment flag, API/default change or adoption
matrix follows a failed investigation gate. Search budgets and behavior remain
unchanged. P1 is still partial; this does not complete the phase.

The next investigation should focus on repeated combat scoring/option selection
and retention work under current combined execution. Configured pass 1 spent
18.807 cumulative seconds in `configured_winner` and 12.866 in
`evaluate_prepared_score`, versus 1.324 in the resource-cost evaluator. Fixed
pass 1 spent 6.527 in `retain` and 5.516 in `diverse`. These observations identify
where to investigate dependencies and avoidable work; they do not qualify a
cache, report deferral or search-policy change. Complete tradeoffs and independent
objective winners remain required.

Ignored local evidence is under `.tmp/running-cost-gate/`: the profiling and
verification scripts, four `.prof` files, per-pass JSON with ranked functions,
provenance and complete normalized-result fingerprints, and `summary.json`.
Frozen inputs remain under `.tmp/fixed-adoption/`. No live restart, private
configuration edit, commit, push, hosted CI or Pi deployment is included.

Both profiled passes for each case matched its unprofiled complete normalized
result fingerprint. Unprofiled full results are archived alongside the profiles.
Configured ranged fingerprint: `d648fa584c5852ffe12961a4d554fa543d5219016ab3c32eb30f5c08a468429c`;
fixed ranged: `194316821c7a049f23997faa4bd1e69233c83264b51605ddcc0b11fb6c58ca97`.
The four-pass gate summary and whitespace checks passed. Only documentation
changed in this task, so no optimizer test suite or timing/memory adoption matrix
was needed. Independent method review confirmed the explicit execution settings
and gate interpretation.


## Prepared equipment legality-summary experiment (2026-11-08)

Follow-up inspection found repeated physical-equipment scans in the configured
combat scorer. In configured ranged pass 1, `_evaluate_prepared` had 758,916 calls,
3.682 seconds self time and 14.808 cumulative seconds. A bounded opt-in prototype
prepared immutable ordered unsupported effects, occupied slots and shield presence
once per equipment state, then reused them only in lightweight scoring. All
role/attack legality and full reports retained their existing behavior. Metadata
was built only inside the experiment context; old prepared cache entries fell
back safely. The disabled path still carried optional metadata/context-check
overhead, so its comparison was not proof of zero default overhead.

The experiment compared current combined plus fixed reporting against that same
execution with the legality summary enabled. Both configured/fixed ranged cases
used the existing full-catalog frozen inputs with complete secondary and forced
running-cost frontiers, unchanged search budgets and serial execution. Each ran
one warm-up per mode and five alternating AB/BA pairs. All 24 archived raw results
(20 measured, four warm-ups) matched complete normalized reference fingerprints;
these also matched the preceding profiling gate. Independent replay hashing and
timing-decision recomputation are archived in `validated-summary.json`.

| Case | Reference median seconds | Candidate median seconds | Reference MAD seconds | Paired median gain seconds | Repeatable gain |
| --- | ---: | ---: | ---: | ---: | --- |
| Configured ranged | 18.3240 | 18.2417 | 0.1872 | 0.0952 | No |
| Fixed ranged | 11.0501 | 11.6921 | 0.0394 | -0.7099 | No |

**Decision: reject and remove the prototype.** Configured ranged did not establish
a gain beyond observed variation; fixed ranged regressed. No memory/adoption
matrix was warranted after the timing failure. Candidate code and tests were
archived under ignored `.tmp/structural-scoring/candidate/` before surgical
removal. No production experiment flag, schema, worker propagation or default
change remains. The existing combined implementation and other in-progress
changes were preserved. These observations are local, not general latency claims.

A separate observational exact-score reuse probe used ordered equipment IDs,
serialized role settings, frozen levels and the defence-inclusion flag as its key.
At capacity 65,536 it observed 363,333 hits in 702,072 configured scoring calls,
and 13,758 hits in 73,909 fixed scoring calls. Complete fingerprints matched.
This instrumented probe always called the original evaluator. Later key review
found that role serialization excludes resolved `active_prayer_ids`, so the
configured hit count conflated different prayer settings and is invalid evidence
of exact-input reuse. The corrected capacity/key/memory measurements below
supersede this probe. No score substitution or production change used that key.

Ignored evidence: `.tmp/structural-scoring/` contains paired reports, frozen
inputs, raw results, candidate snapshots and `validated-summary.json`;
`.tmp/scoring-reuse-probe/` contains the separate counting results. P1 remains
partial. No live restart, commit, push, hosted CI or deployment was performed.

Before removal, 39 candidate tests passed, including 14 complete fixture
comparisons across melee/ranged/magic, fixed/configured options, Fast/Thorough
and Multi controls. Structural-module coverage was 100% (96% with scoring);
Ruff and focused mypy passed. The candidate comparator passed 16 tests; after
removing its experiment mode, its original 14 tests still passed. Candidate
validation records are archived with its patch. Cleanup restored `scoring.py`
exactly and preserved all earlier numerical/reporting work in `combat.py`.
After cleanup, 87 focused incremental-scoring, combat-scoring and comparator
tests passed, with a clean whitespace check.

## Corrected bounded exact-score reuse investigation (2026-11-08)

Key review found `RoleConfig.active_prayer_ids` is declared `exclude=True` and
is absent from `model_dump_json()`. A conservative exact-score key must include
the resolved prayer IDs explicitly. The corrected observational probe uses:
ordered equipment IDs, serialized role settings plus resolved prayer IDs, sorted
level items (including base-level metadata), and the defence-inclusion flag.
Each run uses one frozen catalog and optimization. Role serialization is memoized
with retained object references in a separate bounded 1,024-entry LRU, preventing
object-ID reuse and unbounded memo growth. Objective winners remain independent.

The same full-catalog configured/fixed ranged inputs ran current combined plus
fixed reporting, serially, with complete secondary and forced running-cost
frontiers. The probe always called the original evaluator and simulated all five
LRU capacities without substituting results. Both complete normalized result
fingerprints matched the preceding profiling gate. Counts were:

| Capacity | Configured hits / 702,072 calls | Fixed hits / 73,909 calls | Configured retained Python MB | Fixed retained Python MB |
| ---: | ---: | ---: | ---: | ---: |
| 1,024 | 0 | 0 | 2.21 | 2.71 |
| 4,096 | 0 | 0 | 8.68 | 10.75 |
| 8,192 | 0 | 0 | 17.27 | 21.34 |
| 16,384 | 0 | 0 | 34.58 | 42.56 |
| 65,536 | 0 | 13,758 | 137.47 | 152.18 |

Memory values are partial object-size estimates in decimal MB from recursive
`sys.getsizeof`, deduplicating visited objects within each cache. The probe does
not traverse mapping-proxy contents, so these estimates undercount the complete
reachable graph. They include referenced key/score/bonus objects, some shared
with the optimizer, and are not incremental allocation, RSS, private bytes or an
allocator high-water mark. The separate role memo estimate was
97,010 bytes configured (54 serialization misses) and 5,020 bytes fixed (one
miss). The fixed 65,536-entry cache ended with 60,151 entries; other caches reached
their capacity. Simulating five caches together is instrumentation, not a
production memory measurement.

Instrumented key preparation totaled 2.162 seconds configured and 0.680 seconds
fixed; all fresh score evaluations totaled 9.261 and 0.734 seconds respectively.
The fixed repeated calls accounted for only 0.112 seconds of evaluator time at
the largest capacity. These are per-call instrumented observations, not paired
latency comparisons, additive end-to-end savings or a universal lower bound on
key cost. LRU lookup/eviction overhead is additional and not included in key time.

**Decision: reject this bounded whole-score LRU at the investigation gate.**
Configured scoring has no exact hits at any tested capacity; fixed scoring has
none through 16,384 entries and only modest reusable evaluator work at 65,536,
with a large reachable object graph. No production prototype, cache flag, timing
adoption matrix or sampled-process memory matrix is justified by these results.
This does not reject the already adopted narrower ranged numerical cache, which
keys only the numerical dependencies it reuses.

The next bounded P1 investigation should examine preparing invariant
attack/target/prayer constants, as originally proposed, rather than retaining
whole equipment scores. First attribute remaining `_evaluate_prepared` and
`_calculate` work under current combined execution to identify constants that
actually repeat outside the existing ranged numerical cache. Prototype only a
measured hotspot, retaining exact legality, rounding, tie behavior and independent
objective winners; qualify it with complete result parity and paired timings.
Search pools, beams and work budgets remain unchanged. P1 is still partial.

An ignored serial-only wrapper was tested independently before considering any
score substitution: 14 tests passed with 100% coverage of that helper. Tests
cover prayer identity, target/stance/levels/base-Magic/defence/order isolation,
unsupported scores, bounded eviction/memoization, verification of cached hits,
and exception cleanup. The wrapper was not used in the capacity probe or adopted
into production. Independent review recomputed both reference fingerprints from
archived complete raw results and checked the table against the probe reports.

Ignored evidence is under `.tmp/exact-score-cache/`: the corrected counting probe,
two JSON reports, research wrapper/tests and coverage report. The earlier probe
remains archived with its limitation documented above. Only this plan changed in
tracked files during this task; whitespace checks passed. No desktop restart,
private configuration change, commit, push, hosted CI or deployment was performed.

## Direct finalization of cached ranged scores (2026-11-08)

Review of all four current combined profiles found the remaining ranged work
was not repeated prayer arithmetic. In configured pass 1, prayer effects had
719,201 calls, only three cached-effect misses and 0.354 cumulative seconds;
raw player defence rolls had 56,527 calls and 0.435 cumulative seconds, all from
full reporting. The ranged numerical evaluator had only 11,881 misses in 718,765
calls. `_calculate` nevertheless spent 2.948 self seconds reconstructing some
values already present in its cached `Outgoing`, alongside dispatch and key
construction. Overlapping profile times do not predict achievable savings.

The prototype consumes the existing outgoing cap result, accuracy, expected
damage and adjusted attack speed directly for lightweight ranged scores. Original
equipment/attack legality runs first; optional player defence rolls still use
the original function. Rich reporting, numerical keys, search policies, budgets
and objective winners retain their behavior. There is no new cache or attack
context equivalence key. `ranged_score_finalization()` enables this path only
when an existing ranged numerical evaluation is available. It defaults off,
resets on nested exceptions, and has no desktop/worker/request integration.

### Controlled timings and disabled-path overhead

Both representative frozen full-catalog cases used combined plus fixed reporting,
complete secondary and forced running-cost frontiers, and serial execution.
Each ran one warm-up per mode and five alternating AB/BA pairs. The reference
calculator was compiled from the archived pre-edit function using unchanged
numerical globals. Independent AST review confirmed only a new import and opt-in
block differed. Thus candidate overhead was compared against the actual previous
implementation, rather than giving the reference the added context lookup.

| Case | Reference median seconds | Candidate median seconds | Reference MAD seconds | Paired median gain seconds | Paired MAD seconds | Repeatable gain |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Configured ranged | 18.4829 | 17.9766 | 0.3220 | 0.4729 | 0.3006 | Yes |
| Fixed ranged | 10.9087 | 10.7865 | 0.1000 | 0.0532 | 0.0353 | Yes |

Observed median improvements were approximately 2.7% and 1.1%. All 24 complete
raw results, including warm-ups, matched the preceding normalized fingerprints.
No batch was discarded or repeated to obtain a pass.

A separate configured-case control, chosen for its highest scoring-call count,
compared the pre-edit function with the candidate context disabled: one warm-up
per mode and five AB/BA pairs. Reference median was 17.9450 seconds versus
18.0201 disabled, an observed 0.0751-second slowdown. Removing the added check
did not meet the predeclared repeatable-gain gate: paired MAD was 0.1775 seconds.
All 12 raw control results matched. This is not proof of zero default overhead;
the limitation remains for broader adoption review.

### Separate fresh-process memory and decision

Three fresh processes per mode/case produced 12 unique measurements with matching
result fingerprints and frozen provenance. Memory sampling ran separately from
latency. The unchanged retention gate requires the candidate median sampled
working-set peak to be no higher than the largest matching reference peak.

| Case | Reference median MB | Candidate median MB | Reference maximum MB | Gate |
| --- | ---: | ---: | ---: | --- |
| Configured ranged | 359.035 | 356.798 | 359.977 | Pass |
| Fixed ranged | 348.344 | 349.065 | 349.217 | Pass |

One configured candidate peak exceeded every reference peak, and the fixed
candidate median was slightly higher than the reference median; the complete
three-run medians passed the stated gate. These are sampled process-tree working
sets, not exact private allocations or proof that memory decreased. These runs
had only 5-7 samples each with zero errors, so the observations are coarse.
Sampling can miss brief spikes and counts shared pages per process; broader
adoption should revisit sampling density.

**Decision: retain direct ranged score finalization as an opt-in experiment.**
Do not enable it in desktop combined yet. Broader execution/profile, worker,
cancellation and rollback acceptance remains separate. The fixed-option
extension's live desktop acceptance also remains pending. This is local Windows
serial evidence on two representative cases, not an exact unspecified user
request replay, hosted CI or deployment evidence.

TDD first failed for the missing context module, then 401 focused checks passed,
including 363 new tests and the existing combat-scoring tests. Cases cover
stances, signed armour, three attack patterns, prayer/level/defence variants,
ammunition and defence subtypes, exact cap boundaries, zero max hit, unsupported
legality, full-report equality, nested cleanup, and 12 complete melee/ranged/magic
fixed/configured Fast/Thorough fixture comparisons. Context-module coverage was
100%; Ruff and focused mypy passed.

The tracked comparator adds `--experiment ranged-score-finalization`; both sides
use combined plus fixed reporting, while only the candidate enables finalization.
Its reference is **current source with the context disabled**, explicitly recorded
in report metadata, rather than the archived pre-edit function used above.
Ambient experiment contexts are rejected. All 23 comparator tests passed (98%
tool coverage), including CLI, options, parity failure and context cleanup.
Ruff, focused mypy and whitespace checks passed. Independent final review
verified all 36 archived complete-result fingerprints, pair-to-measurement
records, timing decisions and memory interpretation with no blockers.
Example local reproduction:

```powershell
.\.venv\Scripts\python.exe -m tools.compare_gear_desktop --frozen .tmp/fixed-adoption/configured_ranged-1/inputs.json --experiment ranged-score-finalization --diagnostic --pairs 5 --output .tmp/ranged-score-reproduction
```

Ignored evidence under `.tmp/ranged-score-finalization/` includes source snapshots,
four-profile attribution, raw results, paired reports, disabled-path control,
fresh-process memory observations and recomputed `validated-summary.json`. No
desktop restart, private configuration change, commit, push, hosted CI or
deployment was performed.

## Bounded P1 closeout proposal (superseded)

At the time of this proposal, the adopted P1 increment covered ranged numerical
reuse and configured/fixed lazy partial reporting. The benchmark/probe foundation
and desktop combined integration were delivered. Direct ranged finalization was
still experimental. These P1 limitations are resolved by the final acceptance below.

Original P1 scope was broader: invariant attack/target/prayer preparation for
melee/magic, lazy combat-variant reporting and compact running-cost ranking were
then incomplete. Melee/magic benefited from lazy reporting but lacked numerical
factorization. Frontier combat variants still built rich performance and installed
exact attack/prayer overrides before solution construction; these values participate
in full-result ties and IDs. `CostSearch` still retained full reporting.

The following proposed bounded closeout was superseded by the user's request to
implement all of original P1; it is retained as decision history:

1. Resolve the ranged finalization experiment's broader adoption decision using
   explicit parity, timing, memory and execution gates. Opt-in retention is not
   desktop acceptance.
2. Audit configured melee/magic and combat-variant reporting once. Prototype at
   most one materially justified hotspot, preserving exact variant overrides,
   eligibility, arithmetic and result ties. Keep compact running-cost reporting
   deferred unless new evidence overturns its failed profiling gate.
3. Record adopted, rejected and deferred P1 scope, complete appropriate final
   acceptance, and move to P3 compact states with targeted P2 sharing. Closing
   this increment must not mark all original P1 proposals complete. Live
   fixed-option desktop acceptance remains a separate user-observed check.

## Full original P1 implementation

The user explicitly selected completion of **original P1**, not P2-P6. Prepared
attack/target/prayer constants, lazy frontier combat variants, and compact numeric
running-cost ranking are required deliverables. The earlier profiling gate remains
useful evidence about expected benefit; it no longer removes running-cost work
from implementation scope.

The integrated implementation uses immutable prepared numerical/resource records,
compact score ranking and deferred exact report/tie construction. Existing legal
attack checks, independent objective winners, search budgets, arithmetic order,
unknown prices, exact physical equipment identities, attack/prayer overrides and
public result IDs must remain unchanged. A private execution flag preserves the
previous combined implementation as a controlled reference and crosses serial,
Auto and potion worker paths explicitly.

Acceptance requires complete normalized result parity across the representative
desktop matrix, no material regression in every case, a repeatable gain in at
least one configured/fixed combat or diagnostic case, separate fresh-process
memory measurements, and worker cancellation/recovery and baseline rollback.
Retained experimental code alone does not satisfy original P1 completion.

The first full-catalog acceptance attempt exposed an inert-ammunition refinement
regression: exact resource-report equality was comparing a published report with
a compact cost projection. The comparison now materializes the report at that
semantic boundary, and new refinement candidates are materialized before archive
publication and ID generation. A reduced failing regression and the complete
fixed-magic replay verify the correction. Configured magic, forced diagnostics,
Multi and three-worker Auto also passed complete full-catalog screening.

The second timing attempt failed the unchanged fixed-melee nonregression gate
(5.896 seconds reference versus 6.036 seconds candidate). It was stopped to reduce
preparation lookup overhead; it is not an accepted result. Failed and interrupted
attempts remain under `.tmp/full-p1/acceptance-v1` and `acceptance-v2`.

The third attempt fixed the preparation overhead and passed the Single/Auto
comparisons, but Multi failed the unchanged timing gate (31.905 seconds reference
versus 33.135 seconds candidate). Separate profiling identified repeated compact
candidate identity construction during equality checks: 456,837 identity calls,
and every one of 4,016 deferred variants eventually materialized. This result is
retained as a failed revision under `.tmp/full-p1/acceptance-v3`; it is not evidence
of accepted Multi performance. The corrected implementation caches immutable
candidate descriptors, checks cheap differences before exact report equality,
and extends compact partial ranking to Multi. The memory matrix consequently
also requires three fresh-process runs per mode for Multi.

Focused Multi parity tests additionally exposed a special-role option distinction:
the original frontier override reports an empty option object where an untouched
seed can contain null. Compact projections must preserve that normalization before
deduplication, as well as preserving the eventual full report and result ID.

The full P1 implementation consists of:

- `prepared_combat.py`: bounded, execution-scoped immutable attack, target, prayer
  and defensive constants for melee, ranged and magic. Owned level snapshots are
  frozen after potion boosts; unsupported legality remains on the original path.
- Numeric configured/fixed scoring in `optimizer.py`: partial Single and Multi
  states, baseline scaffolds and candidate marginals defer rich reports. Physical
  item assignments, weighted roles, independent objective selection and search
  budgets retain their original meaning.
- `variant_reporting.py`: exact attack/prayer descriptors, lazy full-report ties
  and equality, and explicit materialization before final archive IDs. Special
  role overrides and cancellation use the same semantics as the reference.
- `compact_costs.py` and `running_frontier.py`: immutable resource recipes and
  numeric costs for ranking, with complete descriptions, charging alternatives,
  price provenance and unknowns expanded when results require them.
- `execution_profile.py`, service and worker dispatch: a private full-P1 flag
  creates fresh contexts per concrete branch, including direct ranged score
  finalization. The preceding combined implementation remains the acceptance
  reference; baseline remains the desktop rollback profile.

Complete full-catalog screening of configured magic, forced diagnostics, Multi
and three-worker configured Auto passed after these corrections. The
fourth acceptance attempt is under `.tmp/full-p1/acceptance-v4`; source hashes
were recorded before timing. Multi improved from 31.439 to 28.851 seconds with
exact parity and a repeatable gain. Fixed ranged passed, but fixed melee narrowly
missed the strict nonregression threshold (6.027 seconds versus 5.987 seconds;
reference MAD 0.026 seconds). The attempt was stopped for a further prepared-context
lookup optimization. None of these failed revisions counts as final adoption.

The fifth attempt qualified eleven timing configurations, including Multi,
fixed magic, defence-roll ranking, Thorough, forced diagnostics, Auto and potion
branches. Configured ranged then failed with a repeatable 3.1% slowdown (11.661
seconds candidate versus 11.313 seconds reference). Profiling identified 417,293
prepared-attack lookups even though the existing ranged numerical cache supplied
the outgoing calculations. The revision is retained under
`.tmp/full-p1/acceptance-v5`; its passing subsets do not make it an adopted revision.

The sixth revision removed redundant prepared-attack lookups for lightweight
ranged scores already supplied by the existing ranged numerical cache. All 17
timing configurations passed their unchanged gates, with exact parity across 224
warm-up/timed results. Thirty separate fresh-process memory measurements then
rejected this revision: configured ranged's candidate median was 315.51 MiB
against a 300.01 MiB reference maximum; configured potion workers were 902.64 MiB
against 881.15 MiB. Magic, Auto workers and Multi passed their memory gates. This
is a memory failure, despite successful timing, and does not qualify for adoption.

Inspection found avoidable deferred-report lifetimes: a candidate-owned tie key
formed a reference cycle, resolved tie strings remained attached to candidates,
completed report factories still captured searches and seed trees, and cost
factories captured complete searches instead of their immutable resource records.
The next revision addresses these lifetimes and screens memory before repeating
timing. Source bytes matching the sixth revision's hashes and all its raw evidence
are preserved under `.tmp/full-p1/acceptance-v6/`.

The seventh revision removed those cycles and unnecessary factory captures.
Five weak-reference/retry tests first failed and then passed; 542 focused
integration tests and 495 cost-focused tests passed, with 96% coverage of the
variant module. A memory-first ranged probe reduced the candidate median peak to
301.58 MiB, but still exceeded the 299.86 MiB reference maximum. The full matrix
was therefore not restarted. An instrumented recipe-cache count found only 62
retained recipes and about 72 KiB of cache structures and copied price-map storage;
recipe-key changes cannot explain or remove the remaining gap. The next check
measures the allocation overhead of the deferred-report objects themselves.

That allocation observation found only about 78 KiB of potential peak savings
from slots, so no slots change was made. A prepared-context lifetime observation
then identified the remaining retention: 1,352 cached role objects occupied about
1.63 MiB of shallow model/dictionary/field-set storage, and 1,268 of them (about
1.53 MiB) had no persistent owner besides the cache. Their otherwise obsolete
search configurations survived until the entire evaluation context ended. The
next revision uses validated weak role references, retaining one strong owner for
the most-recent-context fast path. Dead identity entries must be discarded without
creating a callback/context cycle or allowing an object-ID reuse hit.

The eighth revision passed all thirty fresh-process memory measurements: candidate
median peaks for configured ranged, magic, Auto, potions and Multi were 299.45,
334.42, 1,162.93, 871.05 and 443.03 MiB, respectively, below their matching
reference maxima. Configured ranged also passed timing. Configured melee then
failed the unchanged timing gate (10.746 seconds candidate versus 10.540 seconds
reference; reference MAD 0.081 seconds). Its paired slowdown exceeded the
predeclared noise allowance, so no conditional extension was used. The revision
remains unaccepted, with exact measured source bytes preserved under
`.tmp/full-p1/acceptance-v8/measured-source/`.

The follow-up profile found only 1,254 prepared-record builds and 1,123 weak-role
cleanup callbacks; those cold operations were too small to explain the slowdown.
The next change targets repeated ordinary single-attack score finalization,
preserving the original arithmetic while avoiding generic report-path scaffolding.

### Final P1 acceptance revision (2026-11-09)

The ninth revision finalizes prepared ordinary single-attack scores directly,
preserving the one-term sum's initial zero, damage-cap ordering, signed armour,
Sanguinesti addition order and defensive rolls. Double attacks and full reports
retain their general calculation path. Plain-dictionary variant equality now
rejects differing DPS/secondary values before allocating the remaining comparison
fields; genuine ties still use exact full reports. Focused RED/GREEN tests passed
for both changes, followed by 720 combat/integration checks and 109 variant/Multi
checks. Exact serialized cost-report comparisons passed all 438 cost tests.

All 17 frozen full-catalog timing configurations passed the unchanged
nonregression gate. Every one of 224 warm-up/timed outputs retained its complete
normalized result digest. Reference is the preceding combined profile with
fixed-option reporting; candidate additionally enables all original P1 work.
The frozen catalog contains 5,435 items. Measurements used Windows, Python
3.12.10, branch HEAD `6c1fbec` plus the source bytes recorded in
`.tmp/full-p1/acceptance-v9/source-hashes.json`. They describe this local desktop
cohort, not a universal speedup or hosted CI result.

| Case | Workers | Reference median (s) | Full P1 median (s) | Median reduction | Repeatable gain |
| --- | ---: | ---: | ---: | ---: | --- |
| Auto control | 1 | 58.538 | 46.473 | 20.6% | Yes |
| Auto control | 3 | 26.749 | 19.486 | 27.2% | Yes |
| Configured Auto | 3 | 30.426 | 23.042 | 24.3% | Yes |
| Configured forced frontiers | 1 | 18.699 | 16.725 | 10.6% | Yes |
| Configured magic | 1 | 28.027 | 20.968 | 25.2% | Yes |
| Configured melee | 1 | 10.019 | 10.015 | 0.0% | No |
| Configured potion search | 3 | 9.613 | 9.291 | 3.3% | Yes |
| Configured ranged | 1 | 9.457 | 9.345 | 1.2% | Yes |
| Fixed defence-roll objective | 1 | 5.984 | 5.878 | 1.8% | Yes |
| Fixed forced frontiers | 1 | 10.948 | 9.130 | 16.6% | Yes |
| Fixed magic | 1 | 14.563 | 10.864 | 25.4% | Yes |
| Fixed melee | 1 | 5.981 | 5.909 | 1.2% | Yes |
| Fixed potion control | 1 | 10.214 | 10.190 | 0.2% | No |
| Fixed potion control | 3 | 5.464 | 5.359 | 1.9% | No |
| Fixed ranged | 1 | 5.472 | 5.423 | 0.9% | Yes |
| Fixed Thorough | 1 | 9.794 | 9.491 | 3.1% | Yes |
| Multi | 1 | 31.279 | 28.206 | 9.8% | Yes |

Each configuration used five alternating AB/BA pairs after one warm-up per mode,
except fixed potion workers, which used fifteen pairs declared before timing.
No conditional extension was needed and no observations were discarded. The
gate requires candidate median at most reference median plus reference MAD;
the separate repeatable-gain test also considers paired variability. Small
positive median differences marked "No" are not demonstrated speedups.

Thirty separate fresh-process memory observations also passed, with three runs
per mode/case. These are sampled peak process-tree working sets, including worker
descendants, not exact allocation high-water marks. Sampling produced 4-784 samples
per observation; the lowest-density measurements are coarse. The memory gate requires the
candidate median to be no greater than the corresponding reference maximum.

| Case | Workers | Reference maximum (MiB) | Full P1 median (MiB) |
| --- | ---: | ---: | ---: |
| Configured ranged | 1 | 300.38 | 299.07 |
| Configured magic | 1 | 383.70 | 327.14 |
| Configured Auto | 3 | 1,285.96 | 1,161.68 |
| Configured potion search | 3 | 881.30 | 870.68 |
| Multi | 1 | 486.24 | 442.80 |

Serial/three-worker parity passed for configured Auto and potion search in both
reference and candidate modes (four comparison records, eight complete outputs).
The acceptance selector returned `adopt: true` with no rejection reasons. An
independent audit recomputed every result fingerprint, input/cohort identity and
gate, verified all 50 measured source files, and confirmed that all 1,789 evidence
files from revisions 1-8 remained unchanged. The accepted source snapshot and
`validated-summary.json` are under
`.tmp/full-p1/acceptance-v9/independent-audit/`.

The desktop factory now enables full P1 only for `combined` and logs its activation.
`baseline` and `lazy` leave full P1 disabled; worker startup fallback preserves the
selected profile. Generic services, direct calls and Pi defaults remain baseline.
The only production change after the audited source snapshot is desktop factory
activation/logging; numerical code is identical to the measured revision.

Final verification:

- 781 focused numerical/variant/cost/integration tests passed. New-module coverage:
  prepared combat 100%, compact costs 100%, variants 96% (99% combined).
- 48 desktop factory, dispatch, HTTP, cancellation/recovery and rollback tests
  passed. The HTTP fixture calls the actual factory without candidate injection.
- The Chrome browser regression passed and published a result without JavaScript
  errors. Ruff passed for every changed/new Python file; mypy passed for 50 source
  files; the final whitespace check passed.
- An isolated real desktop app used the existing private read-only connection
  settings and three-worker configuration for a fixed ranged, prayers-off scenario.
  Automated Chrome interaction exercised `combined` -> `baseline` -> `combined`;
  each request returned HTTP 200, a selected solution and the rendered result with
  no JavaScript errors. The final screenshot was inspected. This completes the live
  fixed-option check and full-P1 rollback/re-enable check. It is automated local
  browser evidence, not a claim of manual user input or restarting the existing app.

Original P1 is complete, including the broader ranged-finalization adoption
decision and running-cost work previously proposed for deferral. P2-P6 are outside
the requested P1 scope. No private config was edited, existing desktop process
restarted, commit/push made, or hosted CI/deployment claimed. A normal desktop
restart loads the adopted code.

Raw timing, memory and worker evidence remains ignored under
`.tmp/full-p1/acceptance-v9/`; live outputs/screenshots are under
`.tmp/full-p1/live-desktop/`. Example reproduction with the local frozen input:

```powershell
.\.venv\Scripts\python.exe -m tools.accept_factored_evaluation --frozen .tmp/desktop-controlled/inputs.json --case configured_magic --pairs 5 --output .tmp/p1-reproduction/magic
.\.venv\Scripts\python.exe -m tools.accept_factored_evaluation --frozen .tmp/desktop-controlled/inputs.json --case configured_auto --workers 3 --worker-parity --output .tmp/p1-reproduction/workers
.\.venv\Scripts\python.exe -m tools.accept_factored_evaluation --frozen .tmp/desktop-controlled/inputs.json --case multi --memory-mode candidate --output .tmp/p1-reproduction/memory-multi
```

The memory command launches a fresh interpreter; repeat separately for both modes
three times per required memory case when reproducing the full acceptance gate.
