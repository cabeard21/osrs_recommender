# Gear Optimizer refinement enablement review

## Decision and scope

**Retain opt-in refinement as an experimental capability. Do not enable it in the normal service/API/MCP workflow yet.** The expanded catalog supplies a real, zero-GP Slash improvement, but the full local budget adds substantial work to requests that gain no DPS. The narrower targeted experiment is much cheaper for this account's melee cases, but misses established historical budget/joint improvements. Neither is an adequate universal default on this evidence.

The preferred next product design is an explicitly selected Fast/Thorough mode, subject to a separate reviewed implementation decision and operational acceptance. Fast must preserve today's baseline. Thorough would describe bounded additional search, retain cancellation and baseline recovery, and continue to return `best_found`. This review does not implement that design or authorize Milestone 6. Production formulas, scoring, beams, candidate limits, routing, service, API and MCP remain unchanged.

This report follows [high-impact coverage](GEAR_HIGH_IMPACT_COVERAGE.md), [search correction](GEAR_SEARCH_QUALITY_CORRECTION.md), [recommendation acceptance](GEAR_RECOMMENDATION_QUALITY_ACCEPTANCE.md), and [targeted retention](GEAR_TARGETED_RETENTION_REFINEMENT.md). Numerical results describe supported ordinary attacks against the same generic target: Defence/Magic 80, zero defence bonuses, accurate Slash, rapid Ranged, accurate Fire Bolt. They do not establish encounter utility, survival, consumable endurance or global best-in-slot.

## Input identity and separate historical evidence

The connected account summary was checked before measurement. Its latest persisted sync was **2026-10-28 02:53:24 UTC**, newer than the preceding acceptance capture. The Pi database was read using SQLite `mode=ro`, `query_only=ON`, a WAL-aware in-memory backup and `quick_check=ok`; the serialized copy was retained locally. No account observations were changed. This is the latest available persisted account at capture, not guaranteed current in-game state.

| Input | Identity |
| --- | --- |
| Current account snapshot | `7781190a42c1bf2af0b81323d3945ddc1d6ce2c6dc086b45dd4afd2f2be224cd` |
| Captured current SQLite image SHA-256 | `a1a5d20f7db3e7e60d366d79595641e53a7b2c34ca2d9bc8840653ec313c8cf4` |
| Expanded physical catalog revision | `7ef875fb452c389eef0460cd76c2f6c177a4f5f27c5b26468f8505675798f8f7` |
| Evaluation clock | `2026-10-28T03:00:35.437377+00:00` |
| Expanded as-of price revision | `64e600bf48045ee0b7b5d94545c817e5ac7e997f72ff0a4cef4f925cb7832fec` |
| Historical acceptance snapshot | `dab5fd94ac2f1af7df69947250f45661ee9d536acdd91fd172f2aec89f5b0bca` |
| Historical physical catalog revision | `b8cb3949f6707e5604fea77b59dea84d80782054ad7f8d81d03dde4af87d6b67` |
| Unchanged historical fixture file SHA-256 | `402bbed7834ffe0f4e069f253f24d999f691b41ec7846879a9aa10db7460a46d` |
| Development HEAD, dirty checkout | `f74bf4cc89598964fa7309867bbc4086783fe04a` |
| Optimizer source SHA-256 | `d3217c0a49e0f3cb7ba3e9eca30afd17b98df8944db38e93c2e1b73e34b5a3f4` |
| Local helper source SHA-256 | `0b8eea542e94eb86ac4af5b91740b3629f57bc3dbcebced387726e24353c07d2` |
| Targeted helper source SHA-256 | `ad131e78b04f63be33466bcb43a84df39a8cd0f002f5fb36f7cc5a0994697f15` |

The current price set combines the freshly captured database's as-of prices with the seventeen exact-ID records already captured by high-impact coverage. It does not refresh market prices, invent quotes, persist an overlay, or substitute one physical ID's quote for another. The price revision hashes sorted `{id: str(record)}` JSON using the existing acceptance convention. The separate catalog/price pilot without that overlay is not the final measurement set; in particular its budget-case recovery counts differ.

