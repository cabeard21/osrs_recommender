# Gear Optimizer Search Quality Correction

## Decision and scope

This correction is a Python-only, opt-in refinement of completed solutions. It
retains the existing bounded search and its incumbents, uses the existing exact
combat evaluator and complete joint validator, and accepts only improvements
under the established final solution ordering. Keep it **disabled by default**
pending performance and result-quality review. This work does not authorize
Milestone 6, production routing changes, catalog edits, or deployment.

References: [recommendation-quality acceptance](GEAR_RECOMMENDATION_QUALITY_ACCEPTANCE.md),
[candidate-retention assessment](GEAR_CANDIDATE_RETENTION_ASSESSMENT.md),
[targeted-head experiment](GEAR_TARGETED_RETENTION_REFINEMENT.md),
[Milestone 5](GEAR_MILESTONE_5.md), and
[Catalog Coverage Phase 2](GEAR_CATALOG_COVERAGE_PHASE_2.md).

## Reproducible account evidence

The source-controlled fixture
[`gear_search_quality_account.json`](../tests/fixtures/gear_search_quality_account.json)
is a redacted derivative of the acceptance assessment's October 27 authoritative
snapshot, not a fresh account read. It freezes 119 access-eligible physical
equipment definitions across the four regression requests, 84 observed owned
IDs, requirement-referenced quest facts, levels, and existing cached prices.
It contains no account name, XP, database, or unrelated item observations.
The derived fixture represents accepted ownership in synthetic bank observations;
its container timestamps and fingerprint are fixture data, not new account evidence.

Original snapshot: `dab5fd94ac2f1af7df69947250f45661ee9d536acdd91fd172f2aec89f5b0bca`.
Original catalog: `b8cb3949f6707e5604fea77b59dea84d80782054ad7f8d81d03dde4af87d6b67`.
Frozen evaluation time: `2026-10-28T02:14:30.010365Z`.
The reusable [fixture loader](../tools/gear_search_quality_fixture.py) does not
read live observations or the mutable equipment catalog. Regression tests assert
the original equipment and scores before testing the correction.

All account cases use generic ordinary targets with Defence/Magic 80 and zero
bonuses. Slash is accurate; Ranged is rapid. Joint weights are equal, with both
directed transitions, four equipment actions, and twelve reserved supply slots.
The numerical model remains `normal-attacks-v1`.

## Where the better configurations disappear

The [research observer](../tools/trace_gear_search_quality.py) instruments the
current search class in a serial research process immediately before beam
trimming. It changes no ranking, branches, limits, or production logging, and
restores the original class on failure. Instrumented time is not benchmark time.
Ranks below are zero-based and ignore non-ranged ammunition in prefix matching.
This conservatively includes all matching combat-gear paths, without claiming
every ammunition variant is interchangeable under protected prayer/defence rules.
For example, Peaceful blessing's prayer bonus can prevent its removal by the
existing ammunition refinement. Losing even this broader set establishes loss
of the exact witness path.

| Case | Pool evidence | First demonstrated loss of the validated witness |
| --- | --- | --- |
| Owned Slash, Strength amulet | Both 1725 and 6585 retained | Neck prefix ranks 420 among 768 expansions; role/common beam retains 128 |
| +1M/+5M Slash, owned Strength configuration | Neck alternatives retained | Neck prefix ranks 424 among 768; clipped by the same beam |
| +1M/+5M, Combat bracelet only | Both 11126 and 21736 retained | Prefix survives through legs; hands ranks 160 among 896; clipped at 128 |
| Four-action joint, Berserker helm | Both 3751 and 3753 retained | Independent melee witness loses at body, rank 1358 among 1536. Joint head branching never offers 3751 |

For the joint case, melee head branches are `[None, 3753, 1017, 6326]` and
ranged branches `[None, 3749, 6326]`. This is a branch omission inside the joint
search, not an initial candidate-pool omission or a demonstrated joint-beam
ranking eviction. The corresponding ranged role witness survives its role beam.

