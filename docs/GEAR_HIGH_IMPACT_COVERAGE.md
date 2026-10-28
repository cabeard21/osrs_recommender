# High-impact Gear and purchase coverage

Assessment: October 27, 2026, America/Chicago. This is a targeted continuation of
[recommendation-quality acceptance](GEAR_RECOMMENDATION_QUALITY_ACCEPTANCE.md),
[Catalog Phase 2](GEAR_CATALOG_COVERAGE_PHASE_2.md), and the independent
[search correction experiment](GEAR_SEARCH_QUALITY_CORRECTION.md).

## Scope and evidence

Ten exact physical items receive independent ordinary-effects review. Seven new
authored entries supply requirements/acquisition; the three existing Mixed hide
entries retain their independently verified rules. Only the generic unreviewed
effect marker changes in ten physical catalog rows. No bonus, identity, slot,
compatibility field, search limit, scoring rule, or final tie-break changes.

All measurements use the acceptance account's read-only frozen database, not the
older development account: snapshot
`dab5fd94ac2f1af7df69947250f45661ee9d536acdd91fd172f2aec89f5b0bca`,
database SHA-256
`5ee533dcb241a26ca12e681793ccf38a918b1771def91d28fab7f780fd240cda`.
Its latest account sync is October 27 at 14:19:38 UTC; Attack/Strength/Ranged are
60, Defence 56, Magic 55, Prayer 46. These are persisted observations, not a new
live in-game check. No Pi connection or production database mutation occurred.

The before, catalog-only, and catalog-plus-price stages share the clock
`2026-10-28T03:00:35.437377+00:00`. This permits the new price observations without
using future quotes at the older acceptance clock. All seven before-stage selected
solutions exactly reproduce acceptance, including their loadouts and scores.
The account, requests, and existing quotes are otherwise frozen.
Physical catalog revision changes from
`b8cb3949f6707e5604fea77b59dea84d80782054ad7f8d81d03dde4af87d6b67`
to `7ef875fb452c389eef0460cd76c2f6c177a4f5f27c5b26468f8505675798f8f7`.

Pinned item revisions and content hashes are retained in
[`gear_high_impact_source.json`](../tests/fixtures/gear_high_impact_source.json).
Every numeric field was compared with each Wiki page and the independently pinned
[calculator export](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json).
Private source captures, before inputs, scenario responses and price observations
remain in ignored [`.tmp/gear-high-impact/`](../.tmp/gear-high-impact/).

## Exact item review