The original source-controlled fixture retains its own embedded equipment, prices, account facts and clock. It was not regenerated against the expanded catalog. Historical fixture tests and the separate expanded-catalog replay of the earlier private acceptance account both remain distinct from the new authoritative capture.

Private evidence is retained under ignored [`.tmp/gear-refinement-review/`](../.tmp/gear-refinement-review/): `capture.json`, `current.sqlite`, `full-priced.json`, `historical-expanded-replay.json`, `boundaries.json`, `witnesses.json`, `profiles.json`, `verify.json`, `pi.json`, `health.json`, `source-identities.json`, and the measurement scripts. Full responses retain all action-curve points, purchases, transitions, equipment facts and refinement baseline snapshots. These private artifacts are local acceptance evidence, not a portable public account fixture.

## Exact real-account regression and quality interpretation

Owned Slash returns **2.6708655667374095 DPS** with Warrior helm `3753`. Replacing only its head with already-owned Berserker helm `3751` gives **2.7955325803150433 DPS**, an increase of **0.1246670135776338 DPS / 4.67%**, for **zero additional GP**. Max hit rises 17→18 while accuracy falls 0.749229821→0.741141196. Both the previous private account capture and the newer authoritative snapshot reproduce this regression with the expanded inputs.

The witness is evaluated through `_Search.solution`, including complete equipment legality, requirements, supported combat, cost and purchase unions, action constraints and transient inventory. No approximate DPS calculation is used. All final feasible curve and unrestricted solutions in the seven-scenario comparison are independently replayed through that same complete evaluator: **195 successful complete validations**. Finite fixture tests additionally use the separate exhaustive oracle, which shares numerical combat but independently checks enumeration, acquisition and transitions.

Both refinements recover the witness's objective value in all three Slash cases. Their final selected head is Helm of Neitiznot `10828`; that final tie choice must not be confused with the independently checked Berserker witness. In the two purchase-budget cases, recovery also changes Black platebody `1125` back to Fighter torso `10551`; the owned-case single substitution alone does not explain those paths.

Owned Ranged and Magic gain no DPS from either experiment. Budget Ranged already buys Archers ring `6733` for **1,859,790 GP** in baseline and gains no further DPS from refinement. The joint case retains melee/Ranged DPS **2.670865566737 / 2.942705209708**, weighted **2.806785388223**. Local refinement changes only its melee hands to Combat bracelet `11126` at equal DPS. Magic's local result adds equipped ammunition at equal DPS. These are existing serialization/tie-order changes, not damage improvements, defensive Pareto improvements or useful purchases.

Local diagnostics count curve/unrestricted replacements, not distinct improved requests: each Slash case reports 10 objective replacements; Ranged/Magic/joint report zero. Tie replacements are 20 for owned Slash, 60 for each budget Slash, 20 for Magic, four for joint, and zero for both Ranged cases. Targeted skips Ranged, Magic and joint because they are outside its supported trigger. Skipping is compatibility behavior, not evidence that targeted searches those configurations.

Single requests retain action limits 0–8 and 12 reserved supply slots. The joint request retains limit four, both directed edges, and 12 reserved supply slots. Its selected carried union contains 14 physical IDs; melee→Ranged takes three actions and reverse takes four, with transient gear peak four. Single-role gear inventory peaks are zero. No selected result violates a purchase budget, equipment lock, exclusion or supported assumption.

## Full-catalog results

Role cells list equipment key, DPS, max hit, and accuracy. Weighted DPS is the existing score. Actions are selected maximum edge actions; inventory is transient gear peak.