Role/common beams rank exact **partial** DPS, cost, melee strength ties, and
physical identity. Partial DPS does not anticipate later max-hit breakpoints.
The joint beam uses summed scaffold marginals and a width of 16. Tuple combination
only receives surviving role configurations; neither its partial-state ordering
nor final exact selection can recover a configuration already lost. The complete
validator accepts the manually supplied witnesses, isolating discovery from
legality and final comparison.

Existing ammunition refinement changes only ammunition and cannot repair these
neck, glove, or head failures. The independent targeted-head experiment can
recover Owned Slash through a head-plus-neck trial, but does not recover the
budget failures and deliberately skips joint scenarios. Its opt-in switch and
tests remain separate.

## Strategies evaluated

1. **One exact single-slot pass:** recovers Owned Slash and the joint helm
   witness, but budget Slash reaches only the Combat-bracelet result,
   `2.6708655667374095` DPS.
2. **Iterated exact singles:** can traverse equal-DPS final-order improvements,
   but still does not recover the budget target or the synthetic double
   strength breakpoint.
3. **Singles followed by pairs from only current winners:** passes the small
   historical breakpoint fixtures but fails the actual budget cases. Exhaustive
   same-role two-slot probing from the Combat-bracelet-only configuration finds
   no positive DPS move. Later equal-DPS moves select Fighter torso but can also
   replace Granite boots with leather boots, losing strength needed by a later
   head-plus-neck breakpoint.
4. **Bounded history plus pair refinement:** preserves a small set of already
   accepted complete configurations for subsequent pair discovery. This retains
   useful intermediate strength combinations while final returned incumbents
   still improve monotonically under the existing ordering.

These comparisons justify retaining bounded discovery history rather than
increasing candidate pools, beam widths, or search expansions. The history and
traversal order remain heuristics; realistic-catalog global optimality is not
claimed.

## Implementation and preservation guarantees

[`local_refinement.py`](../tracker/gear/local_refinement.py) is invoked only by
`optimize(..., local_refinement=True)`. No service, API, MCP, frontend, or production
caller enables it. With the flag absent or false, the existing response path is
unchanged. When both experiments are requested, targeted-head refinement runs
first and completed-solution refinement preserves those incumbents as its baseline.

The refinement retains at most **eight** distinct historical accepted incumbents,
including initial seeds, for pair exploration. It retains the first such states
in deterministic encounter order rather than ranking them with another objective.
Current curve/unrestricted winners remain seeds independently of this history.
History is used only for discovery; it never restores an inferior returned winner.

The refinement scans eligible physical IDs and empty slots, respects global and
role locks, skips changes to unscored special-role equipment, and schedules
seed/role/slot groups deterministically. Singles precede pairs; pairs change two
slots within one role. Melee pair traversal prioritizes strength to expose floor
breakpoints, then physical ID. Strength never replaces exact DPS as the final
objective and is not a dominance proof.

Every distinct proposed full assignment consumes one unit before calling
`_Search.solution(..., None)`. That existing validator checks attack support,
item eligibility, physical slots, ownership and assumptions, purchase union and
budget, handedness/ammunition, directed transition plans, and steady/transient
inventory capacity. Accepted candidates are offered only to curve points whose
action limit permits them. Isolated role gains cannot bypass joint validation.

The final key remains: descending weighted DPS, peak gear inventory slots,
purchase cost, total directed actions, and deterministic serialized loadouts.
Only a strictly better key replaces an incumbent. Original curve and unrestricted
solutions remain accessible under `search.local_refinement.baseline`; their item
facts remain in the response. Equal-DPS tie replacements and objective increases
are counted separately. The `objective_improvements` counter also includes filling
an empty incumbent; it is not a count of distinct measured DPS gains. Counts
describe incumbent replacements, so one accepted configuration can improve several
curve points.

