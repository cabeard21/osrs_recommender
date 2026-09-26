# Weight tuning — procedure, corpus, and disagreement log

> **Historical record only.** Milestone 3 retired the weighted recommender, scoring
> profile, tuner, and golden corpus. The commands and procedures below no longer
> apply. See [current architecture](ARCHITECTURE.md).

> **Status: D1, D2 and D3 are RESOLVED (§16.3 step 5, human review, 2026-08-11).
> A fourth disagreement — D4, below — is open, and `content/scoring/profile.yaml` is still
> `version: 1`.**
>
> The review ruled: **D1** the six judgments were wrong, `cost_decay` stays at 0.5;
> **D2** a modelling gap, closed by a sixth §9.4 factor (`method_unlock`, SDD A30/D13);
> **D3** the judgment was wrong, and its wrongness ratifies A29?. All seven wrong judgments
> are deleted from the corpus, each with the ruling recorded in place. The factor is
> implemented, wired and tested, and the profile authors its weight at **`0.0`** — inert,
> since `0 · ln(f) = 0` — so v1 ranks exactly as it did.
>
> What blocks the profile write is [**D4**](#d4--the-tie-break-cannot-choose-between-two-100-profiles):
> on the corrected corpus **two** one-knob changes reach 100% agreement, `method_unlock: 0.1`
> and `effort_decay: 0.8`, they are the same distance from the shipped profile, and the
> search's tie-break resolves that by enumeration order rather than by anything meaningful.
> Which one ships is a §16.3 step 5 judgment of exactly the kind this document exists for.

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
| 2. Record pairwise expert preferences | `judgments:` in each scenario | done — 93 judgments, 52 pairwise (was 100/59; step 5 deleted seven) |
| 3. Grid search over weights, τ, κ subject to §9.6 | `tools/tune_weights.py` | done — six factors since A30 |
| 4. Maximize pairwise-agreement rate | the search objective | done — 98.1% → 100% on the corrected corpus |
| 5. **Review every disagreement manually** | §7 below | D1/D2/D3 done; **D4 open** |
| 6. Round to humanly interpretable values | the search's tie-break | done — and see D4, which is about that tie-break |
| 7. Persist with `version: 2` and `tuned_against_corpus` | *not done, deliberately* | blocked on D4 |

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

**Step 13b deleted seven judgments and no scenarios** (D1's six, D3's one), taking the corpus
from 100 judgments / 59 pairwise to **93 / 52**. Every scenario is kept, including the two the
deletions were about: 06 still decides the acquisition pair on its other judgments, and 19 is
the only place where `pvp_value` and `leverage` pull in opposite directions.

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
| `method_unlock` | 0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8 | A30. Finer at the bottom, and starting at **zero** — see the note below |
| `proximity` | 0.2 … 1.2 step 0.2 | |
| `effort_decay` | 0.2 … 1.4 step 0.2 | |
| `cost_decay` | 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0 | |
| `tau_hours` | 5, 10, 15, 20, 30 | `unknown_effort_hours` tracks it (§9.7) |
| `kappa_gp` | **pinned to 8M / 20M / 50M** | see [§5](#5-why-κ-is-not-tuned) |

Not tuned: `epsilon` (a floor so `ln(0)` cannot happen), `observation_aged_days` and the
`refresher` block (freshness policy — tuning §6.6's semantics with a §9.4 objective would be
a category error), and §9.9's `DISPLACEMENT_MARGIN` (it damps how fast the answer may change,
it does not shape what is recommended).

**`method_unlock`'s grid needs its own shape.** The factor is zero for every candidate that
does not change another candidate's §8 estimate — in this corpus, everything except Desert
Treasure I in seven of twenty scenarios. §9.4's ε floor therefore turns it into a near-uniform
`0.01 ^ w` multiplier on the rest of the field, and `100 ^ w` is 1.26× at `w = 0.05` but 40× at
`w = 0.8`. A 0.2 step would jump straight over the range where the factor is doing something
proportionate. Zero is on the grid because it is a real answer: if the search prefers it, A30
earns nothing here and the modelling gap is somewhere else.

Ties are broken toward the shipped profile, measured in grid units. That is where §16.3
step 6's *"humanly interpretable values"* is bought: several hundred grid points reach the
same agreement rate, and the one nearest the current defaults is both the most readable and
the smallest change to justify. **That tie-break acquired a bias the moment A30 was added**,
and D4 below is about the bias, not about the factor.

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

### 6.1 The first run (59 pairwise judgments, five factors) — historical

```
v1 (shipped, provisional per D4)          51/59 = 86.4%
best on grid, κ pinned to §9.6's presets  57/59 = 96.6%   cost_decay 0.5 → 0.1
best with κ free (reported, not proposed) 58/59 = 98.3%   κ_normal 30M
```

That run produced D1, D2 and D3. Its proposal — `cost_decay: 0.1` — was **rejected** by the
review, for the reason D1 spells out: at ε = 0.01 a weight of 0.1 caps the cost penalty at
0.63, so no price whatever can overcome a 1.6× relevance gap, and
`test_but_a_forty_fold_price_move_does_reorder_them` fails. Cost stays at **0.5**.

### 6.2 The second run (52 pairwise judgments, six factors) — current

Seven judgments deleted (D1's six, D3's one) and `method_unlock` added:

```
v1 (shipped, method_unlock inert at 0)    51/52 = 98.1%
best on grid, κ pinned to §9.6's presets  52/52 = 100.0%
best with κ free (§9.6 validation only)   52/52 = 100.0%  — and it picks the pinned κ anyway
```

κ stops being an argument: with the wrong judgments gone, the free search proposes
**8M/20M/50M**, the values §9.6 prints. §5's constraint costs nothing on the corrected corpus.

One judgment separates v1 from 100%, and it is D2's — scenario 10, `complete_desert_treasure_i
> train_magic_87_to_94`. **Two different single-knob changes close it**, and D4 is which:

| Profile | agreement | |
|---|---:|---|
| v1 as shipped (`method_unlock: 0`) | 51/52 (98.1%) | scenario 10 fails |
| v1 + `method_unlock: 0.1` | **52/52 (100%)** | closes it for A30's reason; holds to 1.0 |
| v1 + `effort_decay: 0.8` | **52/52 (100%)** | closes it by making the grind long; knife-edge |
| v1 + `effort_decay: 0.9` | 51/52 (98.1%) | breaks scenario 18 instead |
| v1 + both | 52/52 (100%) | |

The full `method_unlock` sweep with everything else at v1, which is the evidence D4 turns on:

| `method_unlock` | agreement | |
|---:|---:|---|
| 0 – 0.05 | 51/52 | the ε-floored term is too weak to move the pair |
| **0.1 – 1.0** | **52/52** | a plateau, not a point |

Against `effort_decay` swept the same way: 0.6 and 0.7 fail scenario 10, **0.8** passes, 0.9
and 1.0 fail scenario 18 (`complete_desert_treasure_i > refresh_nh_fundamentals` — a long quest
becomes worse than a short practice session). One grid step wide in each direction.

## 7. Disagreement log

§16.3 step 5: *"Review every disagreement manually — a disagreement is as likely to reveal a
bad judgment as a bad weight."*

Each disagreement below is also recorded in the corpus itself, as a `pending_review:` note on
the judgment. `test_judgments.py` xfails those **strictly**, so the suite is green today and
turns red the moment a retune resolves one — the marker is a claim about the current profile,
not a permanent exemption.

After Step 13b's review, **one** `pending_review:` remains — scenario 10's, D2's pair, which
the shipped `method_unlock: 0.0` still disagrees with. It is removed by the second commit,
whichever way D4 goes. Where a judgment was ruled *wrong* rather than *pending*, it is deleted
and the ruling is left in its place as a comment, so the corpus records the decision and not
merely its consequence.

---

### D1 — `buy_voidwaker` vs `buy_high_risk_gear` · **6 occurrences** · **RESOLVED: the judgments were wrong**

> **Ruling (2026-08-11): option 1. The six judgments are deleted; `cost_decay` stays at 0.5.**
>
> The decisive argument is the ceiling, stated below and worth restating as a rule: **§9.4's
> ε floor means `cost_decay`'s worst possible mark is `ε ^ w`.** At `w = 0.5` that is 0.10 and
> cost can still overrule a large relevance gap; at `w = 0.1` it is **0.63**, and no price —
> 85M, 850M, 3.4 *billion* — can overcome a 1.6× relevance advantage. The proposal did not
> rebalance cost against relevance, it switched cost off, and
> `test_but_a_forty_fold_price_move_does_reorder_them` is the corpus saying so rather than a
> flaky test. An app that cannot see price is worse than one that weighs it debatably.
>
> The six judgments were also one opinion written six times, which inflated their weight in
> the headline rate; scenario 12's opposing judgment is a claim about something more
> important — that an **explicit user preference** must visibly change the advice.
>
> Deleted from scenarios 03, 06, 07, 09, 13 and 15, each with the ruling recorded in place as
> a comment. Every scenario is kept; none of their other judgments is affected. Option 3
> (that `buy_high_risk_gear` advancing `deep_wildy_nh` at 0.50 is too generous) remains the
> *right* fix and is a content change outside tuning's scope — it is not foreclosed by this.

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

### D2 — `complete_desert_treasure_i` vs `train_magic_87_to_94` · 1 occurrence · **RESOLVED: a sixth factor**

> **Ruling (2026-08-11): the gap is real and is closed by a new §9.4 factor,
> `method_unlock` — SDD A30 and D13.** The judgment is right, `effort_decay: 0.8` satisfying
> it was a coincidence, and the amendment route this entry recommended was taken rather than
> the widening of `leverage`.
>
> **Derivation** (§9.4, §10.6): for candidate X with facts G, and every other *uncompleted*
> candidate Y — blocked ones included —
>
> ```
> reduction(X, Y) = clamp₀₁( (hours(Y) − hours(Y | G)) / hours(Y) )
> method_unlock(X) = max_Y reduction(X, Y),  normalized by the largest across the set
> ```
>
> Four choices inside that, each made the way the rest of the document makes them:
>
> * **Maximum, never sum** — A2's rule for `pvp_value` and §9.8's for refresher groups, for
>   the third time. Summing would let a candidate that shaves 10% off six grinds outrank one
>   that deletes 90% of the grind that matters.
> * **Normalized against the candidate set**, exactly as `leverage` is, so the factor is
>   comparative and a sparse corpus does not depress everyone.
> * **Floored at ε by the scorer, not at the source.** A candidate that unlocks no faster
>   method derives a genuine `0.0` and §6.10 persists it; `leverage` already behaves this way
>   and no special case was invented.
> * **Hours only, never GP.** `apply_facts` hands the player the granted *item*, so a GP delta
>   would let any acquisition "save" every other candidate the price of a thing it just bought
>   — a restatement of X's own cost, not an effect on Y. Hours are where §8.2 step 3's method
>   fallback lives, which is the mechanism this factor is about.
>
> Blocked candidates are in `Y`'s range because that is where the effect is largest: in
> scenario 02 DT1 both unblocks the Magic grind *and* makes it seven times shorter.
>
> Refreshers score a **real zero** and get no readiness-layer twin. A29? had to reinterpret
> `leverage` for refreshers because a permanent zero there was *wrong*; here it is simply the
> answer — a refresher grants no facts and §8 sizes nothing from practice freshness.
>
> On this corpus the factor is non-zero for `complete_desert_treasure_i` and nothing else, in
> seven of twenty scenarios, and it moves scenario 10's pair for any weight in `[0.1, 1.0]`.
> The reason line picks it up with no help — at `method_unlock: 0.8`, DT1 reads
> *"high PvP value (+4.50) · **makes later work far faster (+3.68)** · a long grind (+2.52)"*,
> generated from the log contributions like every other phrase (§9.5, anti-pattern 9).
>
> **What is still open is the weight**, not the factor: see D4.

### D2 (original entry) — the analysis the ruling above acts on

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

### D3 — `refresh_vengeance_fundamentals` vs `refresh_nh_fundamentals` · 1 occurrence · **RESOLVED: the judgment was wrong**

> **Ruling (2026-08-11): the judgment is deleted; scenario 19 is kept; A29? is ratified as
> written.** The engine's reasoning was correct. `consistent_overhead_prayers` is an
> `anti_pk` requirement, so the nh session genuinely serves the anti-PK roadmap too, and the
> judgment's premise — that it does not — was the error. A29?'s readiness-flip `leverage` is
> what surfaced that, which makes this the **strongest evidence in the corpus for ratifying
> A29? as written**: the one judgment it "loses" is a judgment that is wrong, and A29? is the
> reason it is wrong.
>
> The narrower claim the judgment was reaching for is not one of §16.1's three shapes — it is
> a statement about a *factor*, not a ranking — so it is asserted by a targeted test,
> `test_the_blend_inverts_pvp_value_for_the_one_member_group` in `tests/golden/test_judgments.py`.
> That test pins both halves: `pvp_value` inverts under the blend (§9.8's *"group size never
> drives rank"* is working), and `leverage` runs the other way (which is why the pair comes
> out as it does). Scenario 19 stays because it is the only place in the corpus where the two
> factors pull in opposite directions.

### D3 (original entry) — the analysis the ruling above acts on

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

### D4 — the tie-break cannot choose between two 100% profiles · **RESOLVED — option 1**

> **Ruling (§16.3 step 5, human review).** Ship **`method_unlock: 0.1`**, leave `effort_decay`
> at `0.7`. Persisted in `content/scoring/profile.yaml` v2, tuned against `b978d44`. The
> reasoning below stands as recorded — the plateau/knife-edge asymmetry is what decided it:
> a value that works across `[0.1, 1.0]` is a mechanism, and a value that works only at `0.8`
> is a coincidence.
>
> **The fourth item is deliberately deferred.** §4's tie-break bias is *not* being fixed now.
> It is documented, it is understood, and it costs nothing until a seventh factor is proposed
> — at which point it will misreport that factor as worthless in exactly the way it misreported
> this one. Whoever adds that factor should read this entry **before** trusting the search's
> output. Deferring is the reviewer's call, not an oversight.

**Scenario:** 10 `blocked_fast_method` again — the same pair D2 is about, now closeable two
different ways.

**What the search reports.** `method_unlock: 0.0`, `effort_decay: 0.8`, everything else
unchanged, 52/52. That looks like *"A30 earns nothing"* and it is **not** what happened.

**What actually happened.** On the corrected corpus, `v1 + method_unlock: 0.1` and
`v1 + effort_decay: 0.8` both reach 52/52. Measured in grid units they are the **same distance
from the shipped profile** — one 0.2-step each — so §4's tie-break cannot separate them, and
the winner is decided by `itertools.product`'s enumeration order. `method_unlock` varies more
slowly than `effort_decay` in that order, so the `method_unlock = 0` block is enumerated first
and records the distance that the later, equally-close point then fails to beat.

**The tie-break acquired a bias when A30 was added, and it is structural.** *"Break ties toward
the shipped profile"* was written when the factor set was fixed. A newly added factor is at
`0` in the shipped profile **by construction** — there is nowhere else it could have been — so
the metric systematically prefers not using it. That is a defect in the search, not a finding
about the factor, and it will recur for every future factor.

**The evidence says the two are not equivalent.** §6.2's sweeps:

* `method_unlock` closes scenario 10 across a **plateau**, every value from 0.1 to 1.0.
* `effort_decay: 0.8` closes it on a **knife-edge**: 0.7 fails scenario 10, 0.9 fails
  scenario 18 instead. It is the only value that works, which is what a coincidence looks
  like.
* D2's original entry made the same call from the mechanism rather than the numbers: raising
  `effort_decay` satisfies the judgment by making the 113-hour grind expensive, and credits
  the quest for nothing it does. A corpus whose blocked method sat behind a *short* grind
  would not reproduce it.

**Three ways to resolve, for the reviewer.**

1. **Ship `method_unlock: 0.1`, leave `effort_decay: 0.7`.** *This is the option this document
   recommends.* Smallest change that closes D2 for D2's reason, on the widest plateau, and it
   leaves `effort_decay` at the value the corpus has never argued against. 52/52.
2. **Ship `method_unlock: 0.2`.** Mid-plateau rather than at its edge, so a future scenario
   with a weaker method unlock still moves the ranking. Costs nothing on this corpus (52/52)
   and buys margin; the argument against is that 0.1 is the smaller claim and the corpus
   cannot currently distinguish them.
3. **Ship `effort_decay: 0.8`, leave `method_unlock: 0.0`.** The search's literal output.
   Reaches 52/52 with the factor inert — i.e. ships A30 as machinery nothing uses. Not
   recommended: it takes the coincidence over the mechanism, and re-opens D2 the moment the
   corpus gains a fast-method-behind-a-short-quest scenario.

A fourth item, independent of which is chosen: **§4's tie-break should stop measuring distance
on axes the shipped profile could not have had an opinion about.** Excluding a factor absent
from the origin profile, or measuring distance only over axes the origin authors, would remove
the bias without putting a thumb on the scale. That is a change to `tools/tune_weights.py` and
is deliberately *not* made here — it would change which profile the tool recommends, in the
same edit that decides which profile to ship.

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
| `tests/golden/scenarios/*.yaml` | remove each `pending_review:` the retune resolves — after Step 13b, exactly one remains, scenario 10's, and it is the one D4 decides |
| `docs/SDD.md` §9.7 | **already done** by Step 13b: the printed profile listing carries `method_unlock` and `unknown_effort_hours`. Only the *value* moves in the second commit |

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
* **A29?** (`leverage` for refreshers = `recommended_now` flips) — **ratified as written**,
  on D3's evidence. The one judgment A29? "loses" is a judgment that is itself wrong, and
  A29? is the reason it is wrong.
* **A30 — closed.** §9.4 had no factor for a candidate that reduces *another* candidate's
  cost. Now it does: `method_unlock`, §9.4/§9.7/§10.6 and decision D13. `magic_bursting`
  sitting behind DT1 was the corpus's example and it is not exotic — quest-gated training
  methods are everywhere in OSRS.
* **New, from D4** — §4's tie-break metric measures distance from the shipped profile on
  *every* axis, including axes a newly added factor occupies, where the shipped value is `0`
  by construction. It therefore systematically prefers not to use any new factor. Not an
  amendment candidate for the SDD (§16.3 does not specify a tie-break) but a defect in
  `tools/tune_weights.py` that will recur for every factor added after this one.