| Scenario | Mode | Weighted DPS | Roles: key / DPS / hit / accuracy | GP | Actions | Gear peak |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| owned_slash | baseline | 2.670865566737 | melee: L1 / 2.670865566737 / 17 / 0.749229821 | 0 | 0 | 0 |
| owned_slash | local | 2.795532580315 | melee: L2 / 2.795532580315 / 18 / 0.741141196 | 0 | 0 | 0 |
| owned_slash | targeted | 2.795532580315 | melee: L2 / 2.795532580315 / 18 / 0.741141196 | 0 | 0 | 0 |
| owned_ranged | baseline | 2.949200995744 | ranged: L3 / 2.949200995744 / 13 / 0.807824621 | 0 | 0 | 0 |
| owned_ranged | local | 2.949200995744 | ranged: L3 / 2.949200995744 / 13 / 0.807824621 | 0 | 0 | 0 |
| owned_ranged | targeted | 2.949200995744 | ranged: L3 / 2.949200995744 / 13 / 0.807824621 | 0 | 0 | 0 |
| owned_magic | baseline | 1.442765429029 | magic: L4 / 1.442765429029 / 12 / 0.712251288 | 0 | 0 | 0 |
| owned_magic | local | 1.442765429029 | magic: L5 / 1.442765429029 / 12 / 0.712251288 | 0 | 0 | 0 |
| owned_magic | targeted | 1.442765429029 | magic: L4 / 1.442765429029 / 12 / 0.712251288 | 0 | 0 | 0 |
| melee_1m | baseline | 2.670865566737 | melee: L6 / 2.670865566737 / 17 / 0.749229821 | 0 | 0 | 0 |
| melee_1m | local | 2.795532580315 | melee: L2 / 2.795532580315 / 18 / 0.741141196 | 0 | 0 | 0 |
| melee_1m | targeted | 2.795532580315 | melee: L7 / 2.795532580315 / 18 / 0.741141196 | 0 | 0 | 0 |
| melee_5m | baseline | 2.670865566737 | melee: L6 / 2.670865566737 / 17 / 0.749229821 | 0 | 0 | 0 |
| melee_5m | local | 2.795532580315 | melee: L2 / 2.795532580315 / 18 / 0.741141196 | 0 | 0 | 0 |
| melee_5m | targeted | 2.795532580315 | melee: L7 / 2.795532580315 / 18 / 0.741141196 | 0 | 0 | 0 |
| ranged_5m | baseline | 2.961841467505 | ranged: L8 / 2.961841467505 / 13 / 0.811287011 | 1859790 | 0 | 0 |
| ranged_5m | local | 2.961841467505 | ranged: L8 / 2.961841467505 / 13 / 0.811287011 | 1859790 | 0 | 0 |
| ranged_5m | targeted | 2.961841467505 | ranged: L8 / 2.961841467505 / 13 / 0.811287011 | 1859790 | 0 | 0 |
| joint_four | baseline | 2.806785388223 | melee: L9 / 2.670865566737 / 17 / 0.749229821; ranged: L10 / 2.942705209708 / 13 / 0.806045340 | 0 | 4 | 4 |
| joint_four | local | 2.806785388223 | melee: L11 / 2.670865566737 / 17 / 0.749229821; ranged: L10 / 2.942705209708 / 13 / 0.806045340 | 0 | 4 | 4 |
| joint_four | targeted | 2.806785388223 | melee: L9 / 2.670865566737 / 17 / 0.749229821; ranged: L10 / 2.942705209708 / 13 / 0.806045340 | 0 | 4 | 4 |

Equipment uses exact physical IDs; omitted slots are empty.

