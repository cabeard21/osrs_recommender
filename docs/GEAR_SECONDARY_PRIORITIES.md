# Gear Optimizer tradeoff metrics

## Composable objectives

New browser runs use an `objectives` list. DPS is always included. Quick select
offers five defence rolls, Prayer bonus, Melee/Ranged strength, Magic damage,
Accuracy, Running cost (GP per damage), and Wilderness loss if PK’d (GP) for
Wilderness scenarios. Defence selections can improve their minimum or mean together,
or remain independent. The expanded editor supports multiple defence groups.
Browser-local objective presets are separate from saved gear setups.

A defence descriptor looks like
`{"kind":"defence_roll","styles":["stab","ranged"],"aggregation":"minimum"}`.
Other descriptors contain only their kind, such as `{"kind":"prayer_bonus"}`.
Style order, duplicates, and singleton minimum/mean equivalence are canonicalized.
There are 64 distinct secondary functions. Empty objectives means DPS only.
Explicit objectives conflict with a nondefault `secondary_priority`. Historical
scalar requests and results retain their original meanings.

Each group is reduced within each role before Multi applies normalized active-time
weights. Wilderness loss counts the whole carried setup, including utility switches.
Dominance compares unrounded DPS and every objective. A point dominates another
when it is at least as good on every dimension and strictly better on one.
Lower GP/damage and lower Wilderness loss are better. Combat objectives favor higher values.
Multi divides weighted spend per second by weighted DPS to calculate GP/damage.
Equal vectors keep one representative using existing resource and identity ties.
Objective order is not an importance ranking. Search normalization only spreads
candidates; it does not change objective values or dominance.

Additional frontier work scales with distinct secondary functions: 500,000
expansions per objective in Fast and 1,500,000 in Thorough, within each concrete
discipline/potion branch. These remain bounded best-found searches. More objectives
can substantially increase runtime and archive size. Complete archives merge
before final presentation filtering.

All retained tradeoffs are browsable through paginated session-result endpoints.
The chart uses a separate representative sample. A point can appear dominated on
two plotted axes while remaining useful across other objectives. Changing axes
does not change the objective configuration or selected setup.

Archives are session-only, separate from the account database, and may spill to
temporary local SQLite files. Restart expires result references; the UI offers
rerunning. The scalar metrics below remain supported for compatibility.

### Running cost fixture

On Windows, the frozen two-staff, two-spell Magic regression fixture took a median
7.8 ms with an empty objective list and 13.4 ms with GP/damage selected. Each
measurement used one warmup followed by five serial Python runs. Both selected
2.519969 DPS. The cost run retained two alternatives, using Fire Blast and Wind
Strike. These timings cover this small fixture only.

### Desktop single-roll regression check, 2026-11-16

The supplied draft-only `temp.txt` used Animated Black Armour, usable gear with a
10m budget, stab defence roll, accurate melee attacks, and optimized Defence and
Combat potions. Its combat-option exclusions resolve to accurate stab/slash/crush
using the frozen account capabilities; treating it as fixed slash is narrower.
Because the dump contains no submitted account snapshot, these measurements use
one newly frozen account/price snapshot and the same 5,435-item catalog in both
implementations. They do not establish the timing of the historical user run.

| Implementation | Optimize seconds | Points per equivalent Single cap | Native requests / fallbacks |
| --- | ---: | ---: | ---: |
| Main `b8f8c481`, scalar stab-roll request | 14.975 | 7 | 8 / 0 |
| Vector path after numeric/native fixes, before transaction batching | 32.069 | 13 | 8 / 0 |
| Vector path with bounded transactions | 21.640 | 13 | 8 / 0 |

These are individual Windows desktop observations with six workers and four
potion branches; worker startup is excluded. Main was compiled in an isolated
source snapshot. Only NPC selection revision metadata was cleared for main's
different NPC catalog revision; identical frozen target combat stats were asserted.
The remaining 6.7-second gap to main is real in this comparison; a 10-second
runtime has not been demonstrated.