The refinement has a separate maximum of **2,000 distinct complete assignments**.
Rejected assignments count too. It leaves the original pool cap, role beam 128,
joint beam 16, and expansion limit 1,000,000 unchanged. Additional combat cache
misses, valid assignments, rounds, single/pair work, elapsed time, and budget
exhaustion are reported. Cancellation is checked during preparation, scheduling,
and before/after complete validation. Timing is observational and excluded from
deterministic equality checks.

## Results and performance

| Regression | Original DPS | Corrected DPS | Additional GP | Outcome |
| --- | ---: | ---: | ---: | --- |
| Owned Slash | 2.642031114342 | 2.728201379517 | 0 | Max hit 17 to 18; Strength amulet recovered |
| Slash +1M | 2.659550762100 | 2.728201379517 | 0 | Owned breakpoint configuration recovered |
| Slash +5M | 2.659550762100 | 2.728201379517 | 0 | Same supported improvement; no unnecessary purchase |
| Joint, four actions | 2.710305653123 | 2.778752039298 | 0 | Exceeds the validated 2.772721328442 witness |

All selected equipment remains observed owned. The regression separately supplies
the Berserker-helm joint witness to the complete validator and verifies its unchanged
Ranged performance, both directed transitions, budget, action limit, and inventory.
The corrected joint result improves melee to `2.642031114342` DPS while Ranged
remains `2.915472964253`. It uses Helm of Neitiznot and Combat bracelet for melee.

The single-role corrected set retains Dragon scimitar 4587, Mooleta 33101,
Black cape 1019, Fighter torso 10551, Zamorak monk bottom 1033, Combat bracelet
11126, Granite boots 21643, and Berserker ring (i) 26770, with Strength amulet
1725. Owned Slash selects Helm of Neitiznot 10828; the budget results select
Berserker helm 3751. Peaceful blessing 20226 occupies ammunition. The helm
difference and blessing are **equal-DPS final-order changes**, not additional
damage gains. Defence/prayer differences are not a new optimization objective.

The joint result retains its shared Ava's accumulator 10499, Fury 6585,
Blue d'hide body 2499, Rangers' tights 23249, Snakeskin boots 6328, Berserker
ring (i) 26770, and Amethyst arrows 21326. Melee uses Dragon scimitar/Mooleta,
Neitiznot 10828, and Combat bracelet; Ranged uses Magic shortbow (i) 12788,
Archer helm 3749, and Ranger gloves 19994. All joint fields are recomputed by
the existing full validator.

Windows development measurements use Python 3.12.10, one warmup and three serial
measured runs per strategy. These use the 119-row redacted fixture and therefore
exclude full-catalog fact-construction cost; they are not substitutes for a
full-catalog or deployed ARM64 benchmark. Output hashes are stable after removing
observational duration fields.

| Case | Baseline median s | Opt-in median s | Assignments | New performance-cache entries | Valid assignments |
| --- | ---: | ---: | ---: | ---: | ---: |
| Owned Slash | 0.565 | 1.007 | 2,000 | 1,963 | 1,239 |
| Slash +1M | 0.610 | 1.087 | 2,000 | 1,989 | 1,150 |
| Slash +5M | 0.679 | 1.087 | 2,000 | 1,985 | 1,269 |
| Joint, four actions | 3.677 | 5.069 | 2,000 | 1,108 | 1,595 |

All four exhaust the refinement cap. Owned Slash uses 308 singles and 1,692
pairs; both budgets use 548 singles and 1,452 pairs. The joint case consumes its
cap on singles. Original explored-node counts remain respectively 18,678,
21,256, 21,472, and 124,257. The shared search expansion budget is not charged
for, or increased by, refinement work.

Separate native Windows `GetProcessMemoryInfo` sampling at 10 ms measured baseline/
opt-in process working-set peaks of 65.55/70.62 MiB for Owned Slash,
70.62/72.56 MiB for +1M, 72.16/73.63 MiB for +5M, and 88.20/88.57 MiB for joint.
These sequential measurements in one process include Python, loaded inputs, and allocator
retention; they do not isolate allocation per request. Process-lifetime peak is
reported separately in the raw benchmark.