| Key | Slot=physical ID |
| --- | --- |
| L1 | ammunition=20226, body=10551, cape=29289, feet=21643, hands=7459, head=3753, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| L2 | ammunition=20226, body=10551, cape=29289, feet=21643, hands=7459, head=10828, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| L3 | ammunition=21326, body=29280, cape=29289, feet=29286, hands=19994, head=3749, legs=23249, neck=1704, ring=13125, weapon=12788 |
| L4 | body=4091, cape=13121, feet=2579, hands=7459, head=3755, legs=4093, neck=1704, ring=13125, shield=12612, weapon=4675 |
| L5 | ammunition=20226, body=4091, cape=13121, feet=2579, hands=7459, head=3755, legs=4093, neck=1704, ring=13125, shield=12612, weapon=4675 |
| L6 | body=1125, cape=29289, feet=21643, hands=7459, head=3753, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| L7 | body=10551, cape=29289, feet=21643, hands=7459, head=10828, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| L8 | ammunition=21326, body=29280, cape=29289, feet=29286, hands=19994, head=3749, legs=23249, neck=1704, ring=6733, weapon=12788 |
| L9 | ammunition=21326, body=2501, cape=29289, feet=29286, hands=7459, head=3753, legs=23249, neck=6585, ring=26770, shield=33101, weapon=4587 |
| L10 | ammunition=21326, body=2501, cape=29289, feet=29286, hands=19994, head=3749, legs=23249, neck=6585, ring=26770, weapon=12788 |
| L11 | ammunition=21326, body=2501, cape=29289, feet=29286, hands=11126, head=3753, legs=23249, neck=6585, ring=26770, shield=33101, weapon=4587 |

## Windows runtime and work

Wall values are medians of three serial measured calls following one warmup. CPU and memory come from a separate fresh-process single sample for each cell. Memory is whole-process lifetime high-water RSS, including input/database loading; it is not incremental refinement allocation.

| Scenario | Mode | Wall s | CPU s | Peak MiB | Extra exact checks | Extra combat cache misses | Exhausted |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| owned_slash | baseline | 0.941 | 0.969 | 181.3 | 0 | 0 | False |
| owned_slash | local | 1.515 | 1.484 | 181.2 | 2000 | 1940 | True |
| owned_slash | targeted | 1.009 | 0.953 | 181.2 | 106 | 106 | False |
| owned_ranged | baseline | 0.966 | 0.953 | 181.5 | 0 | 0 | False |
| owned_ranged | local | 1.352 | 1.328 | 181.6 | 2000 | 1900 | True |
| owned_ranged | targeted | 1.017 | 0.922 | 181.4 | 0 | 0 | False |
| owned_magic | baseline | 1.025 | 1.031 | 181.6 | 0 | 0 | False |
| owned_magic | local | 1.625 | 1.500 | 181.5 | 2000 | 1921 | True |
| owned_magic | targeted | 1.093 | 1.031 | 181.5 | 0 | 0 | False |
| melee_1m | baseline | 1.054 | 0.984 | 181.5 | 0 | 0 | False |
| melee_1m | local | 1.555 | 1.484 | 181.6 | 2000 | 1990 | True |
| melee_1m | targeted | 1.158 | 1.172 | 181.4 | 684 | 684 | False |
| melee_5m | baseline | 1.070 | 1.172 | 181.3 | 0 | 0 | False |
| melee_5m | local | 1.604 | 1.781 | 181.2 | 2000 | 1985 | True |
| melee_5m | targeted | 1.211 | 1.312 | 181.3 | 684 | 684 | False |
| ranged_5m | baseline | 1.117 | 1.094 | 181.7 | 0 | 0 | False |
| ranged_5m | local | 1.509 | 1.500 | 181.5 | 2000 | 1884 | True |
| ranged_5m | targeted | 1.109 | 1.156 | 181.5 | 0 | 0 | False |
| joint_four | baseline | 2.839 | 2.969 | 181.5 | 0 | 0 | False |
| joint_four | local | 3.662 | 3.844 | 181.5 | 2000 | 1155 | True |
| joint_four | targeted | 2.763 | 3.047 | 181.5 | 0 | 0 | False |

## Deterministic recovery budgets

These are the first budgets recovering the strongest objective score found at 2,000 in each row. Binary subdivision was followed by explicit N-1/N checks. They recover an objective value, not necessarily the identical witness equipment. A no-gain row has no recovery threshold.