The fixes preserve work budgets and complete results: native exact farthest-point
retention and partial expansion, numeric projection reuse, deferred rich reports,
duplicate Single-archive elimination, native fixed scoring, and bounded SQLite
transactions for disposable search archives. Account databases are unchanged.
The corrected context-aware replay matches the original vector implementation's
complete solution digest, all 13 points per group, selected setup and curve.
The original-code parity replay disabled only temporary SQLite synchronization
to avoid disk-flush delays; its time is not a pre-fix latency measurement.
Private inputs, reference source copies, profiles and reports are under ignored
`.tmp/stab-performance/`. Profiling is separate from latency observations.

## Legacy scalar metric compatibility

Historical configurations offer a **Tradeoff metric** alongside DPS: nineteen player defensive-roll metrics, Prayer bonus, Melee/Ranged strength, Magic damage bonus, and Accuracy. **None — DPS only** retains the ordinary DPS search. Existing API identifiers (`secondary_priority`, `secondary_value`, `secondary_frontiers`) remain compatible.

The seven equipment-bonus defence metrics are no longer selectable in the UI. Stored Single/Multi drafts and named setups using them migrate to the matching roll metric (for example, `slash_defence` becomes `slash_defence_roll`), preserving all other settings. Run optimization again to measure the new metric. Historical results retain their original labels and values, and backend API callers can still request the old identifiers with their original meanings: Magic & ranged defence takes the lower equipment bonus, Balanced defence averages all five bonuses, and individual metrics use the named bonus. Negative equipment bonuses remain negative.

## Player defensive rolls

The selectable defensive metrics are Balanced defence roll, Melee defence roll, Melee & magic defence roll, Melee & ranged defence roll, Magic & ranged defence roll, individual Stab/Slash/Crush/Ranged/Magic defence rolls, and each individual melee style combined with magic, ranged, or both.

| Metric identifier | Value within each complete loadout |
| --- | --- |
| `melee_defence_roll` | Minimum of stab, slash, and crush rolls |
| `melee_magic_defence_roll` | Minimum of stab, slash, crush, and magic rolls |
| `melee_ranged_defence_roll` | Minimum of stab, slash, crush, and ranged rolls |
| `stab_magic_defence_roll` | Minimum of stab, magic rolls |
| `stab_ranged_defence_roll` | Minimum of stab, ranged rolls |
| `stab_magic_ranged_defence_roll` | Minimum of stab, magic, ranged rolls |
| `slash_magic_defence_roll` | Minimum of slash, magic rolls |
| `slash_ranged_defence_roll` | Minimum of slash, ranged rolls |
| `slash_magic_ranged_defence_roll` | Minimum of slash, magic, ranged rolls |
| `crush_magic_defence_roll` | Minimum of crush, magic rolls |
| `crush_ranged_defence_roll` | Minimum of crush, ranged rolls |
| `crush_magic_ranged_defence_roll` | Minimum of crush, magic, ranged rolls |

These combined metrics improve the weakest included roll. Each individual melee style can be combined with magic, ranged, or both. All require a known Defence level; combinations including magic also require Magic. Missing unrelated levels do not prevent defensive scoring. Each role takes its minimum before Multi applies active-time weights.

