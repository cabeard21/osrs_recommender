# Proposal: `advances` weights for the generated corpus

> **Historical proposal.** The weighted recommendation and generated candidate
> corpus were retired in Milestone 3. See [current architecture](../ARCHITECTURE.md).

**Status:** §§1–3 **applied**. §4 (diaries) accepted as "no weights". §5 (the blocked-row
path) remains open — see the note at the end.

Steps 4–6 added 258 quest and diary candidates, all with `advances: {}`. They rank at the
ε floor and break ties alphabetically, so the bottom of the list is arbitrary. `advances`
is the one input §10.6 reserves for a human, which is why this is a proposal rather than a
commit.

The short version: **the corpus supports far fewer weights than expected — two candidates,
not twenty — and two of the four changes below are bug fixes rather than editorial calls.**

---

## What the corpus actually asks for

The five capabilities were walked for every `quest:` and `unlock:` leaf they gate on:

| capability | quest leaves | unlock leaves |
|---|---|---|
| `ice_barrage_nh` | `desert_treasure_i` | `ancient_magicks` |
| `vengeance_pvp` | `lunar_diplomacy` | `spellbook_lunar` |
| `budget_nh` | — | `ancient_magicks` |
| `deep_wildy_nh` | — | — |
| `anti_pk` | — | — |

Two quests. That is the entire surface on which a quest can advance anything in this
corpus by its own requirements, and one of them (`desert_treasure_i`) is already
hand-weighted.

**No capability gates on any `diary_*` or `ca_*` unlock.** Checked mechanically, not by
eye. See "Diaries" below.

---

## 1. Bug: `complete_lunar_diplomacy` does not grant the spellbook

Not a weighting question — the content is wrong today.

```yaml
# content/candidates/generated/quests.yaml — as generated
grants_facts:
  quest: lunar_diplomacy
```

Lunar Diplomacy grants the lunar spellbook, and the plugin already reports it that way:
`UnlockCollector.questGranted` derives `spellbook_lunar` from the quest's completion. The
authored DT1 candidate sets the precedent and its own comment says why this matters:

> Two facts, because the quest reward is the point: the unlock is what other content gates
> on, and a `quest:` leaf alone would leave `leverage` unable to see it.

**Proposed** — and note this cannot be generated, since the quest→unlock mapping lives in
the plugin's `QUEST_GRANTED_UNLOCKS` table, not in the wiki dump. It needs to move to an
authored file:

```yaml
- id: complete_lunar_diplomacy
  name: Complete Lunar Diplomacy
  kind: quest
  source: authored          # moved out of generated/, so --check stops owning it
  advances:
    vengeance_pvp: 0.90     # see §2
  requires:
    all_of:
      - skill: {crafting: 61}
      - skill: {defence: 40}
      - skill: {firemaking: 49}
      - skill: {herblore: 5}
      - skill: {magic: 65}
      - skill: {mining: 60}
      - skill: {woodcutting: 55}
      - quest: the_fremennik_trials
      - quest: lost_city
      - quest: rune_mysteries
      - quest: shilo_village
  completion:
    quest: lunar_diplomacy
  grants_facts:
    all_of:
      - quest: lunar_diplomacy
      - unlock: spellbook_lunar
```

---

## 2. The one real weight: `complete_lunar_diplomacy` → `vengeance_pvp: 0.90`

**Calibrated against the corpus's own authored example rather than a rule I invented.**
A pure "fraction of leaves satisfied" rule would give 0.50 — and it would also give DT1
0.50, where the corpus authored 0.90. So the existing convention is not leaf-counting; the
enabling unlock counts for more than its share. DT1's comment says so directly: it
advances three capabilities "by very different amounts, because two of them need far more
than Ancients before they are usable."

The two cases are structurally identical:

| | DT1 → `ice_barrage_nh` (authored) | Lunar → `vengeance_pvp` (proposed) |
|---|---|---|
| capability leaves | 4 | 4 |
| satisfied by this quest | quest + enabling unlock | quest + enabling unlock |
| remaining gap | Magic 94, one item | Magic 94, one milestone |
| **weight** | **0.90** | **0.90** |

Same shape, same number. If you think DT1's 0.90 is too high, both should move together —
that is the point of anchoring to it.

Lunar Diplomacy advances nothing else: `anti_pk` and `deep_wildy_nh` gate on milestones and
items it does not touch.

---

## 3. Bug: `complete_desert_treasure_i` understates its requirements

The authored candidate carries a rationale that Step 4 made obsolete:

> Its quest prerequisites … are deliberately not listed: quests/ declares only the quests
> this corpus's capabilities gate on, and §10.7 rejects a `quest:` leaf naming an
> undeclared id.