| Fixture | Local first budget | Targeted first budget | Recovered DPS |
| --- | ---: | ---: | ---: |
| owned_slash | 61 | 1 | 2.795532580315 |
| owned_ranged | no gain | no gain | 2.949200995744 |
| owned_magic | no gain | no gain | 1.442765429029 |
| melee_1m | 341 | 620 | 2.795532580315 |
| melee_5m | 341 | 620 | 2.795532580315 |
| ranged_5m | no gain | no gain | 2.961841467505 |
| joint_four | no gain | no gain | 2.806785388223 |
| breakpoint | 13 | 1 | 1.798007071681 |
| double_breakpoint | 25 | 13 | 1.798007071681 |
| historical_owned_slash | 28 | 33 | 2.728201379517 |
| historical_melee_1m | 809 | no gain | 2.728201379517 |
| historical_melee_5m | 809 | no gain | 2.728201379517 |
| historical_joint_four | 1083 | no gain | 2.778752039298 |

Sweep scores (local, complete evaluator; columns are assignment caps):

| Scenario | 0 | 16 | 32 | 64 | 128 | 256 | 512 | 1000 | 2000 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| owned_slash | 2.670865567 | 2.670865567 | 2.670865567 | 2.795532580 | 2.795532580 | 2.795532580 | 2.795532580 | 2.795532580 | 2.795532580 |
| owned_ranged | 2.949200996 | 2.949200996 | 2.949200996 | 2.949200996 | 2.949200996 | 2.949200996 | 2.949200996 | 2.949200996 | 2.949200996 |
| owned_magic | 1.442765429 | 1.442765429 | 1.442765429 | 1.442765429 | 1.442765429 | 1.442765429 | 1.442765429 | 1.442765429 | 1.442765429 |
| melee_1m | 2.670865567 | 2.670865567 | 2.670865567 | 2.670865567 | 2.670865567 | 2.670865567 | 2.795532580 | 2.795532580 | 2.795532580 |
| melee_5m | 2.670865567 | 2.670865567 | 2.670865567 | 2.670865567 | 2.670865567 | 2.670865567 | 2.795532580 | 2.795532580 | 2.795532580 |
| ranged_5m | 2.961841468 | 2.961841468 | 2.961841468 | 2.961841468 | 2.961841468 | 2.961841468 | 2.961841468 | 2.961841468 | 2.961841468 |
| joint_four | 2.806785388 | 2.806785388 | 2.806785388 | 2.806785388 | 2.806785388 | 2.806785388 | 2.806785388 | 2.806785388 | 2.806785388 |


## Refinement efficiency and implementation assessment

Exact witness visits are recorded separately from objective-equivalent recovery. A cap of N includes the complete check at attempt N; later equal-DPS ties can select different equipment.

| Known local-refinement witness | First exact assignment | First witness objective |
| --- | ---: | ---: |
| Current owned Slash, original equipment with Berserker helm | 61 | 61 |
| Historical owned Slash, original equipment with Amulet of strength | 28 | 28 |
| Historical +1M / +5M, original budget equipment with Combat bracelet | 52 / 52 | 52 / 52 |
| Historical +1M / +5M, owned-Slash Amulet-of-strength equipment | Not visited within 2,000 | 809 / 809 |
| Historical joint, original equipment with melee Berserker helm | 581 | 581 |

For the two unvisited exact assignments, the optimizer recovers the witness's DPS using an objective-equivalent outcome with different equipment tie choices; it does not promise to return or enumerate the particular original witness. The stronger historical joint outcome appears later at 1,083. The independent old single/double breakpoint objective thresholds are in the preceding table.

The deterministic sweep also measures helper-only work on a fresh `_Search` with the frozen completed baseline seeds. These are single Windows samples with a cold full-loadout performance cache; they exclude baseline search and final response assembly and cannot be added directly to the integrated medians. They explain work savings rather than predict Pi or service latency.

| Scenario | 64 checks, s | 512 checks, s | 2,000 checks, s |
| --- | ---: | ---: | ---: |
| owned_slash | 0.0184 | 0.1457 | 0.5616 |
| owned_ranged | 0.0162 | 0.1054 | 0.4914 |
| owned_magic | 0.0185 | 0.1606 | 0.6526 |
| melee_1m | 0.0173 | 0.1396 | 0.4962 |
| melee_5m | 0.0174 | 0.1444 | 0.5409 |
| ranged_5m | 0.0160 | 0.1089 | 0.4020 |
| joint_four | 0.0314 | 0.2088 | 0.8700 |