Rolls use freshly boosted Defence and Magic levels, selected stat-prayer modifiers, complete equipment defence bonuses and the selected legal combat stance. Defensive and longrange stances add 3 effective levels; controlled adds 1. Physical effective defence is `floor(Defence * prayer_defence_multiplier) + stance + 8`. Magic effective defence is `floor(7 * floor(Magic * prayer_magic_defence_multiplier) / 10) + floor(3 * floor(Defence * prayer_defence_multiplier) / 10) + stance + 8`, with the contributions truncated separately. Each usable roll is `max(0, effective_defence * (equipment_defence_bonus + 64))`. These rules follow the [OSRS Wiki calculator player-defence implementation](https://github.com/weirdgloop/osrs-dps-calc/blob/main/src/lib/NPCVsPlayerCalc.ts).

The UI displays all roll values in thousands with two decimal places (for example, `12.34k`). Frontier roll gains show both the absolute increase and the percentage increase relative to the highest-DPS point in the same swap-limit group, using unrounded values. A zero baseline shows percentage unavailable. These percentages describe roll increases, not damage reduction.

Balanced averages the five rolls. Magic & ranged takes the lower of those two rolls within each complete role loadout, before Multi applies normalized active-time weights. Individual metrics use the corresponding roll. Utility roles remain unscored. Required unknown levels make the requested roll metric unavailable rather than being treated as zero.

Potion search retains Defence boosts for roll metrics and Magic boosts when magic defence contributes, even for melee or ranged outgoing attacks. Fixed combat settings and legal-option filters are respected. Larger rolls resist ordinary attack accuracy; they are not damage reduction or survival percentages. Stat prayers are assumed active. No incoming enemy attacks, protection prayers, prayer drain, boost decay, drinking downtime, supply endurance or encounter survival are simulated. Divine potion HP costs remain separate disclosures.

New results expose optional `player_defence_rolls` alongside combat performance; the existing singular `defence_roll` continues to describe the enemy defence used for outgoing accuracy. Historical results without player rolls remain readable and require a fresh optimization to measure a new roll metric.

## Best-found tradeoff frontiers

Named metrics produce nondominated DPS/metric alternatives for every swap limit and unrestricted results. Both objectives must be at least as high, with one strictly higher, for dominance. Comparisons use unrounded values and existing resource/identity tie-breakers. Highest DPS favors metric on equal damage; highest metric favors DPS on equal metric.

The ordinary DPS search is preserved. A separate metric-first lane reserves one quarter of frontier equipment expansions, alongside diverse exploration for intermediate alternatives. Metric lane candidates and beams retain complementary defence components. Existing shared-assignment, combat-option and refinement allowances remain bounded. Search diagnostics report lane work and exhaustion. Neither endpoints nor intermediate points are guaranteed global optima.

The browser submits `max_dps_loss_pct=100` for new runs, including restored drafts, and has no DPS-loss input. Existing API callers may still explicitly supply finite caps from 0 to 100 (default 10); historical responses retain their original caps. New browser requests also expose full running-cost and ammunition-comparison ranges. Changing the metric requires a fresh optimization.

Charts plot actual DPS against the metric. Highest DPS is initially selected; both endpoint buttons select complete solutions, including equipment, combat options, purchases, potions and joint transitions. A single point can represent both endpoints. DPS loss and metric gain remain explanatory table values; a zero baseline has no defined percentage loss. Sampled published groups contain at most 64 points and preserve endpoints.

Auto discipline and potion orchestration merge complete child archives before final sampling. IDs remain unique and swap-cap scoped. The `tradeoff-frontier-v2` policy and `metric_lane_equipment_fraction=0.25` participate in provenance and scenario fingerprints. Old capped results remain historical and require rerunning to obtain the expanded range.

Manual comparisons preserve selected combat options and validate equipment, budget, eligibility, inventory, locks and transitions through the existing evaluator.

## Frozen local benchmark evidence

Measured on Windows on 2026-10-28 with `tools.gear_search_quality_fixture.load_case`,
using the redacted `gear_search_quality_account.json` fixture, its frozen account,
catalog, prices and time. Each row is one run, with Python `tracemalloc` enabled.
Times include allocation tracing overhead and are not production latency estimates;
peak MiB is traced Python allocation memory, not process RSS. No Pi acceptance or
live deployment is implied. Default selects no secondary; Fast/Thorough select
balanced defence with the default 10% DPS-loss range. These comparisons include the
existing secondary ordering as well as the new frontier phase.

| Case | Mode | Seconds | Peak MiB | Highest DPS | Returned points | Added expansions | Frontier assignments |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| owned_slash | Default | 3.052 | 15.08 | 2.642031 | 0 | 0 | 0 |
| owned_slash | Fast | 11.618 | 26.66 | 2.670866 | 30 | 18,086 / 100,000 | 0 |
| owned_slash | Thorough | 24.710 | 31.72 | 2.670866 | 60 | 18,086 / 300,000 | 2,000 / 2,000 |
| joint_four | Default | 20.884 | 37.97 | 2.710306 | 0 | 0 | 0 |
| joint_four | Fast | 33.024 | 53.87 | 2.765004 | 9 | 43,257 / 100,000 | 0 |
| joint_four | Thorough | 56.583 | 60.15 | 2.785961 | 28 | 43,257 / 300,000 | 2,000 / 2,000 |

Returned point counts sum all swap-limit groups plus unrestricted and can include
repeated equipment across groups. Neither Fast run exhausted its extra expansion
budget; both Thorough runs exhausted the separate frontier substitution budget.
The highest-DPS incumbent was preserved or improved in these cases. This is focused
local evidence, not proof of global frontier completeness or a general latency SLA.

Focused backend verification: 71 tests passed across frontier, secondary priorities,
optimizer and exact evaluation. Changed frontier/evaluation modules reached 94.80%
combined coverage (frontier 96%, evaluation 93%) under an 80% gate. The tests include
omitted defensive candidates, joint swap feasibility, stance tradeoffs, shared
Thorough work limits and legal-option enforcement in manual comparisons.

## Objective-builder desktop measurements

The objective-scaling harness is `python -m tools.benchmark_objectives`. It uses
the redacted `gear_search_quality_account.json` fixture's `melee_1m` request,
frozen 119-item catalog, account snapshot, prices, and time. This is a substitute
regression account, not a replay of a live account. Each case runs in a fresh
process with the combined execution profile and native scoring enabled. Raw
reports under ignored `.tmp/objective-benchmarks/` include input and source hashes,
the actual work policy, complete solution digests, and native execution evidence.

Windows desktop observations on 2026-11-16, one run per row:

| Canonical secondary objectives | Search seconds | Complete points per swap group | Native fallbacks | Instrumentation | Source hashes stable during run |
| ---: | ---: | ---: | ---: | --- | --- |
| 1 | 17.381 | 6 | 0 | None | Yes |
| 3 | 43.863 | 185 | 0 | None | Yes |
| 8 | 85.207 | 626 | 0 | None | No |
| 62 | 527.886 | 1,235 | 0 | RSS sampling | No |

The three-objective case independently maximizes slash, ranged, and magic player
defence rolls alongside DPS. Its 185 points per group exceed the 128-point chart
sample, so chart points cannot substitute for the complete paginated archive.
Counts repeat across Single's equivalent swap caps; they are not distinct
additional configurations in each cap. These observations are not a latency SLA
or evidence of a globally exhaustive search. Other development checks may have
been active on the desktop.

Memory was sampled in a separate one-objective run: peak process-tree working
set was 123,928,576 bytes (118.19 MiB), across 159 samples with no failures. Source
hashes stayed stable. This Windows sampling can miss short peaks and counts
shared pages in every process; it is not Python allocation tracing or an OS
high-water measurement. Its 19.808-second search included memory instrumentation
and is not part of the latency table.

The full 62-objective run completed before its 600-second benchmark cancellation
deadline. Search took 527.886 seconds; completion plus complete-archive digesting
took 533.886 seconds. Its sampled peak working set was 151,195,648 bytes
(144.19 MiB), across 2,038 samples with no sampling failures. All 1,235 discovered
nondominated configurations per equivalent Single swap group were retained;
the extra groups repeat those configurations rather than multiplying the unique
set. This run covered all 62 distinct canonical secondary functions alongside DPS,
with one native request and zero fallbacks. The 600-second deadline belongs to
the benchmark harness, not a product runtime limit.

Source hashes changed during the eight- and 62-objective measurements while
progress and temporary-archive lifecycle handling were finalized. Their raw
reports record the before/after hashes; these rows are development observations,
not immutable final-build performance comparisons. The 62-objective time includes
RSS instrumentation and must not be compared directly with uninstrumented rows.
The final one-objective smoke run used stable final source hashes, completed in
17.381 seconds, and reproduced the earlier complete solution digest exactly.

Focused parity tests compare every complete archived solution, selected solution,
and curve point between Python and native execution for Single, Multi, and Auto,
both with and without optimized defensive/magic potions. All six cases match
exact solution digests with zero native fallbacks. Additional merge tests cover
finite DPS-loss caps applied after global merging, per-cap feasibility, nested
Auto/potion archives larger than chart samples, and worker archive ownership.