| Physical ID / pinned source | Wear requirements | Acquisition / tradeability |
| --- | --- | --- |
| 7460 [Rune gloves](https://oldschool.runescape.wiki/w/Special:PermanentLink/15213298) | Daero training **or** Defeating the Culinaromancer | Untradeable; seven RFD subquests unlock purchase from the chest |
| 7459 [Adamant gloves](https://oldschool.runescape.wiki/w/Special:PermanentLink/15213297) | Defence 13 | Untradeable; six RFD subquests unlock chest purchase |
| 7458 [Mithril gloves](https://oldschool.runescape.wiki/w/Special:PermanentLink/15213296) | No additional skill/quest wear gate (Defence 1) | Untradeable; five RFD subquests unlock chest purchase |
| 29280 [Mixed hide top](https://oldschool.runescape.wiki/w/Special:PermanentLink/15271149) | Ranged 60, Defence 50 | Tradeable; crafting or player trade |
| 29286 [Mixed hide boots](https://oldschool.runescape.wiki/w/Special:PermanentLink/15344258) | Ranged 60, Defence 50 | Tradeable; crafting or player trade |
| 29289 [Mixed hide cape](https://oldschool.runescape.wiki/w/Special:PermanentLink/15350309) | Ranged 60, Defence 50 | Tradeable; crafting or player trade |
| 2501 [Red d'hide body](https://oldschool.runescape.wiki/w/Special:PermanentLink/15356812) | Ranged 60, Defence 40; no Dragon Slayer I wear gate | Tradeable; crafting or player trade |
| 2495 [Red d'hide chaps](https://oldschool.runescape.wiki/w/Special:PermanentLink/15356693) | Ranged 60; no Defence/quest wear gate | Tradeable; crafting or player trade |
| 6733 [Archers ring](https://oldschool.runescape.wiki/w/Special:PermanentLink/15355140) | No skill/quest wear gate | Tradeable; Dagannoth Supreme drop or player trade |
| 2577 [Ranger boots](https://oldschool.runescape.wiki/w/Special:PermanentLink/15379383) | Ranged 40; no quest gate | Tradeable; medium clues or player trade |

Rune gloves do **not** become wearable merely because Defence is at least 34,
Monkey Madness I is complete, or the physical gloves are observed. The existing
requirement AST represents `daero_training_complete` OR
`recipe_for_disaster_culinaromancer`. Missing training evidence remains unknown.
This adds an understood requirement key, **not automatic training detection**.
The frozen account cannot establish either branch and remains blocked. No account
unlock was fabricated. The other seven observed reviewed items pass wear checks.

RFD subquest counts above are acquisition conditions, not extra wear gates on
already-owned Mithril/Adamant gloves. The current purchase model does not turn
untradeable chest rewards into market purchases. Mixed hide crafting/Hunter/quest
access likewise does not impose a wear gate on traded equipment.

Vectors below are stab, slash, crush, magic, ranged. All ten pieces have ranged
strength 0, magic damage 0%, prayer 0, are nonweapons, and occupy one exact slot.
They do not add attack profiles, change weapon speed, or bypass handedness/ammo
validation. Tests compare all 140 numeric bonus fields.

| ID | Slot | Attack vector | Defence vector | Melee strength |
| --- | --- | --- | --- | ---: |
| 7460 | hands | 8,8,8,4,8 | 8,8,8,4,8 | 8 |
| 7459 | hands | 7,7,7,4,7 | 7,7,7,4,7 | 7 |
| 7458 | hands | 6,6,6,3,6 | 6,6,6,3,6 | 6 |
| 29280 | body | 4,-2,-3,-15,27 | 33,39,43,30,32 | 2 |
| 29286 | feet | 0,0,0,-10,5 | 4,5,6,3,3 | 2 |
| 29289 | cape | 0,0,0,-15,5 | 2,2,2,5,1 | 1 |
| 2501 | body | 0,0,0,-15,25 | 26,34,36,36,45 | 0 |
| 2495 | legs | 0,0,0,-10,14 | 15,18,22,18,20 | 0 |
| 6733 | ring | 0,0,0,0,4 | 0,0,0,0,4 | 0 |
| 2577 | feet | 0,0,0,-10,8 | 2,3,4,2,0 | 0 |

The reviewed pages describe no conditional outgoing proc, target multiplier or set
damage bonus for these physical forms. Mixed hide's hunter-spear synergy is
ordinary bonuses, not an invented set multiplier. Imbuing Archers ring, crafting
a Venator ring, and converting Ranger boots to Pegasian boots produce distinct
items; none inherits this review or an ownership/price alias. Related Black gloves
7457, Mixed hide legs 29283 and Archers ring (i) 11771 retain their prior blockers.

## Purchase prices and provenance

The small pricing batch covers the two new purchase reviews, the previously
reviewed dark/light Mystic robes, Enchanted hat and gold Climbing boots, plus
existing blue Mystic and the five tradeable owned items above. No additional
equipment family is approved. This addresses the explicit queue without adding
items whose wear rules or conditional mechanics still require a separate review.

The six Phase 2 purchase forms retain their independent pinned reviews:
[4101](https://oldschool.runescape.wiki/w/Special:PermanentLink/15322453),
[4103](https://oldschool.runescape.wiki/w/Special:PermanentLink/15322426),
[4111](https://oldschool.runescape.wiki/w/Special:PermanentLink/15250408),
[4113](https://oldschool.runescape.wiki/w/Special:PermanentLink/15250409),
[7400](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324861), and
[23413](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324095).
The robes/hat require Magic 40 and Defence 20. Gold Climbing boots require Death
Plateau completion even when bought from another player. All six are tradeable;
this task supplies missing quotes, not new approvals for them.

Prices use the existing `resolve_prices`, `PricesClient`, `DatabasePriceCache`,
`persist_prices`, `DatabaseGearPrices`, and `resolve_price` path. The existing
12-hour fetch TTL is unchanged; no forced refresh occurred. Ten missing exact-ID
quotes were fetched from the [OSRS Wiki price API](https://prices.runescape.wiki/api/v2/osrs/latest).
Seven existing records were reused with their original timestamps. Acquisition
uses high/low/cached/static/unknown policy as before; trade time determines
confidence. New authored tradeable rows use live pricing, 30-day staleness and
**no static fallback**. Existing Mixed hide hints remain unchanged and were not
used instead of available market quotes. Missing quotes never mean zero cost.

Ten missing rows were also populated in the **local development** `tracker.db`
using existing persistence, increasing price rows from 206 to 216. All other price
rows and every account table were verified logically unchanged; `quick_check`
passed. A WAL-aware backup and exact affected-ID/timestamp evidence are retained
in `pricing/local-persistence.json` and its companion backup. This did not refresh
the development account. Existing sync scope discovers authored tradeable IDs
after content reload; no sync wiring change is necessary.

All ten newly fetched quotes below use the high-price leg, provider `osrs_wiki`,
source `live`, with high confidence at evaluation. Dates/times are UTC on October
28, 2026. Full microsecond fetch times and both trade legs are in `pricing/quotes.json`.

| Exact ID | Item | GP | High trade time | Fetch time (milliseconds) |
| --- | --- | ---: | --- | --- |
| 2495 | Red d'hide chaps | 2,656 | 02:59:41 | 03:00:35.062 |
| 2501 | Red d'hide body | 5,796 | 02:59:40 | 03:00:35.143 |
| 2577 | Ranger boots | 32,768,334 | 02:51:13 | 03:00:35.160 |
| 4101 | Mystic robe top (dark) | 72,499 | 02:46:34 | 03:00:35.179 |
| 4103 | Mystic robe bottom (dark) | 49,449 | 02:55:01 | 03:00:35.196 |
| 4111 | Mystic robe top (light) | 75,000 | 02:55:06 | 03:00:35.227 |
| 4113 | Mystic robe bottom (light) | 48,120 | 01:25:04 | 03:00:35.245 |
| 6733 | Archers ring | 1,859,790 | 02:51:30 | 03:00:35.263 |
| 7400 | Enchanted hat | 8,359 | 01:23:35 | 03:00:35.282 |
| 23413 | Climbing boots (g) | 50,000 | 02:57:09 | 03:00:35.303 |

Reused cached high quotes were 4089=9,099; 4091=70,968; 4093=47,258;
4097=6,000; 29280=18,000; 29286=17,600; 29289=19,398 GP. Their October 27
fetch times range from 15:40:46.304401 through 22:41:03.648380 UTC; their trade
times range from 15:37:02 through 22:37:45 UTC. These seven frozen acceptance-cache
records were reused for measurement, not overwritten into the development cache.
Archers ring fits only the 5M budget; Ranger boots fit neither budget. Other scoped
quotes are individually under 1M. Individual affordability does not establish
affordability of a complete purchase union. Owned equipment costs zero additional
GP. Quotes are observations, not guaranteed market fills.

## Before/after coverage

Accepted observed catalog equipment support rises **81 to 88 /286**. The acceptance
report's fixed positive-combat-bonus cohort, including defence/prayer, rises
**81 to 88 /215**. An additional fixed cohort with any positive *offensive* attack,
strength or magic-damage bonus rises **65 to 72 /149**. These denominators are
frozen before review and are not the historical October 19 Phase 2 denominator.

The scenario-oriented counts below reproduce the acceptance report's exact
concrete membership: weapons must support the requested style, ranged ammunition
must contribute ranged strength, and other pieces must contribute positive style
attack or relevant strength/damage. Purchase universes include potentially relevant
unowned forms except known-untradeable rows, even if their metadata/prices are
unknown. Numerators require wear, supported ordinary evaluation and individual
budget eligibility; retention and final selection are separate.

| Scenario / role | Fixed denominator | Before eligible | Catalog-only eligible | With prices eligible |
| --- | ---: | ---: | ---: | ---: |
| Owned Slash | 55 | 17 | 22 | 22 |
| Owned Ranged | 62 | 32 | 39 | 39 |
| Owned Magic | 48 | 24 | 26 | 26 |
| Slash +1M | 596 | 21 | 26 | 27 |
| Slash +5M | 596 | 22 | 27 | 28 |
| Ranged +5M | 845 | 40 | 47 | 48 |
| Joint melee | 55 | 17 | 22 | 22 |
| Joint ranged | 62 | 32 | 39 | 39 |

The pricing-only Slash count increment is gold Climbing boots; the Ranged increment
is Archers ring. Mystic/Enchanted pricing improves supported purchase coverage even
though the representative Magic request is owned-only. Joint role counts overlap.

Among **unowned positive-offensive-bonus items** with satisfied wear, tradeability
and clear ordinary effects, the metadata-eligible count rises **21 to 23** with
Archers ring and Ranger boots. Priced coverage rises **15 to 23**; individually
within 1M rises **14 to 20**, and within 5M **15 to 22**. This is a separate
cross-style availability count, not a retained-pool or whole-loadout count.

- **Newly eligible observed:** `7458,7459,29280,29286,29289,2501,2495` (seven).
- **New purchase metadata approvals:** `6733,2577`; the latter remains over budget.
- **Newly priced unowned supported items:** `2577,4101,4103,4111,4113,6733,7400,23413`
  (eight). Red body/chaps supply two further new quotes but are already owned.
- **Still blocked by account facts:** Rune gloves `7460`, whose ordinary effects
  are reviewed but training/final-subquest wear evidence is unknown. Rune crossbow
  `9185` retains the account's known-unmet Ranged requirement.
- **Still blocked by unsupported mechanics/review:** the prior Crystal bow `23983`
  charge-state and Dragonstone bolts (e) `9244` enchanted-effect limitations remain.
  No new charge, proc, set, special-attack or encounter model was introduced.

## Updated acceptance recommendations

Requests remain the acceptance generic ordinary target (Defence/Magic 80, zero
defence bonuses), accurate Slash, rapid Ranged, and accurate standard Fire Bolt.
Singles retain eight action points; joint retains four actions per edge and equal
role weights. All reserve twelve supply slots. No locks, exclusions or overrides
were added to the measured requests.

| Scenario | Before DPS | Catalog-only DPS | Final DPS | Final additional GP |
| --- | ---: | ---: | ---: | ---: |
| Owned Slash | 2.642031114342 | 2.670865566737 | 2.670865566737 | 0 |
| Owned Ranged | 2.915472964253 | 2.949200995744 | 2.949200995744 | 0 |
| Owned Magic | 1.438853910028 | 1.442765429029 | 1.442765429029 | 0 |
| Slash +1M | 2.659550762100 | 2.670865566737 | 2.670865566737 | 0 |
| Slash +5M | 2.659550762100 | 2.670865566737 | 2.670865566737 | 0 |
| Ranged +5M | 2.915472964253 | 2.949200995744 | 2.961841467505 | 1,859,790 |
| Joint four actions | 2.710305653123 | 2.806785388223 | 2.806785388223 | 0 |

All selected complete assignments pass the existing exact solution validator,
including wear/ownership, compatible equipment, budget union, transitions and
inventory. Only Ranged +5M purchases anything: physical Archers ring `6733`,
observed unowned, not an assumed-owned form. Every other selected item is observed
owned. No improvement percentage against the unsupported worn Graceful baseline
is asserted.

| Slot | Final Owned Slash | Final Owned Ranged | Final Owned Magic |
| --- | --- | --- | --- |
| weapon | Dragon scimitar 4587 | Magic shortbow (i) 12788 | Ancient staff 4675 |
| shield | Mooleta 33101 | empty | Book of Darkness 12612 |
| ammunition | Peaceful blessing 20226 | Amethyst arrow 21326 | empty |
| head | Warrior helm 3753 | Archer helm 3749 | Farseer helm 3755 |
| cape | Mixed hide cape 29289 | Mixed hide cape 29289 | Ardougne cloak 1 13121 |
| neck | Amulet of fury 6585 | Amulet of glory 1704 | Amulet of glory 1704 |
| body | Fighter torso 10551 | Mixed hide top 29280 | Mystic robe top 4091 |
| legs | Zamorak monk bottom 1033 | Rangers' tights 23249 | Mystic robe bottom 4093 |
| hands | Adamant gloves 7459 | Ranger gloves 19994 | Adamant gloves 7459 |
| feet | Granite boots 21643 | Mixed hide boots 29286 | Wizard boots 2579 |
| ring | Berserker ring (i) 26770 | Explorer's ring 1 13125 | Explorer's ring 1 13125 |

Both budget Slash results use the Owned Slash set with Black platebody `1125`
and empty ammunition instead of Fighter torso/blessing. Ranged +5M changes only
the Owned Ranged ring to `6733`. This is ordinary DPS, not an endorsement of losing
Ava's ammunition-saving utility; that utility is outside this objective.

Joint shares Amethyst arrows `21326`, Mixed hide cape `29289`, Fury `6585`,
Red d'hide body `2501`, Rangers' tights `23249`, Mixed hide boots `29286`, and
Berserker ring (i) `26770`. Melee uses Dragon scimitar/Mooleta `4587/33101`, Warrior
helm `3753`, Adamant gloves `7459`; Ranged uses Magic shortbow (i) `12788`, Archer
helm `3749`, Ranger gloves `19994`. Per-role DPS is **2.670865566737 /2.942705209708**.
The complete solution carries 14 distinct IDs, uses three/four directed actions,
and peaks at four gear inventory slots while preserving twelve reserved slots.

## Retention, performance and remaining search losses

Direct single-role substitution checks accept all seven newly eligible owned IDs.
The six Phase 2 newly priced forms also pass exact single-role budget checks even
when omitted by initial pools. Archers ring passes 5M and fails 1M; Ranger boots
fail both budgets. Rune gloves fail wear validation in every request. Item-level
support does not guarantee a legal joint replacement: changing only the joint body
to Mixed hide top or legs to Red chaps can violate the four-action complete plan.

Mixed hide top `29280` is eligible but omitted from the single Slash/budget Slash
initial pools; it is retained for Ranged and joint. Newly priced Mystic/Enchanted
pieces and gold boots are eligible but initial-pool omitted in the measured
purchase scenarios. Ranger boots can appear in the existing access pool despite
exceeding budget; complete evaluation rejects them. Pool presence alone does not
establish affordability.

Owned Slash still loses a demonstrably better **retained** choice: replacing only
Warrior helm with Berserker helm `3751` yields **2.795532580315 DPS**, zero GP, and
passes complete validation. Every piece in that witness is retained for Owned
Slash, proving a bounded discovery loss, not a metadata problem. The same complete
witness is legal under both purchase budgets, but Fighter torso `10551` is omitted
from their initial pools. Helm of Neitiznot `10828` is also omitted from the single
melee pools. The diagnostic sweep found no other positive single-slot witnesses
for the final returned scenarios; this is not proof of optimality or absence of
multi-slot improvements.

Timing uses one warmup and three serial measured Windows runs per stage, excluding
loading, network and diagnostic sweeps. Four responses per scenario were identical.
Host scheduling was not isolated; these are development measurements, not ARM64
or live UI acceptance.

| Scenario | Before median s | Final median s | Before nodes | Final nodes |
| --- | ---: | ---: | ---: | ---: |
| Owned Slash | 0.930 | 0.989 | 18,678 | 19,446 |
| Owned Ranged | 0.927 | 0.947 | 16,662 | 17,430 |
| Owned Magic | 1.004 | 1.063 | 19,158 | 19,926 |
| Slash +1M | 1.085 | 1.057 | 21,256 | 22,280 |
| Slash +5M | 1.015 | 1.060 | 21,472 | 22,496 |
| Ranged +5M | 0.984 | 1.063 | 18,808 | 19,832 |
| Joint four actions | 3.558 | 2.753 | 124,257 | 125,217 |

Joint elapsed time falls despite a slightly larger node count; no search speedup
was implemented or inferred. Every run remains `best_found` with candidate
truncation and bounded-search completion. Role beam 128, joint beam 16, nominal
slot cap 12 and 1,000,000-node limit are unchanged.

The **separate frozen 119-row regression fixture** preserves the old catalog and
prices. Baseline, `local_refinement` and `targeted_head_refinement` were rerun
independently with one warmup/three repeats. These results are not the expanded
catalog recommendations above:

| Frozen case | Baseline DPS | Local-refinement DPS | Targeted-head DPS | Median s: baseline/local/targeted |
| --- | ---: | ---: | ---: | --- |
| Owned Slash | 2.642031114342 | 2.728201379517 | 2.728201379517 | 0.544 /1.017 /0.521 |
| Slash +1M | 2.659550762100 | 2.728201379517 | 2.659550762100 | 0.607 /0.975 /0.649 |
| Slash +5M | 2.659550762100 | 2.728201379517 | 2.659550762100 | 0.671 /1.008 /0.689 |
| Joint four actions | 2.710305653123 | 2.778752039298 | 2.710305653123 | 3.027 /4.477 /2.917 |

Both features remain independently opt-in. No service/API/MCP/frontend caller
enables them, and no optimizer implementation was changed in this task.

## Validation and reproduction

**363 focused tests pass:** 238 catalog/review tests (10.61s), 81 frozen-search and
independent-refinement tests (26.31s), and 44 pricing tests (0.44s). The catalog
selection includes 60 new exact-ID tests. Before implementation, the initial
54-test selection had 45 expected failures; all were resolved, then six further
isolation/acquisition checks added. Requirements test below/at/above thresholds,
missing facts, both Rune gloves alternatives, exact ownership, synthetic budget
boundaries, stale quote labeling, complete evaluations and locked optimizer use.
Synthetic 100-GP quotes are test inputs only, not price evidence.

Seventeen captured price records additionally round-trip through persistence and
resolution with unchanged provenance. The ten local inserts preserve every other
row/table. Content validation passes (23 skills, 211 quests, 273 items), and scoped
Ruff lint/format checks pass. Independent review found no blocking issue and
verified all 140 numeric fields against pinned page captures.

No new executable production branch was added: changes are reviewed data and an
import allowlist. No new line-coverage percentage is claimed. The focused checks
exercise the existing end-to-end optimizer path; no UI code changed and no new
browser or physical-client acceptance run was performed.

```powershell
.venv\Scripts\python.exe -m pytest tests/gear/test_high_impact_coverage.py tests/gear/test_catalog_coverage_phase1.py tests/gear/test_catalog_coverage_phase2.py tests/gear/test_catalog.py -q --no-cov --basetemp=.tmp/high-impact-verified
.venv\Scripts\python.exe -m pytest tests/gear/test_search_quality_account.py tests/gear/test_local_refinement.py tests/gear/test_local_refinement_integration.py tests/gear/test_targeted_retention.py -q --no-cov --basetemp=.tmp/high-impact-search-tests
.venv\Scripts\python.exe -m pytest tests/integrations/prices/test_prices_cache.py tests/integrations/prices/test_prices_client.py tests/estimation/test_prices.py tests/integration/test_price_seam.py -q --no-cov
.venv\Scripts\python.exe -m tracker.content.validate
.venv\Scripts\python.exe -m tools.benchmark_gear_search_quality --strategies baseline local targeted --cases owned_slash melee_1m melee_5m joint_four --repeats 3 --out .tmp/gear-high-impact/frozen-regressions.json
```

For the private acceptance replay, `measurement/run.py` uses the existing frozen
database/audit APIs and original `requests.json`. Run stages `before` (with
`--content .tmp/gear-high-impact/measurement/before-content`), `catalog`, and
`priced` (with `--prices .tmp/gear-high-impact/pricing/quotes.json`), all with
`--at 2026-10-28T03:00:35.437377+00:00`. `relevance.py` checks concrete denominator
equality against historical scenario arrays; `complete-witness-checks.json`
records the legal-but-undiscovered witnesses. These ignored files depend on
private account evidence and are not a public account fixture.

Remaining blockers are unknown Rune training evidence, unsupported conditional
equipment, high Ranger boots cost, initial pool omissions and bounded discovery
losses. Encounter utility, ammunition recovery, special attacks and production
packaging/ARM64 latency acceptance remain outside this expansion. **No production
routing change, deployment, cutover or Milestone 6 work was performed.**