The local helper's exact-assignment cap is **not necessary to recover these measured objective gains**. Current owned Slash first recovers at 61 checks; each current budget Slash at 341. A 512 cap therefore recovers the current seven-case objective outcomes, but loses historical quality: the strongest old budget results require 809, and the strongest old joint result requires 1,083. Even 1,000 is insufficient for that joint outcome. The old single/double breakpoint recoveries require 13/25 local checks. These thresholds concern this deterministic scheduling and these exact input identities; catalog, eligibility, seed or price changes can move them.

A smaller universal default is not justified. A prospective 1,200–1,500 assignment Thorough cap could be evaluated against a larger corpus, but it would merely exceed the largest observed threshold here. It is not a sufficiency proof. The targeted helper recovers current owned Slash's objective in one assignment but needs 620 for the budget cases, and cannot recover the historical budget/joint gains at all. Narrow-trigger default enablement would therefore need a separately specified scope and fallback rather than an assumption that all melee losses are omitted-head losses.

Adaptive scheduling is a worthwhile research direction: establish the baseline, offer a bounded early refinement slice, then continue in deterministic chunks under an explicit Thorough request. Preserve the existing scheduling prefix and exact acceptance ordering when evaluating chunk sizes. Do not use “no improvement in the first slice” as proof that later work is useless: the historical budget and double-breakpoint cases demonstrate delayed gains and neutral intermediates. A runtime deadline must be separate from the assignment budget and must specify whether a validated incumbent is returned or the request is cancelled. No such behavior is implemented here.

Implementation inspection found no blocking defect in exact acceptance. `tracker/gear/local_refinement.py` tries complete singles, then same-role pairs, revisits accepted finalists, retains eight historical seeds, and accepts only strict improvement under existing `_solution_key`: weighted DPS, inventory peak, acquisition cost, total actions, stable equipment identity. Every trial calls `optimizer._Search.solution`; only compatible curve points can change. Deep-copied baseline incumbents remain recoverable. This establishes no-worse baseline ordering, not global discovery completeness.

The 2,000 cap bounds distinct complete assignment checks, including invalid trials, and at most four new performance cache entries per check. It does not bound queue construction, duplicate traversal, transition exploration, baseline preparation or wall time. Cancellation checks surround setup/scheduling/evaluation; an in-progress complete transition calculation is not interrupted by the helper. One-role pair neighborhoods cannot generally discover simultaneous changes across roles or longer adverse paths.

The service optimization/evaluation lock remains occupied for the complete operation. API snapshot checks before calculation and before publication remain necessary for a slower Thorough mode; an old response must not overwrite a changed account/scenario. An eventual mode and work-budget policy must participate in request/result identity and cache provenance. Existing baseline callers must retain the same behavior and fallback.

## ARM64 performance and operational policy

The authorized benchmark ran on the existing four-core Raspberry Pi, Linux `6.18.50+rpt-rpi-v8`, **aarch64**, Python **3.12.15**, inside the existing container. Only code/content/scenario inputs and the previously captured price overlay were transferred. Each child read the Pi database read-only into memory; all eight cells matched the Windows snapshot, database, catalog, clock and price identities above. Production files and observations were not replaced. Execution used `nice -n 10`, serial child processes and a disposable temporary directory, removed on completion. This is isolated compute acceptance, not deployed feature acceptance.

Each cell had one warmup and **two measured calls**. Wall/CPU are measured-call medians; RSS is the fresh child process lifetime high-water (`getrusage`), including database/content loading and warmup. It is not incremental allocation or container peak. All three response hashes per cell agreed; selected equipment/scores also match Windows.

