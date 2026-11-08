# Desktop gear optimizer: performance analysis and work tracker

**Analysis date:** 2026-11-08  
**Assessed revision:** `3fad336`  
**Status:** Analysis complete; implementation proposals and experiments pending.  
**Scope:** Desktop optimization, including Single, Multi, Auto disciplines,
potion selection, secondary frontiers, and running-cost frontiers.

This document records the fundamental performance analysis and tracks follow-up
work. It does not authorize or claim implementation of the proposed redesign.
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

The evidence supports substantial opportunities, but no end-to-end speedup from
these proposals has been measured. The repeated-signature counts below are not
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

Two distinct acceptance standards apply. Refactors that preserve search policy
must retain full result parity, excluding observational timing. New search policies
must demonstrate correctness and frontier quality; exact historical IDs need not
be the only acceptance measure if a better feasible result replaces an old point.

| Work item | Completion evidence | Status |
| --- | --- | --- |
| Representative desktop benchmark suite | Frozen Single/Multi/Auto cases, option/potion variants, bonus and defence-roll metrics, repeated timings, peak memory, cancellation, complete result fingerprints | Pending |
| Reusable dependency probe | Tracked redacted inputs; counting harness; equivalence checks; bounded-cache hit/miss, key-cost, and memory measurements | Pending |
| P1 factored evaluator | Differential scalar/full-model tests; complete archive parity; measured runtime and memory | Pending |
| P2 shared evaluation | Lane winner isolation; context invalidation tests; stable logical work budgets; observed reuse | Pending |
| P3 compact states | Exact acquisition, transition, inventory, tie-order and fractional-sum parity; allocation/serialization reduction | Pending |
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
- [ ] Establish the representative desktop baseline and portable probe.
- [ ] Implement and validate the first compact evaluator experiment.
- [ ] Record each experiment's revision, environment, scenario provenance,
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
