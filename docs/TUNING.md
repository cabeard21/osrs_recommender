# Weight tuning — procedure, corpus, and disagreement log

> **Status: awaiting the human review that §16.3 step 5 requires.**
> The corpus and the search tool are complete and committed. `content/scoring/profile.yaml`
> is **unchanged** — still `version: 1`, `tuned_against_corpus: null`, which D4 names as a
> valid shipping state. The tuned profile is Step 13's *second* commit and it happens after
> someone reads [the disagreement log](#disagreement-log) below and decides each entry.

---

## 1. What this is for

SDD §9.4 ships five weights and calls them **"provisional priors, not tuned values"**. D4
explains why they could not be anything else: *"no principled way to solve for weights
before realistic scenarios exist. The design owes a definition of tuning success, not the
answer."*

§16.3 is that definition. This document records the corpus that supplies the scenarios, the
search that reads them, and — the part that matters — every place where the search and the
expert disagreed.

## 2. The procedure (§16.3)

| Step | Where it happens | State |
|---|---|---|
| 1. Build ~20 realistic scenarios | `tests/golden/scenarios/*.yaml` | done — 20 |
| 2. Record pairwise expert preferences | `judgments:` in each scenario | done — 100 judgments, 59 pairwise |
| 3. Grid search over weights, τ, κ subject to §9.6 | `tools/tune_weights.py` | done |
| 4. Maximize pairwise-agreement rate | the search objective | done — 86.4% → 96.6% |
| 5. **Review every disagreement manually** | §7 below | **← you are here** |
| 6. Round to humanly interpretable values | the search's tie-break | done |
| 7. Persist with `version: 2` and `tuned_against_corpus` | *not done, deliberately* | blocked on step 5 |

```bash
python -m pytest tests/golden -v          # assert the corpus against the shipped weights
python tools/tune_weights.py --report     # run the search, print the disagreements
python tools/tune_weights.py --report --quick   # coarse grid, ~3s, for a sanity pass
```

`tune_weights.py` has **no `--write` flag**, by design. A tool that applied its own answer
would have deleted the one step this procedure is built around.

## 3. The corpus

Twenty scenarios in `tests/golden/scenarios/`, each a `PlayerState` written in positives
plus a `RoadmapSelection` and the judgments recorded about it. `tests/golden/loader.py`
parses them; `tests/golden/test_judgments.py` and `tools/tune_weights.py` are its only two
consumers, and they share it precisely so the search optimizes the judgments the suite
asserts.

| # | Scenario | What it is for |
|---|---|---|
| 01 | `fresh_account` | the floor case: nothing unlocked, nothing owned, everything *observed* |
| 02 | `early_main_ancients_locked` | **§16.2's DT1-over-Voidwaker judgment**, on the account it names |
| 03 | `midgame_main` | the app's most common real state: the levels but not the unlock |
| 04 | `barrage_target` | **§16.2's 94-Magic-over-99-Strength judgment** |
| 05 | `low_prayer_protect_item` | **§16.2's Rigour-under-Protect-Item judgment**, below 25 Prayer |
| 06 | `maxed_pure` | the skill grinds are done; the acquisition pair decides everything |
| 07 | `unknown_bank` | **the tri-state scenario** — `scanned: none`, every `item:` leaf unknown |
| 08 | `all_stale` | both practice groups 200 days cold; the refresher's best case |
| 09 | `multi_roadmap` | §9.3's worked blend, `main_nh 0.75 / anti_pk 0.25` |
| 10 | `blocked_fast_method` | Ancients unlocked, DT1 open — `magic_bursting` unavailable |
| 11 | `anti_pk_focus` | the counter-case to 05: Rigour is correct *here* |
| 12 | `gp_sensitivity_high` | κ = 8M — the cheaper setup must win |
| 13 | `gp_sensitivity_low` | κ = 50M — relevance must win |
| 14 | `never_synced` | `last_sync_at IS NULL`: every leaf unknown, nothing blocked (A6, G3) |
| 15 | `aged_observations` | a 40-day-old bank scan — aged, not absent (A4, G2) |
| 16 | `near_barrage` | 93 Magic — proximity's near end |
| 17 | `far_from_barrage` | 75 Magic — proximity's far end |
| 18 | `mildly_stale_vs_progression` | 40 days stale against real progression: refresher must lose |
| 19 | `stale_vengeance_focus` | 08 inverted by roadmap blend alone; §9.8's "never group size" |
| 20 | `incumbent_hysteresis` | §9.9's margin must not become a veto |

### The three §16.2 pairwise judgments

All present, each in the account the SDD states it about, and
`test_the_sdd_named_judgments_are_all_present` fails if one is ever removed:

* *DT1 outranks buying a Voidwaker while Ancients are still locked* — 02, 03, 05, 10, 15, 18.
* *94 Magic outranks 99 Strength when the target capability requires Barrage* — 04, 07, 09,
  16, 17.
* *Rigour does not outrank Protect Item below 25 Prayer* — 01, 05, with 11 as the
  counter-case that keeps the corpus from simply always preferring Protect Item.

### The three §16.2 stability tests

In `tests/golden/test_stability.py`, each paired with its negative — a stability test that
only ever asserts *nothing changed* is satisfied by an engine that ignores its input.

| §16.2 claim | Positive | Negative |
|---|---|---|
| +10,000 Magic XP does not replace the top recommendation | order and score unchanged at 75 Magic (drift < 1%) | 75 → 94 Magic removes the candidate entirely |
| A 2% price move does not move a candidate to rank 1 | order unchanged both directions; no score moves > 10% | a 40× price rise does reorder the pair |
| A milestone crossing 30 days does not reorder the progression list | unchanged at 29 vs 31 days, and across the whole 30–90d band | crossing 30 days *does* produce a refresher |

### Judgments, not exact orderings (§16.1)

Only three judgment shapes exist, and the loader rejects any other key: `must_rank_above`,
`top_3_contains`, `must_not_be_top`. Nothing in the corpus can assert a full ranking. Two
near-tied candidates flip on noise, and a suite that fails for that reason trains its readers
to ignore it.

Pairwise judgments are read against the **full ranking** including deferred refreshers;
positional judgments against the **primary list**. §9.8's at-most-one-refresher rule is a
display policy applied after scoring, so asking "did the engine prefer A to B?" of the
truncated list would report a second refresher as unranked when the engine ranked it second.

A pair naming a candidate that did not rank — complete, or blocked — is **excluded from the
denominator**, never counted as agreement. Otherwise the search could buy a perfect rate from
candidates disappearing, and completion does not depend on the weights at all.

## 4. What the search tunes

`pvp_value` is **pinned at 1.0 and is not a free parameter**: scaling every weight by a
positive constant is a monotone transform of the score, so the vector has four degrees of
freedom, not five. Searching the fifth reports a family of numerically distinct profiles that
all rank identically.

| Parameter | Grid | Notes |
|---|---|---|
| `leverage` | 0.2 … 1.4 step 0.2 | |
| `proximity` | 0.2 … 1.2 step 0.2 | |
| `effort_decay` | 0.2 … 1.4 step 0.2 | |
| `cost_decay` | 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0 | |
| `tau_hours` | 5, 10, 15, 20, 30 | `unknown_effort_hours` tracks it (§9.7) |
| `kappa_gp` | **pinned to 8M / 20M / 50M** | see [§5](#5-why-κ-is-not-tuned) |

Not tuned: `epsilon` (a floor so `ln(0)` cannot happen), `observation_aged_days` and the
`refresher` block (freshness policy — tuning §6.6's semantics with a §9.4 objective would be
a category error), and §9.9's `DISPLACEMENT_MARGIN` (it damps how fast the answer may change,
it does not shape what is recommended).

Ties are broken toward the shipped profile, measured in grid units. That is where §16.3
step 6's *"humanly interpretable values"* is bought: several hundred grid points reach the
same agreement rate, and the one nearest the current defaults is both the most readable and
the smallest change to justify.

**The search does not call `recommend()` in its inner loop.** Every §9.4 factor except
`effort_decay` and `cost_decay` is profile-independent, and those two are closed forms over
an `Estimate` that §8 computes without a profile. So the engine runs once per scenario and
the inner loop is arithmetic — 10,290 points in 2.4s, or 277,830 with κ free in 67s. The
winner is then **re-verified against the real `recommend_run`** and the tool aborts if the
two rates differ.

## 5. Why κ is not tuned

§9.6's validation block permits any κ in `[1M, 250M]` with `high < normal < low`, and a
search reading only that constraint proposes **κ_normal = 30M**, which buys one extra
agreeing pair (58/59 rather than 57/59).

It must not be adopted. §9.6 *also* prints a worked table — a 10M purchase reads
0.29 / 0.61 / 0.82 across the three presets — that 8M/20M/50M is the unique solution to, and
Step 6 asserts it in `test_cost_decay_reproduces_the_worked_table`. Moving κ_normal falsifies
a table the SDD shows the user, and the plan's rule is explicit: *if tuning breaks a Step 4–6
invariant, the invariant wins.*

`tune_weights.py` therefore runs the search twice and reports both, so the reviewer can price
the constraint. **The κ-free result is evidence, not a proposal.** If the reviewer wants it,
the correct route is an SDD amendment to §9.6's table — not a profile edit.

## 6. Results

```
v1 (shipped, provisional per D4)          51/59 = 86.4%
best on grid, κ pinned to §9.6's presets  57/59 = 96.6%
best with κ free (reported, not proposed) 58/59 = 98.3%
```

**Proposed — not written:**

```yaml
scoring_profile:
  version: 2
  tuned_against_corpus: <hash of the tests/golden/ commit>
  tau_hours: 10                # unchanged
  kappa_gp: {high: 8000000, normal: 20000000, low: 50000000}   # unchanged (§5)
  observation_aged_days: 14    # unchanged
  unknown_effort_hours: 10     # unchanged
  weights:
    pvp_value: 1.0             # unchanged (numeraire)
    leverage: 0.8              # unchanged
    proximity: 0.6             # unchanged
    effort_decay: 0.8          # was 0.7
    cost_decay: 0.1            # was 0.5   ← the whole story is here
  refresher:
    max_in_primary_list: 1
    breadth_bonus_per_extra_member: 0.03
    breadth_bonus_cap: 0.10
```

Two numbers move. `effort_decay: 0.7 → 0.8` is uncontroversial and resolves D2 on its own;
**the entire argument is `cost_decay: 0.5 → 0.1`**, and §7's D1 is why this document does not
recommend adopting it as printed.

For comparison, the two intermediate profiles a reviewer is most likely to want:

| Profile | agreement | |
|---|---:|---|
| v1 as shipped | 51/59 (86.4%) | |
| v1 + `effort_decay: 0.8` only | 52/59 (88.1%) | resolves D2; leaves D1's six |
| the search's proposal (`cost_decay: 0.1`) | 57/59 (96.6%) | resolves D1's six; breaks scenario 12 |
| κ free, `cost_decay: 0.2`, κ_normal 30M | 58/59 (98.3%) | rejected — falsifies §9.6's table |

## 7. Disagreement log

§16.3 step 5: *"Review every disagreement manually — a disagreement is as likely to reveal a
bad judgment as a bad weight."*

Each disagreement below is also recorded in the corpus itself, as a `pending_review:` note on
the judgment. `test_judgments.py` xfails those **strictly**, so the suite is green today and
turns red the moment a retune resolves one — the marker is a claim about the current profile,
not a permanent exemption.

---

### D1 — `buy_voidwaker` vs `buy_high_risk_gear` · **6 occurrences** · unresolved

**Scenarios:** 03 `midgame_main`, 06 `maxed_pure`, 07 `unknown_bank`, 09 `multi_roadmap`,
13 `gp_sensitivity_low`, 15 `aged_observations`.

**The judgment.** At normal or low GP sensitivity, a Voidwaker (85M) should outrank an
AGS-plus-Ahrim's setup (~16.5M): it advances `deep_wildy_nh` 0.80 against 0.50, advances
`anti_pk` 0.60 against 0.35, and satisfies the same `any_of` on its own.

**What v1 does.** Ranks the gear set first, everywhere. The relevance ratio is 1.6×; the
`cost_decay` ratio at κ = 20M is 31×, and at weight 0.5 that is 5.6× against the Voidwaker.

**What the search does.** Drops `cost_decay` to 0.1 and resolves all six.

**Why it is not obviously right.** Dropping the weight to 0.1 *inverts scenario 12*
(`gp_sensitivity_high`, κ = 8M), where the recorded judgment is the opposite: a user who
asked for cost to weigh heavily must not be pointed at the corpus's most expensive purchase.
With κ pinned, the corpus contains no weight that satisfies both — the two judgments are
jointly unsatisfiable under the shipped κ presets, which is itself the most useful thing this
search found.

**There is a hard ceiling, and it is close.** §9.4 floors every factor at ε = 0.01, so the
worst mark cost can ever give a candidate is `0.01 ^ w`: 0.10 at `w = 0.5`, but **0.63 at
`w = 0.1`**. Below roughly `w = 0.15`, no price — 85M, 850M, 3.4 *billion* — can overcome a
1.6× relevance advantage. `test_but_a_forty_fold_price_move_does_reorder_them` fails under
the proposed weights for exactly this reason, and it is not a flaky test: it is the corpus
noticing that the proposal has effectively switched cost off.

**There is no middle setting.** Sweeping `cost_decay` with everything else at the proposed
values gives a cliff, not a curve:

| `cost_decay` | agreement | which side of D1 |
|---:|---:|---|
| 0.05 | 57/59 | the six resolve; scenario 12 breaks |
| 0.10 | 57/59 | the six resolve; scenario 12 breaks |
| 0.15 | 52/59 | the six break; scenario 12 holds |
| 0.20 – 0.30 | 53/59 | the six break; 12 and 13 both hold |
| 0.40 – 0.50 | 52/59 | the six break; 13 breaks too |

The transition is between 0.10 and 0.15 and it is total: no weight resolves *some* of the six.
D1 and scenario 12 are jointly unsatisfiable under the shipped κ presets, and the choice is
which of the two the app should be wrong about. A compromise value does not exist and should
not be looked for.

**Three ways to resolve, for the reviewer.**

1. **The judgments are wrong; keep `cost_decay: 0.5`.** 85M against 16.5M is a five-fold
   difference and κ = 20M means *"20M is where cost starts to hurt"*. The six are one
   judgment written six times, so the 86.4% headline over-weights them, while scenario 12's
   judgment is a different and arguably more important claim — that an **explicit user
   preference** must visibly change the advice. Adopting `effort_decay: 0.8` alone still
   improves agreement to 52/59 and resolves D2. *This is the option this document
   recommends.*
2. **The judgments are right; take `cost_decay: 0.1`.** The search's proposal, and the
   highest agreement available with κ pinned. Costs scenario 12, and — see the ceiling
   above — leaves `cost_decay` unable to penalise any price at all beyond 1.6×, which is
   close to deleting the factor. If this is chosen, ε should be revisited in the same
   change: the ceiling is a product of `ε ^ w`, and lowering ε to 1e-4 restores cost's
   authority at `w = 0.1`. That is an SDD §9.4 amendment, not a profile edit.
3. **Neither — the content is wrong.** `buy_high_risk_gear` advancing `deep_wildy_nh` at 0.50
   may simply be too generous for a setup strictly worse than a Voidwaker; at 0.35 the pair
   resolves on relevance and no weight has to move. Editing
   `content/candidates/acquisitions.yaml` is a content change, not a tuning one, and is
   outside Step 13's scope — but it is the only option that fixes the ordering for the right
   reason.

---

### D2 — `complete_desert_treasure_i` vs `train_magic_87_to_94` · 1 occurrence · **modelling gap, not a weight**

**Scenario:** 10 `blocked_fast_method`.

**The judgment.** With Ancients unlocked but DT1 still open, finish the quest first: §8.1's
`magic_bursting` requires *both*, so 87 → 94 Magic costs 113 hours at 35k/hr instead of 16
hours at 250k/hr. Doing the quest makes the same seven levels seven times cheaper, and DT1 is
a hard requirement of `ice_barrage_nh` regardless.

**What v1 does.** Ranks Magic first. `leverage` counts capability *status* flips, and DT1
flips none here — `ice_barrage_nh` still wants 94 Magic — so the quest scores 0 on the factor
that is supposed to express "this unblocks things".

**What the search does.** Resolves it, at `effort_decay: 0.8`, by making the 113-hour grind
expensive enough to fall behind. That is the right answer arrived at by the wrong route.

**Reading.** §9.4 has **no factor for "this candidate makes another candidate cheaper"**. The
engine cannot see the 250k/hr method waiting behind the quest; it can only see that the grind
in front of it is long. The judgment is right, the weight change that happens to satisfy it is
a coincidence, and a corpus without a 113-hour candidate would not have produced it.

**Recommendation.** Accept the resolution, and record the gap. This is a **candidate SDD
amendment** in the same family as A28?/A29? — either `leverage` gains a second meaning
(capabilities whose *estimate* would improve materially), or §9.4 gains a sixth factor with
its own authored weight. Do not treat `effort_decay: 0.8` as having solved it.

---

### D3 — `refresh_vengeance_fundamentals` vs `refresh_nh_fundamentals` · 1 occurrence · **bad judgment**

**Scenario:** 19 `stale_vengeance_focus`.

**The judgment as recorded.** Under a `anti_pk 0.9 / main_nh 0.1` blend, `vengeance_pvp`
blends to 0.83 while `deep_wildy_nh` falls to 0.39, so the one-member vengeance group should
beat the three-member nh group — §9.8's *"group size never drives rank"*.

**What both v1 and the tuned weights do.** Keep `refresh_nh_fundamentals` ahead. This is the
only judgment no point on the grid satisfies.

**Reading — the judgment is what is wrong.** `pvp_value` does invert exactly as predicted
(0.83 against 0.64), so §9.8's rule is working. What carries the nh group is `leverage`:
restoring it flips **three** capabilities' `recommended_now`, the vengeance group one. And
that is correct, because `consistent_overhead_prayers` is a requirement of `anti_pk` — the
very capability this roadmap weights at 1.00. The nh session serves the anti-PK player too;
the judgment assumed it did not.

This is A29?'s derivation (refreshers count readiness flips rather than status flips) working
as designed, and it is the strongest evidence in the corpus for ratifying A29? as written.

**Recommendation.** Delete the judgment and replace it with the narrower claim it was reaching
for: that `pvp_value` alone inverts under the blend. Keep scenario 19 — it is the only place
in the corpus where the two factors pull in opposite directions.

---

## 8. What the second commit must touch

Recorded here because it crosses a unit boundary the plan does not name. Persisting the tuned
profile is **not** a one-file change: three assertions in `tests/content/test_seed_corpus.py`
(Step 2c's directory) pin the shipped profile and will fail.

| File | Change |
|---|---|
| `content/scoring/profile.yaml` | `version: 2`, `tuned_against_corpus`, the tuned weights |
| `tests/content/test_seed_corpus.py::TestShape::test_the_shipped_corpus_validates` | `version == 1` → `2` |
| `tests/content/test_seed_corpus.py::TestScoringProfile::test_matches_the_sdd_defaults` | the weight assertions, and rename — it no longer matches §9.7's printed defaults |
| `tests/content/test_seed_corpus.py::TestScoringProfile::test_is_declared_untuned` | delete or invert |
| `tests/golden/scenarios/*.yaml` | remove each `pending_review:` the retune resolves |
| `docs/SDD.md` §9.7 | the printed profile listing, if the amendment route in D2 is taken |

Note the ordering §16.3 step 7 forces: `tuned_against_corpus` names the corpus commit, so the
corpus must be committed first and the profile second. That is why Step 13 is two commits and
not one.

## 9. Open amendment candidates this exercise touched

* **A25?** (`manual` / `derived` / `osrs_wiki_prices` have no §7.4 precedence) — untouched. No
  scenario in this corpus mixes sources within one fact, because `PlayerState` arrives already
  merged. Tuning cannot inform it; it needs a merge-layer corpus.
* **A28?** (where `group_urgency` enters the §9.4 score) — the corpus **supports** the shipped
  choice. Spending urgency as `proximity` is what makes 08 and 18 come out differently, and no
  weight vector on the grid produces a sensible ranking for both if urgency is removed. Nothing
  here argues for a sixth factor.
* **A29?** (`leverage` for refreshers = `recommended_now` flips) — see D3. The one judgment
  A29? "loses" is a judgment that is itself wrong, and A29? is the reason it is wrong. This is
  the strongest evidence available for ratifying it as written.
* **New, from D2** — §9.4 has no factor for a candidate that reduces *another* candidate's
  cost. `magic_bursting` sitting behind DT1 is the corpus's example, and it is not exotic:
  quest-gated training methods are everywhere in OSRS. Nearest existing kin is A28?.