| Scenario | Mode | Wall s | CPU s | CPU/wall | Peak MiB | Cancel completion s from entry |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| owned_slash | baseline | 4.796 | 4.784 | 0.997 | 174.5 | 1.795 |
| owned_slash | local | 8.603 | 8.577 | 0.997 | 174.4 | 1.562 |
| owned_ranged | baseline | 4.865 | 4.855 | 0.998 | 174.6 | 2.106 |
| owned_ranged | local | 7.680 | 7.631 | 0.994 | 174.5 | 2.037 |
| owned_magic | baseline | 5.426 | 5.412 | 0.997 | 174.6 | 2.048 |
| owned_magic | local | 9.213 | 9.185 | 0.997 | 174.7 | 1.773 |
| joint_four | baseline | 16.439 | 16.389 | 0.997 | 174.4 | 1.804 |
| joint_four | local | 21.729 | 21.652 | 0.996 | 174.7 | 1.977 |

Cancellation in that table was requested by a timer at nominal **0.1 seconds from optimizer entry**; every call raised `optimization_cancelled`. Completion took **1.56–2.11 seconds**, exposing baseline preparation before effective cancellation checks. This is separate from refinement-only cancellation: with a timer armed at helper entry for nominal 0.05 seconds, completion took **0.0555–0.0564 seconds** for all four local cases. The timer callback timestamp was not recorded, so the difference from 0.05 is not an exact event-to-return latency. The direct Windows trial-20 check records the actual request timestamp and acknowledges in **0.017–0.060 ms**, excluding preparation, HTTP and browser latency.

The measured full-run ARM64 envelope was **21.879 seconds maximum elapsed** and **174.75 MiB maximum process peak RSS** across these cells (including warmups). CPU/wall close to one means approximately one core stayed busy; these are CPU seconds, not a percentage of all four cores. These are observed bounds for the tested inputs, **not enforced runtime/memory ceilings or worst-case guarantees**. Request validation count alone cannot guarantee a future ceiling.

Host available RAM changed from **2,521,544 to 2,504,920 KiB**; available swap was effectively unchanged. Container memory at driver boundaries was approximately **251 MiB**. The existing cgroup reported `memory.max=max` and `cpu.max=max 100000`: no observed hard CPU/memory limit. Ten read-only `/healthz` probes around the tail of the benchmark session all returned 200, in **5.5–168.9 ms**; the probe phase was not tagged to individual optimizer calls. Cgroup memory-event counters reported zero high/max/OOM events. This supports absence of an observed outage or OOM, not absence of user-facing interference.

Operational assessment: isolated serial work did not demonstrate host memory exhaustion, but each Thorough request adds roughly **2.8–5.3 CPU seconds** in these measured medians and occupies the service busy gate longer. The dashboard, sync endpoint and MCP share host/container resources, so contention can affect them even with spare cores; this benchmark ran in a separate lower-priority process and does not measure Python serving-process GIL/thread contention. No authenticated RuneLite sync write, dashboard journey or MCP concurrency workload was generated. Their latency under simultaneous serving-process optimization remains an explicit acceptance gap. Do not infer production responsiveness from the health probes.

Three-/four-role Windows samples are below. These additional requests retain the original joint edges, rather than exercising every directed graph. All completed, and separate complete-evaluator replay validated every feasible curve/unrestricted output and no-worse ordering.

| Roles | Mode | Wall s | CPU s | Whole-process peak MiB | Weighted DPS |
| --- | --- | ---: | ---: | ---: | ---: |
| 3 | baseline | 4.817 | 4.688 | 181.6 | 2.272296561700 |
| 3 | local | 6.814 | 6.562 | 181.2 | 2.311420510146 |
| 4 | baseline | 7.352 | 7.234 | 181.2 | 2.333171474710 |
| 4 | local | 8.679 | 8.438 | 181.8 | 2.371938812959 |

No prohibitive cost was established for these Windows configurations, but **three-/four-role ARM64 timings were not measured**. Supported policy for this review is to keep their existing direct Python experimental capability available with all requested roles/constraints intact; keep normal production requests on baseline. A future Thorough UI/API must explicitly support one-to-four-role requests with progress, cooperative cancellation, a documented busy response and an independently accepted runtime/resource policy. Do not silently drop roles, omit transitions or turn off refinement for a role count while claiming a Thorough result. Until that acceptance exists, do not expose an enabled production Thorough path for any role count.