All 211 quests are now declared, so the constraint is gone — but the omission remains, and
**DT1 currently shows as available to an account that cannot start it.** The generator
would have produced these seven; they are proposed as an addition to the authored entry,
leaving its `advances` untouched:

```yaml
      - quest: the_dig_site
      - quest: temple_of_ikov
      - quest: the_tourist_trap
      - quest: troll_stronghold
      - quest: priest_in_peril
      - quest: waterfall_quest
      - quest: plague_city
```

---

## 4. Diaries: **propose no weights at all**

All 48 stay at `advances: {}`, and this is a recommendation rather than a deferral.

No capability in this corpus gates on a diary or combat-achievement unlock — verified by
walking every requirement tree. Assigning a diary a weight would therefore be asserting a
relationship the content does not contain, which is the one thing §10.6 forbids, and no
amount of care in choosing the number fixes that.

If diaries *should* matter — and the Wilderness diary's obelisk teleports and the Ardougne
cloak plausibly do for PvP — the correct change is **a capability that gates on them**, at
which point weights derive from it in the normal way. That is a corpus design decision, not
a weighting one, and it should be its own step.

---

## 5. Open question: the path to a weighted-but-blocked goal

Once Lunar Diplomacy has weight, it will rank — and then be **blocked**, because the
account has none of its four prerequisite quests. The Blocked section shows only a name:

```python
class BlockedRecommendationRow:
    candidate_id: str
    name: str
```

So the user gets "Complete Lunar Diplomacy" with no indication of what blocks it or what to
do next. Three ways to close that:

| | change | cost | asserts priority? |
|---|---|---|---|
| **(a)** | weight the 4 prerequisite quests too | content only | **yes** — invents an ordering the derivations should produce |
| **(b)** | extend `leverage` to count candidate-unblocking, not just capability flips | engine + **weight retune** + §16.3 golden review | no |
| **(c)** | show blockers on blocked rows, as the Capabilities page already does | UI only | no |

**Recommendation: (c).** It is the cheapest, it changes no scoring, and it closes what is
really a §15 gap rather than a weighting one — the Capabilities page has shown blockers
since Step 10 of the original build, and the Recommendations page simply never did. (b) is
worth doing eventually and is the honest fix for quest-unblocks-quest generally, but it
needs a retune and human review of every judgment that moves.

---

## Summary of what would change

| file | change | kind |
|---|---|---|
| `content/candidates/quests.yaml` | add `complete_lunar_diplomacy`, authored, weight 0.90 | fix + weight |
| `content/candidates/quests.yaml` | add DT1's 7 quest prerequisites | fix |
| `content/candidates/generated/quests.yaml` | regenerate — Lunar now skipped as authored | mechanical |
| everything else | unchanged | — |

Two candidates weighted out of 258. That is not a shortfall in the drafting; it is what the
corpus's five PvP capabilities actually reference. Growing the number means growing the
capabilities, not the weights.

---

## Applied — what actually changed

Suite 1334 green; `ruff`, `mypy` clean; `--check` no drift.

**Corpus 337 → 365 candidates**, and the +28 is not the weight — it is the band generator
doing what it is documented to do. Lunar Diplomacy's authored `requires` introduced
Crafting, Herblore and Mining as corpus-referenced skills, plus boundary levels at 61, 60,
55, 49 and 40, so `corpus_skill_levels` picked them up and emitted bands ending exactly at
Lunar's gates. Bands 71 → 99.

**One correction to §3 of this proposal.** It claimed DT1 "currently shows as available to
an account that cannot start it". True in general; **not true for this account** — Rehvun
is Thieving 26 / Magic 35 / Slayer 9 against DT1's 53 / 50 / 10, so the skill gate already
blocked it. The missing quest prerequisites were a latent bug that would bite an account
with the levels and not the quests, and the fix is still right, but nothing visible changed
for this account.

**The 0.90 weight is correct and currently latent.** `complete_lunar_diplomacy` is blocked
(four prerequisite quests, seven skill gates), so it sits in the Blocked section and its
weight has no effect on the ranked list yet. It will the moment the prerequisites clear.

**The path is on screen, by construction rather than by derivation.** The top 12 now shows
*Train Woodcutting to 55*, *Train Mining to 60* and *Train Crafting to 61* — which are
exactly Lunar Diplomacy's skill gates. Worth being precise about why: those bands rank on
their own `proximity` and `effort_decay`, **not** on Lunar's weight, and they would rank
identically if Lunar had none. What the weight bought was the *boundaries* existing at all.
So §5's open question stands — a weighted, blocked goal still shows no explicit path, and
the incidental one here is a happy accident of where the band edges fell.

Purely as a side benefit, the arbitrary alphabetical quest noise (*Complete A Porcine of
Interest* and friends) is gone from the top 12 on both roadmaps, displaced by bands that
are real next actions.