The reproducible [benchmark tool](../tools/benchmark_gear_search_quality.py)
includes single-pass/iterated-single research controls and the independent
targeted-head path. Control timings include a separately constructed `_Search`
and do not reuse the baseline full-loadout cache, so their total runtime is not
an apples-to-apples implementation comparison. The controlled score differences
remain useful evidence for which neighborhoods recover each failure.

Derived workload checks use the same redacted inputs, four actions and twelve
reserved supply slots. The single Ranged/Magic requests inherit that four-action
setting rather than the assessment's default eight, so their node counts are not
the historical assessment counts. Three roles are Slash/Ranged/Fire Bolt; four
roles add a second equally weighted Slash role. They exercise configuration count,
not four distinct combat styles.

| Derived case | Baseline median s | Opt-in median s | DPS outcome | New cache entries |
| --- | ---: | ---: | --- | ---: |
| Ranged only | 1.320 | 1.834 | Same 2.915472964253; complete selected result unchanged | 1,873 |
| Fire Bolt only | 1.345 | 2.616 | Same 1.438853910028; Peaceful blessing is a tie change | 1,923 |
| Three roles | 9.770 | 15.132 | Weighted 2.242520775353 to 2.284131225565 | 1,063 |
| Four roles | 13.904 | 18.298 | Weighted 2.304016378348 to 2.342619483375 | 1,169 |

These also use all 2,000 assignments. The three-role gain preserves Ranged and
Magic performance, zero GP cost, four actions and peak gear inventory eight.
The four-role gain changes the second melee role's body to Fighter torso,
preserving the other roles, zero GP, four actions and peak gear inventory nine.
Their unchanged search-node counts are 175,260 and 287,943. Sampled working-set
peaks are 112.01/112.12 MiB and 126.64/127.61 MiB respectively. This makes the
cost of no-gain and multi-role refinement visible rather than assuming a cheap
early exit.

The fourteen small finite scenarios have a separate final benchmark. Three/four
roles with no DPS improvement require only 9/12 distinct assignments and median
helper times 2.23/3.26 ms. The no-feasible-seed case performs zero assignments
and takes 18.3 microseconds in the helper. These tiny timings demonstrate bounded
completion and skipping; they do not predict realistic-catalog latency.

Direct cancellation measurements set the request-local cancellation predicate
immediately after the twentieth complete validation. Owned Slash and joint both
raise `optimization_cancelled`, after 25.2 and 45.3 microseconds respectively;
total helper time to that point is 6.22/9.13 ms. This measures responsiveness
between validations, not interruption of an in-progress transition search,
baseline preparation, HTTP cancellation, or browser latency.

Raw final evidence is in ignored `.tmp/search-quality-correction/final-account.json`,
`final-tiny.json`, and `cancellation.json`. Account report helper durations are the
last measured sample, not helper medians; overall medians above use all three
measured total runtimes. The benchmark utility now records per-run helper timings
and medians for future reproductions. Earlier pilot reports are not final timing
evidence.

## Independent correctness and compatibility

The source-controlled regressions first failed before the new opt-in API existed.
The initial singles/pairs implementation then failed the two budget acceptance
tests; they were not relaxed. A separate generic tie-valley regression now checks
why retaining an accepted neutral intermediate matters.

The existing independent finite-catalog oracle exhaustively enumerates complete
assignments without reusing optimizer search or pruning. It independently computes
purchase unions and directed transition paths while sharing the numerical combat
model. The correction matches its best DPS across the fourteen small fixtures,
including single and double strength breakpoints, one through four roles, shared
purchases, physical identity, explicit locks, ammunition, handedness and tight
transient capacity. This establishes those finite-fixture results only.

Additional tests cover all-curve/unrestricted no-worse ordering, complete legality,
unknown or unmet requirements, unsupported effects, exclusions, hypothetical
ownership and eligibility, snapshot immutability, no feasible seed, assignment
exhaustion, equal-DPS ties, deterministic concurrent calls, and cancellation during
refinement. The independent targeted-head experiment is tested both alone and
composed with the correction. Production service/API/MCP calls retain the default
baseline path.