## Tests, acceptance limits and remaining work

The focused mixed invocation passed **244 tests** and reported five fixture-setup errors in `test_optimizer_service.py` (`make_content` unavailable when mixed with the other fixture scopes). Running that module alone passed **all five** without source changes: **249 passing tests across the two lanes**, with the initial setup failure retained as part of the execution record. No behavior assertion failed. The selection covers exact historical account regressions; local and targeted unit/integration tests; both old breakpoint fixtures; exhaustive one-to-four-role cases; purchases/unions; locks/exclusions/future assumptions; directed transitions and tight transient inventory; no-worse ordering; determinism; cancellation; service busy handling; and stale-before/stale-after API publication plus disconnect cancellation.

The seven current scenarios each have one warmup and three measured serial calls in all three modes. All **84 semantic response hashes** agree within their scenario/mode cell after excluding observational duration fields. The cap sweep is deterministic work, not a stopwatch cutoff; threshold checks explicitly compare N-1 with N. A separate current-account run validates completed three-/four-role curves and unrestricted winners through the complete evaluator and verifies baseline ordering. These additional configurations add a Fire Bolt role and, for four roles, a second melee role to the joint request, retaining its explicit directed edges; they do not represent every possible role/transition graph.

Reproduction uses the retained private capture and scripts, from the repository root:

```powershell
.venv/Scripts/python.exe .tmp/gear-refinement-review/run.py --sweeps --out .tmp/gear-refinement-review/reproduced.json --repeats 3
.venv/Scripts/python.exe .tmp/gear-refinement-review/extra.py
.venv/Scripts/python.exe .tmp/gear-refinement-review/profiles.py
.venv/Scripts/python.exe .tmp/gear-refinement-review/verify.py
.venv/Scripts/python.exe .tmp/gear-refinement-review/pi.py
.venv/Scripts/python.exe -m pytest tests/gear/test_search_quality_account.py tests/gear/test_local_refinement.py tests/gear/test_local_refinement_integration.py tests/gear/test_targeted_retention.py tests/gear/test_targeted_retention_integration.py tests/test_gear_retention_oracle.py tests/api/test_gear_optimizations.py tests/api/test_gear_joint_optimizations.py -q --no-cov
.venv/Scripts/python.exe -m pytest tests/gear/test_optimizer_service.py -q --no-cov
```

Measurement scripts use scoped, serial research-process wrappers to reduce the existing private helper budget. They must not be imported into a serving application or run in parallel with requests in that interpreter. The historical fixture remains independently runnable through `tools.benchmark_gear_search_quality`; the new evidence does not replace its catalog/price identity. No tracked executable statements changed, so this review claims no new implementation coverage percentage or browser acceptance. The first Pi measurement attempt failed in the disposable harness's cancellation-event handling; it was corrected before the final accepted measurements, without modifying production code.

Before any enablement decision is implemented:

1. Agree on a user-visible latency target and measured resource envelope for Fast/Thorough, including three/four roles, cancellation during preparation, and concurrent dashboard/sync/MCP traffic. Treat observed maxima as measurements, not enforced ceilings or worst-case guarantees.
2. Retain more independent account/catalog witnesses, including joint coordinated changes, and compare deterministic smaller budgets with 2,000. Redact a separate portable expanded-catalog regression fixture if this private evidence must become CI input; preserve the old fixture unchanged.
3. Specify request/result mode provenance, stale-result rejection, cancellation/deadline behavior, busy-gate behavior, baseline recovery and rollback. Decide whether internal baseline diagnostics should be exposed or kept server-side to avoid bloating normal responses.
4. Implement only after an explicit reviewed decision; then test real service/API/MCP mode propagation and user selection end to end. Keep the original baseline path available. Packaging, deployment and production cutover remain separate Milestone 6 work.

No catalog, price database, combat formula, initial candidate limit, beam width, final scoring, production service/API/MCP route, account observation or deployment was changed by this review. Existing unrelated worktree changes were preserved. No commit or push was performed.