The 47 refinement unit/integration tests pass with all 141 statements covered
and 99% combined statement/branch coverage (one partial branch). Scoped Ruff,
formatting and strict core mypy checks are part of final verification. Frontend
unit compatibility passes 166 tests; the TypeScript/Vite build passes. An initial
parallel frontend run had two five-second UI timeouts; a serial-worker run passed
all tests without source or timeout changes.

Final broader verification: **617 Python tests passed** in 166.94 seconds across
Gear optimizer/combat/service, API optimization/evaluation, optimizer MCP,
independent oracle, and stage-observer tests. The 47-test coverage run is a subset,
not 47 additional unique tests. **Eight desktop/mobile browser journeys passed**
in 35.7 seconds, covering existing single, two-, three-, and four-role UI flows.
Those journeys verify compatibility with the unchanged default backend path;
they do not expose or enable the Python-only experiment in the browser.
Independent source review found no blocking correctness issues. Browser-generated
screenshots were retained in ignored test artifacts and the previously clean
tracked documentation screenshots restored.

## Reproduction

From the repository root, with the existing development environment:

```powershell
.venv\Scripts\python.exe -m pytest tests/gear/test_search_quality_account.py tests/gear/test_local_refinement.py tests/gear/test_local_refinement_integration.py tests/test_trace_gear_search_quality.py -q --no-cov
.venv\Scripts\python.exe -m tools.trace_gear_search_quality owned_slash
.venv\Scripts\python.exe -m tools.trace_gear_search_quality melee_1m --bracelet
.venv\Scripts\python.exe -m tools.trace_gear_search_quality joint_four
.venv\Scripts\python.exe -m tools.benchmark_gear_search_quality --strategies baseline local --cases owned_slash melee_1m melee_5m joint_four owned_ranged owned_magic account_three account_four --memory --out .tmp/search-quality-correction/reproduced-account.json
.venv\Scripts\python.exe -m tools.benchmark_gear_search_quality --cases --tiny --strategies baseline local --out .tmp/search-quality-correction/reproduced-tiny.json
```

The broader Python selection is:

```powershell
.venv\Scripts\python.exe -m pytest tests/gear tests/api/test_gear_ui.py tests/api/test_gear_optimizations.py tests/api/test_gear_joint_optimizations.py tests/api/test_gear_evaluations.py tests/quest_cape/test_optimizer_mcp.py tests/test_gear_retention_oracle.py tests/test_trace_gear_search_quality.py -q --no-cov
```

In `frontend/gear`, compatibility commands are `npm.cmd run test -- --maxWorkers=1`,
`npm.cmd run build`, and `npm.cmd run test:e2e -- optimization.spec.ts joint.spec.ts`.
Use a distinct `COVERAGE_FILE` for concurrent coverage work; the final isolated
report is `.tmp/search-quality-correction/coverage.json`.

Use `--strategies single_pass iterated_singles targeted` for the controls and
`--cancellation` for the direct helper cancellation measurement. Run benchmarks
serially, independently of test workers. Research tracing temporarily replaces
the class inside its own serial process; never import that observer into an
application process or run it concurrently with optimizer requests.

## Limitations and enablement decision

Keep default enablement off. Pair trials modify only one role at a time; simultaneous
cross-role changes and longer adverse/neutral paths can remain undiscovered. The
history cap and assignment cap can omit useful exploration. A no-gain request can
still spend the refinement budget, so opt-in cost needs explicit review.

The correction cannot discover a solution when there is no valid completed seed.
It does not unblock unsupported metadata, invent prices, model new combat
mechanics, prove infeasibility, or establish a global optimum. Catalog, price,
frontend packaging, and production-readiness blockers in the acceptance report
remain separate work. ARM64 performance of this correction is unverified; no Pi
deployment or production cutover is performed.
