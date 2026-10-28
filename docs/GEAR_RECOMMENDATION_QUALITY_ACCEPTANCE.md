# Gear Optimizer recommendation quality acceptance

Assessment: October 27, 2026, America/Chicago; calculations at **2026-10-28 02:14:30.010365 UTC**. Scope: current development checkout after Catalog Coverage Phases 1 and 2, evaluated against the latest available authoritative account. No implementation, production cutover, search-limit change, deployment or account modification.

## Decision and highest-value corrections

**Defer Milestone 6 production cutover.** The optimizer produces legal, useful ordinary-attack starting loadouts for this account, especially Ranged and standard-spell Magic. It does not yet consistently return the best readily available supported choices: exact checks demonstrate better already-owned Single melee and constrained joint configurations. Additional purchase budgets currently produce no purchases, and metadata gaps prevent a reliable survey of common upgrades. Packaging also blocks a clean-image cutover.

Prioritize these concrete corrections in separately authorized work:

1. **Recover demonstrated retained-candidate search losses.** Owned Slash returns 2.642031114342 DPS, but changing only Fury to the already-owned Amulet of strength gives **2.728201379517 DPS (+3.26%)**. Both necklaces were retained. The four-action joint result misses a legal single head replacement raising weighted DPS from 2.710305653123 to **2.772721328442 (+2.30%)**. Use these frozen cases as regressions before selecting a bounded correction; increasing catalog size alone will not fix them.
2. **Review the highest-impact observed physical IDs first:** Rune/Adamant/Mithril gloves `7460/7459/7458`, Mixed hide top/boots/cape `29280/29286/29289`, and Red d'hide body/chaps `2501/2495`. Their current blockers and relevance are below. Do not clear generic effect markers or infer quest wear gates without independent review. Mixed hide already has satisfied wear facts and is blocked by effect review alone.
3. **Make purchase coverage actionable:** review exact acquisition/wear/effect facts for common alternatives such as Archers ring `6733`, then ensure exact-ID quotes exist for approved purchases. Phase 2 robes/hat/gold boots already have reviewed metadata but lack prices. Measure improvement after those inputs exist; this assessment supplies no invented quotes or hypothetical DPS for unsupported items.
4. **Package the React build in the wheel/container**, verify the installed artifact on ARM64, and retain NiceGUI `/gear` as fallback. Current source omits the build and package-data inclusion.
5. **Set a Pi latency/resource acceptance gate before cutover.** Matching two-role optimization takes a 20.25-second median in the existing ARM64 container. Cancellation is cooperative and initial work delays acknowledgement; the container has no observed CPU or memory cgroup cap. Decide acceptable latency/concurrency/resource limits in later operational work.

These are evidence-ranked corrections, not subjective recommendation scores. Completing every imported catalog row, adding persistent history and implementing encounter simulation are not prerequisites for a narrowly described ordinary-attack preview.

## Evidence and account provenance

The connected OSRS Recommender `get_account_summary` reported a newer account than local `tracker.db`. Its snapshot ID matched the independently captured production database. The local database remains at October 19, so it was **not** used as the acceptance account. No deterministic fallback was necessary.

| Fact | Evidence |
| --- | --- |
| Account | Rehvun, player 1, member; observed combat level 73, 265 quest points |
| Latest persisted account sync | 2026-10-27 14:19:38 UTC; latest accepted sync received 14:19:39.131267 UTC |
| Snapshot fingerprint | `dab5fd94ac2f1af7df69947250f45661ee9d536acdd91fd172f2aec89f5b0bca` |
| Bank full scan | 2026-10-27 04:55:38 UTC, RuneLite |
| Equipment full scan | 2026-10-27 14:17:07 UTC, RuneLite |
| Inventory full scan | 2026-10-27 14:19:35 UTC, RuneLite |
| Relevant levels | Attack 60, Strength 60, Defence 56, Ranged 60, Magic 55, Prayer 46 |
| Capture | Existing `pi@pi` connection, `/opt/stacks/osrs-recommender`, existing `osrs-recommender` container, `/data/tracker.db` |
| Capture procedure | SQLite `mode=ro`, `query_only=ON`, WAL-aware backup into memory, `quick_check=ok`, serialize and transfer to ignored local evidence directory; no remote snapshot file or migration |
| Captured database SHA-256 | `5ee533dcb241a26ca12e681793ccf38a918b1771def91d28fab7f780fd240cda` |
| Development Git HEAD | `aaf42fa99d4f6c863ec3c7eaf28fd36793d13268`; dirty checkout, including pre-existing unpublished Phase 1/2 catalog inputs and frontend changes |
| Physical catalog revision | `b8cb3949f6707e5604fea77b59dea84d80782054ad7f8d81d03dde4af87d6b67` |
| Authored content SHA-256 | `82eda41da7ace8cc36edb2b3a1c80009d4f1fa4bcece83bd04072803982df413` |
| Combat model | `normal-attacks-v1` |
| Price revision | `3f7502c861ecef19e48f7da0ffd429e130f3d43c1929d5c7d36d31c7fab9fc43` |
| Raw price records | 190; fetched timestamps span September 26 through October 28 01:41:13.655496 UTC |

The price revision uses the existing browser contract's SHA-256 of sorted `{id: str(record)}` JSON. All calculations share one frozen account, one price set and one evaluation clock. Prices were read from cache; no market refresh was requested. Existing acquisition policy chooses usable high/low/cached quotes, then an authored static hint where configured; missing values remain unknown. Cached evidence does not guarantee a market fill. Owned pieces cost zero additional GP regardless of whether a quote is available.

All three containers have scans, so absent concrete IDs are `unowned` under existing semantics rather than `unknown`. All selected pieces in all seven baseline scenarios are **observed owned**, with no assumed IDs or purchases. Full scans were asynchronous: the bank is approximately 21 hours old at evaluation, while the latest account sync is approximately 12 hours old. This is the latest available persisted state, not a claim about current in-game possessions. Positive observations are not summed across containers. The audit found 845 accepted positive physical IDs, no stale observations relative to their own scans, and no missing-scan observations.

Current worn equipment projects unambiguously to Graceful top `11855`, Graceful gloves `11859`, and Boots of lightness `89`, with other slots empty. Their incomplete/unsupported metadata and the missing weapon prevent a trustworthy ordinary Slash/Ranged baseline; Magic also cannot obtain a supported baseline from those pieces. No percentage improvement over the current worn outfit is claimed. Joint observed-equipment baseline metrics are unavailable by API design.

Private raw evidence and disposable runners are retained under [`.tmp/gear-quality-acceptance/`](../.tmp/gear-quality-acceptance/). `capture.json`, `provenance.json`, `audit.json`, `facts.json`, `requests.json`, seven scenario JSON files, three `*-targeted.json` files, `supplement.json`, `pi-measurements.json`, `pi-checks.json` and `windows-memory.json` contain full item-level facts, lists, exact trials and measurement samples. They are ignored local artifacts, not a committed account fixture. The report retains the material results independently of those private files. Source identity records include hashes of the relevant Python files as well as the dirty status; HEAD alone does not identify these inputs.

## Representative scenarios and chosen equipment

Every role uses an explicit **generic ordinary target**, Defence 80, Magic 80, all defence bonuses zero, no elemental weakness, damage cap or encounter mechanics. Slash is accurate; Ranged is rapid; Magic explicitly uses supported standard **Fire Bolt**, accurate casting. Fire Bolt's level requirement is satisfied by observed Magic 55. Spells are request inputs, not optimized choices; stronger supported spell choices would be a different scenario. Rune quantities, active spellbook and manual/autocast convenience are not established by these results.

Single requests use the unchanged defaults: eight action-curve points plus zero, 12 reserved supply slots, no locks/exclusions/overrides. Joint uses equal role weights, owned-only mode, melee base, both default directed transitions, **maximum four equipment actions per edge**, and 12 reserved supply slots. An automatic offhand removal counts according to the existing transition model, not as an extra manual action.

| Scenario | Returned DPS / weighted DPS | Additional GP | Search nodes | Windows median seconds |
| --- | ---: | ---: | ---: | ---: |
| Owned Slash | 2.642031114342 | 0 | 18,678 | 0.975 |
| Owned Ranged | 2.915472964253 | 0 | 16,662 | 0.969 |
| Owned Magic, Fire Bolt | 1.438853910028 | 0 | 19,158 | 0.984 |
| Slash +1,000,000 GP | 2.659550762100 | 0 | 21,256 | 0.978 |
| Slash +5,000,000 GP | 2.659550762100 | 0 | 21,472 | 1.155 |
| Ranged +5,000,000 GP | 2.915472964253 | 0 | 18,808 | 1.111 |
| Joint, four actions | **2.710305653123**; melee 2.505138341993, ranged 2.915472964253 | 0 | 124,257 | 3.871 |

All rows return `best_found`, `candidate_truncation=true`, `termination_reason=bounded_search_complete`; none reaches the 1,000,000-node limit. Beam width is 128, joint beam width 16, nominal slot-candidate limit 12 including empty. Completing bounded search does not prove optimality or infeasibility of excluded combinations.

Equipment is listed with exact physical IDs. Unlisted slots are empty.

| Slot | Owned Slash | Owned Ranged | Owned Magic |
| --- | --- | --- | --- |
| Weapon | Dragon scimitar `4587` | Magic shortbow (i) `12788` | Ancient staff `4675` |
| Shield | Mooleta `33101` | empty (two-handed bow) | Book of Darkness `12612` |
| Ammunition | empty | Amethyst arrow `21326` | empty |
| Head | Berserker helm `3751` | Archer helm `3749` | Farseer helm `3755` |
| Cape | Black cape `1019` | Ava's accumulator `10499` | Ardougne cloak 1 `13121` |
| Neck | Amulet of fury `6585` | Amulet of glory `1704` | Amulet of glory `1704` |
| Body | Fighter torso `10551` | Blue d'hide body `2499` | Mystic robe top `4091` |
| Legs | Zamorak monk bottom `1033` | Rangers' tights `23249` | Mystic robe bottom `4093` |
| Hands | Combat bracelet `11126` | Ranger gloves `19994` | Combat bracelet `11126` |
| Feet | Granite boots `21643` | Snakeskin boots `6328` | Wizard boots `2579` |
| Ring | Berserker ring (i) `26770` | Explorer's ring 1 `13125` | Explorer's ring 1 `13125` |

Both purchase-budget melee rows use the Owned Slash equipment **except** head=Warrior helm `3753`, body=Black platebody `1125`, hands=Granite gloves `21736`. They still spend zero GP. The budgeted Ranged equipment is identical to Owned Ranged. The higher returned melee DPS is a different selection of existing owned equipment, not a demonstrated purchased upgrade or evidence that Black platebody is generally preferable to Fighter torso.

Joint melee uses weapon `4587`, shield `33101`, ammunition `21326`, head `3753`, cape `10499`, neck `6585`, body `2499`, legs `23249`, hands `21736`, feet `6328`, ring `26770`. Joint Ranged uses the same shared pieces except weapon=`12788`, no shield, head=`3749`, hands=`19994`. It carries 14 distinct IDs, peaks at four gear inventory slots and preserves at least 12 reserved supply slots. Melee→Ranged is three actions; Ranged→melee is four. Equipping the bow automatically removes both scimitar and Mooleta. Ammo sharing is already baseline behavior and does not require experimental head refinement.

Max hit / accuracy / interval are respectively: Owned Slash **17 / 0.741141 / 2.4s**; budget Slash **17 / 0.746056 / 2.4s**; Ranged **13 / 0.798586 / 1.8s**; Magic **12 / 0.710320 / 3.0s**; joint melee **16 / 0.746056 / 2.4s**. All selected loadouts pass the existing exact configuration validator for their role. Joint improvements below additionally pass complete union, transition and inventory validation.

These results do not establish suitability for particular activities. Slash and joint results cannot account for Slayer/task-dependent multipliers or special-attack utility. Ranged results are not Vorkath encounter recommendations: the generic target supplies no encounter-specific mechanics, protection or survival objective. Fire Bolt results do not evaluate Ancient-spell/barrage utility or spell-resource endurance. PvP prayer, burst/special decisions and opponent behavior are outside every row. Defensive/prayer-heavy gear or protection may be necessary for an activity even when a neutral or fragile piece ties the supported DPS objective.

## Recommendation quality: metadata, retention and exact alternatives

### Important observed exclusions

These are excluded before a supported recommendation can be evaluated. No missing effect is approximated and no blocked item is described as a proven DPS upgrade.

| Concrete observed item | Relevant scenarios | Actual blocker / implication |
| --- | --- | --- |
| Rune gloves `7460`, Adamant gloves `7459`, Mithril gloves `7458` | Slash, Magic, Ranged and joint | Incomplete wear requirements **and** `Offensive effects have not been validated.` Exact physical review needed; owned does not imply wearable. Rune gloves' imported +8 melee strength / +8 ranged / +4 magic make this a higher-priority omission than cosmetic rows. |
| Mixed hide top `29280`, boots `29286`, cape `29289` | Ranged, joint, and melee strength tradeoffs | Wear satisfied, complete requirements, observed owned; generic effect-review marker still blocks ordinary damage evaluation. Their imported offensive bonuses establish relevance, not supported DPS. |
| Red d'hide body `2501`, chaps `2495` | Ranged and joint | Unknown wear requirements and unreviewed effects. These are real owned forms; do not assume their requirements are satisfied. Their offensive bonuses do not prove they beat selected Blue body / Rangers' tights. |
| Combat bracelet `11120` | Melee/Magic variants | This observed physical form remains incomplete/unreviewed; selected `11126` is separately owned and supported. No ownership or price alias is inferred. |
| Boots of darkness `20140`, Book of the Dead `25818`, Beacon ring `11014` | Magic | Incomplete wear metadata and unreviewed effects; Book of Darkness `12612` is a distinct supported alternative. |
| Granite longsword `21646`, Dragon sword `21009`, Colossal blade `27021`, Sulphur blades `29084` | Applicable melee profiles | Incomplete wear metadata and model/effect review; only compatible attack profiles would enter Slash. No special/target-size effect is assumed. |
| Crystal bow `23983`, Dragonstone bolts (e) `9244` | Ranged | Incomplete metadata/effect support; charge/enchantment behavior must not be invented. |
| Rune crossbow `9185` | Ranged | Metadata supported, but **observed Ranged 60 does not satisfy its authored wear requirement**. This is a valid account restriction, not a catalog defect or pruning loss. |

Defence-only, utility and cosmetic exclusions contribute to raw coverage but may have no supported DPS upside. They should not displace the offensive review queue. Missing mechanics such as set bonuses, procs, specials or charged-state behavior require a separate model decision, not merely removal of a review marker.

### Common purchase alternatives and missing prices

All seven selected purchase lists are empty; selected-item quote coverage is therefore **not measurable as a purchased-gear success rate (zero purchases)**. This does not demonstrate that either budget is economically sufficient or that the account has no useful upgrades.

| Item/family to investigate | Evidence and limitation |
| --- | --- |
| Archers ring `6733`; Ranger boots `2577` | Normalized catalog has unknown acquisition/wear metadata, generic effect blocker and no usable quote. Relevant imported ranged attack exists (+4 / +8). Common purchase-review candidates, but no claim they are currently affordable or wearable. |
| Obsidian platelegs `21304`; Berserker necklace `11128` | Unknown wear/acquisition and unreviewed effects; no usable purchase price. Platelegs have imported strength relevance; necklace synergy cannot be treated as ordinary modeled damage. |
| Dragon longsword `1305`; Brine sabre `11037` | Physical melee rows exist, but requirements/acquisition/effects are not approved and there is no usable purchase quote. Different speed/profile tradeoffs must be evaluated, not presumed upgrades over the owned scimitar. |
| Mystic dark top/bottom `4101/4103`, light top/bottom `4111/4113`, Enchanted hat `7400`, Climbing boots (g) `23413` | Metadata reviewed by Phase 2; concrete forms unowned and missing exact-ID quotes. They cannot enter supported purchases. Physical similarity does not provide a price or ownership alias. These are chiefly alternatives, not demonstrated strict upgrades. |
| Crystal helm/body/legs `23971/23975/23979`, Ancient sceptre `27624` | Also in the existing audit's unowned missing-price set; other account/model gates remain relevant. Filling prices alone does not make them useful to this account. |
| Dragon boots `11840`, Dragon defender `12954` | Supported facts correctly reject current wear requirements. Dragon boots has a cached 137,000-GP quote, showing that price availability alone does not establish eligibility. Defender is not an ordinary unowned purchase. |

The global audit finds **32 catalog-defined tradeable physical IDs without usable prices**: 28 are effect-clear, while the three Crystal armour forms and Ancient sceptre retain effect blockers. **Ten are unowned**: the six Phase 2 price-only gaps listed above plus those four with additional blockers. The other 22 are owned and do not need a purchase quote for these runs. Normalized acquisition is unknown for 5,181 imported definitions; `price.layer=not_tradeable` on a row with unknown acquisition must not be interpreted as independently verified untradeability. Most of those rows fail wear metadata first. No new acquisition facts or market prices were authored during this assessment.

The concrete budget expansion is small even before search: the +1M melee offensive set adds only Iron/Steel/Mithril/Adamant scimitars `1323/1325/1329/1331`; +5M also adds the unimbued Berserker ring `6737`, quoted at a cached **3,068,860 GP**, while the account already owns supported imbued ring `26770`. Ranged +5M adds Blue d'hide chaps `2493` (2,306 GP cached), leather body/chaps/cowl `1129/1095/1167`, Magic shortbow `861` (708 GP cached), Mithril arrows `888`, Shortbow `841` and Willow shortbow `849`. Exact one-slot checks find no Ranged DPS increase from these or other eligible substitutions. This explains why the current budget pathways mainly offer starter alternatives rather than establishing a useful upgrade ladder.

### Initial omissions versus later search loss

Counts below include only access-eligible items with at least one supported compatible scaffold, individual budget compatibility and scenario restrictions satisfied. An omitted candidate is not automatically better. Neutral/negative offensive items can still be legal alternatives and are counted here even when excluded from the narrower offensive-relevance measure below.

| Scenario | Eligible item-role omissions from initial pools | Material examples |
| --- | ---: | --- |
| Owned Slash | 2 | Helm of Neitiznot `10828`, Xerician hat `13385` |
| Owned Ranged | 2 | Farseer helm `3755`, Granite helm `10589` |
| Owned Magic | 2 | Granite helm `10589`, Snakeskin bandana `6326` |
| Slash +1M / +5M | 18 each | Fighter torso `10551`, Helm of Neitiznot `10828`; remaining legal omissions include other-style/neutral armour |
| Ranged +5M | 19 | Shortbow `841`, other-style metal armour and headwear |
| Joint | 2 per role, 2 distinct IDs | Farseer helm `3755`, Granite helm `10589` |

These measure initial pool membership only. Later beam rejection/traversal is not instrumented, so absence from the selected loadout is not proof of initial pruning. More importantly, **retained** alternatives also demonstrate missed DPS:

| Exact trial | DPS before → after | Cost and constraint result | Interpretation |
| --- | --- | --- | --- |
| Owned Slash: Fury `6585` → Strength amulet `1725` | 2.642031114342 → **2.728201379517** | Valid, 0 GP; max hit 17→18, accuracy falls | Retained necklace; later bounded-search loss, not missing metadata or head truncation |
| Owned Slash: Berserker helm `3751` → Warrior helm `3753` | 2.642031114342 → **2.670865566737** | Valid, 0 GP | Both retained; another later search loss |
| Either budget Slash: Granite gloves `21736` → Combat bracelet `11126` | 2.659550762100 → **2.670865566737** | Valid, 0 GP | Retained hand alternative improves supported objective |
| Either budget Slash: reuse Owned Slash + Strength amulet | 2.659550762100 → **2.728201379517** | Valid under each purchase request, 0 GP | A stronger known configuration exists inside both budgets; no global-optimum claim |
| Joint melee: Warrior helm `3753` → Berserker helm `3751` | weighted 2.710305653123 → **2.772721328442** | Complete joint validation passes four-action cap, 0 GP | Retained head; same Ranged DPS, melee becomes 2.629969692631 |
| Joint melee: Warrior helm `3753` → Neitiznot `10828` | weighted 2.710305653123 → **2.772721328442** | Complete joint validation passes, 0 GP | Equal DPS to the Berserker witness; different unscored bonuses |
| Joint melee: Granite gloves → Combat bracelet | weighted 2.710305653123 → **2.715634588997** | Complete joint validation passes, 0 GP | Smaller retained-candidate miss |

The exact one-slot review evaluated all access-eligible concrete items against each selected role loadout, without repair: 73 valid trials for Owned Slash, 65 for Owned Ranged, 77 for Magic, 96/98 for budget Slash, and 87 for budget Ranged. No positive-DPS one-slot witness was found for either Ranged run or Magic. That is local substitution evidence, not a proof over coordinated replacements. Enchanted top/robe `7399/7398` tie the selected Mystic pieces in this Magic context; Glory/Fury and several rings can also tie. Valid-but-unselected ties are not evidence of recommendation failure.

For joint trials, per-role improvements are insufficient: single melee substitutions of Strength amulet, Fighter torso, Climbing/Granite/Rune boots fail complete four-action validation despite raising isolated melee DPS. They are **not** reported as valid joint improvements. The head/bracelet witnesses above pass `_Search.solution(..., 4)`, which recomputes shared purchase union, transient inventory and directed actions with the existing exact combat evaluator.

### Experimental targeted-head comparison

Reused [candidate-retention research](GEAR_CANDIDATE_RETENTION_ASSESSMENT.md) and [targeted refinement](GEAR_TARGETED_RETENTION_REFINEMENT.md), including their independent strength-breakpoint fixtures. Their historical October 19 result of no account DPS gain remains historical evidence; it is not transferred to this newer account/target. The targeted option remains Python-only, opt-in and **disabled in production routes/services/UI/MCP**.

| Current scenario | Baseline → targeted DPS | Attempts / valid | Helper / total seconds | Finding |
| --- | --- | --- | --- | --- |
| Owned Slash | 2.642031114342 → 2.728201379517 | 98 / 92 | 0.0205 / 1.0359 | Demonstrated DPS gain; no work-cap exhaustion |
| Slash +1M | unchanged, 2.659550762100 | 520 / 463 | 0.1080 / 1.2625 | No accepted improvements |
| Slash +5M | unchanged, 2.659550762100 | 520 / 480 | 0.1335 / 1.3356 | No accepted improvements |

Targeted total times are single observations, not benchmark medians. The owned result changes head to Neitiznot and neck to Strength amulet. **Strength amulet alone already produces exactly the same DPS**, so the omitted-head change is an equal-DPS ordering change relative to that direct witness; the measured +0.086170265175 gain cannot be attributed uniquely to head recovery. Head-only substitution at this incumbent does not establish a better breakpoint. Budget runs show that this narrowly triggered head/companion method does not recover every retained hand/body/neck search miss. Multi-style refinement is outside its supported trigger. No strategy is promoted and no result is called globally optimal.

## Coverage impact and explicit denominators

### Historical measures preserved

The Phase 2 historical baseline remains **76/229 (33.2%) raw observed equipment**, **76/174 (43.7%) fixed combat-relevant observed equipment** at October 19. Do not replace its denominators with current account counts or interpret account inventory growth as a catalog regression.

Using the **same definition** on the current account: accepted observed catalog equipment with any strictly positive numeric ordinary combat bonus (attack, defence, strength, magic damage or prayer), fixed before the scenario runs, yields:

| Measure | Current supported / denominator | Meaning |
| --- | ---: | --- |
| Raw observed equipment | **81/286 (28.3%)** | `fully_supported` from existing five-role audit |
| Combat-relevant rule, current membership | **81/215 (37.7%)** | Same positive-bonus rule as Phase 2, applied to newer observations |
| Historical fixed 174-ID cohort, current observations | **74 supported /174 fixed IDs** | Only 169 of those IDs are still observed; this is a cohort-presence diagnostic, not a replacement coverage metric |
| Entire physical catalog | 5,435 definitions; 259 complete requirement rows; 177 complete and effect-clear | Physical statistics do not establish account eligibility or role support |

There are 559 unclassified observed IDs, excluded from equipment denominators without assuming that they are non-equipment. Of the 286 observed equipment rows, 201 have incomplete requirements, 204 have effect-review/model limitations; these categories overlap. The numerator additionally requires satisfied wear and supported initial eligibility. The frozen current 215-ID list and historical cohort list/counts are in `supplement.json`.

### Scenario-oriented offensive relevance

This is an **additional**, deliberately narrower metric. It is not a redefinition of raw or historical combat-relevant coverage.

The denominator is an enumerable set of concrete catalog IDs selected **before eligibility**: weapons must list the requested attack style; ranged ammunition must have positive ranged strength; other slots must have positive attack bonus for the style or positive relevant strength/magic damage. Owned scenarios include only observed-owned IDs. Purchase scenarios include those plus all unowned catalog rows except known-untradeable forms; unknown acquisition/requirements and unknown prices stay in the denominator to expose gaps. Known-unmet wear requirements stay in the denominator and are reported separately. It excludes defence/prayer-only/neutral equipment, noncatalog observations and conditional-effect-only relevance. Thus it is a potential offensive coverage universe, not a list of wearable or affordable purchases.

The numerator uses the existing audit's initial eligibility: satisfied access/wear, a supported legal weapon/ammunition scaffold, individual cost within budget and applicable scenario restrictions. It does not require final selection or retention. Individual affordability is not proof that every combination fits the joint budget. Exact concrete membership and reasons are retained in each scenario's `relevance` arrays; these rules reproduce the denominator from the pinned inputs.

| Scenario / role | Potentially relevant IDs | Initially eligible and model-supported | Unknown wear | Known unmet wear | Effect blockers after wear | Other access / budget blockers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Owned Slash | 55 | **17 (30.9%)** | 35 | 0 | 3 | 0 |
| Owned Ranged | 62 | **32 (51.6%)** | 26 | 1 | 3 | 0 |
| Owned Magic | 48 | **24 (50.0%)** | 24 | 0 | 0 | 0 |
| Slash +1M | 596 | **21 (3.5%)** | 543 | 23 | 6 | 3 |
| Slash +5M | 596 | **22 (3.7%)** | 543 | 23 | 6 | 2 |
| Ranged +5M | 845 | **40 (4.7%)** | 756 | 41 | 7 | 1 |
| Joint melee | 55 | **17 (30.9%)** | 35 | 0 | 3 | 0 |
| Joint ranged | 62 | **32 (51.6%)** | 26 | 1 | 3 | 0 |

Blocker columns use exclusive precedence: wear unknown, wear unmet, effects, other access, then scenario restriction. They do not imply that later blockers are absent. Joint role denominators overlap and must not be added as distinct gear. Because neutral armour and legal other-style pieces are excluded by this offensive definition, some actually selected neutral pieces and some legal initial omissions lie outside it. Selected gear legality is validated separately above.

Concrete priorities illustrated by this measure: Slash includes supported Dragon scimitar, Fury/Strength amulets, Fighter torso, Berserker/Warrior/Neitiznot helms and Mooleta, but excludes observed Rune gloves/Mixed hide until review. Ranged includes Magic shortbow (i), Amethyst arrows, Blue d'hide body, Ranger gloves and Rangers' tights, but observed Red d'hide/Mixed hide and unowned Archers ring expose review gaps. Magic includes Ancient staff, Farseer helm, Book of Darkness, Wizard boots, blue Mystic and Enchanted robes; observed Rune gloves/Book of the Dead/Boots of darkness remain blocked. Counts are not subjective usefulness scores.

For a portable concrete record, these are the initially eligible IDs within the three owned offensive-relevance sets (membership is independent of final selection):

| Role | Concrete eligible offensive IDs |
| --- | --- |
| Slash, 17 | `1333, 1704, 1725, 1731, 3105, 3751, 3753, 4131, 4587, 6585, 10551, 10828, 11126, 21643, 21736, 26770, 33101` |
| Ranged, 32 | `843, 853, 857, 882, 884, 886, 890, 892, 1063, 1065, 1097, 1099, 1133, 1135, 1169, 1704, 1731, 2499, 3749, 6326, 6328, 6585, 8880, 8882, 10499, 11126, 12610, 12788, 19994, 21326, 22275, 23249` |
| Magic, 24 | `577, 1017, 1033, 1381, 1387, 1704, 1727, 1731, 2579, 3755, 4089, 4091, 4093, 4097, 4675, 6585, 7398, 7399, 11126, 12612, 13121, 13385, 13387, 13389` |

## Performance, memory and cancellation

Windows: Ryzen 5 5600X, six physical/twelve logical cores, Windows 10 build 19045, Python 3.12.10. Each baseline ran one warmup plus **three timed repetitions**, serially on immutable inputs; all four responses per scenario were identical. Durations exclude account capture, catalog loading, diagnostic audits, alternative sweeps, browser rendering and network transport. Normal optimizer result/alternative assembly is included. Host scheduling was not isolated.

| Scenario | Three Windows seconds | Median seconds |
| --- | --- | ---: |
| Owned Slash | 1.0221, 0.9594, 0.9747 | 0.9747 |
| Owned Ranged | 0.9693, 0.8991, 0.9758 | 0.9693 |
| Owned Magic | 1.0623, 0.9836, 0.9685 | 0.9836 |
| Slash +1M | 0.9781, 1.0238, 0.9617 | 0.9781 |
| Slash +5M | 1.0792, 1.1706, 1.1555 | 1.1555 |
| Ranged +5M | 1.2107, 1.1110, 1.0751 | 1.1110 |
| Joint four-action | 3.8031, 3.8960, 3.8712 | 3.8712 |

The initial Windows sampling path could not measure memory because `psutil` is absent. A separate run used native `GetProcessMemoryInfo` at approximately 10ms intervals, without installing dependencies. Sampled working-set maxima were **102.0 MiB Slash, 102.0 MiB Ranged, 102.9 MiB Magic, 123.5 MiB joint**. The process lifetime peak was 173.6 MiB, including setup. These are process measurements, not incremental allocation or full application/container memory. The extra memory runs had different timings and are not mixed into the table above.

ARM64 was available. Measurements ran in an automatically cleaned temporary directory inside the existing container, using a temporary copy of the exact current Python/content files and the **same frozen account, requests and price image**. Production files/routes/catalog/database were not replaced, no dependencies were installed, and no infrastructure was added. This validates core calculations on Pi hardware; it is not acceptance of the deployed React application or a packaged Milestone 6 image.

Pi: `aarch64`, Linux `6.18.50+rpt-rpi-v8`, Python 3.12.15, four visible CPUs. One warmup plus three timed repetitions:

| Scenario | Three Pi seconds | Median seconds | Baseline parity |
| --- | --- | ---: | --- |
| Owned Slash | 4.8753, 5.3280, 5.2133 | **5.2133** | Same equipment, DPS, nodes and diagnostics as Windows |
| Owned Ranged | 4.7723, 4.6334, 4.8199 | **4.7723** | Same |
| Joint four-action | 20.2529, 20.5511, 20.1025 | **20.2529** | Same |

Pi response hashes were stable across repeats. Process `ru_maxrss` reached **173,256 KiB (169.2 MiB)** including setup; it is cumulative, not a per-request delta. During the separate cancellation check, cgroup `memory.current` was 392,409,088 bytes (~374.2 MiB), including existing app and assessment activity. `memory.max=max`, `cpu.max=max 100000`: no container CPU/memory cap was observed. These readings are not a sustained-load/thermal test. Pi Magic, purchase scenarios and three/four-role performance were not benchmarked here; the prior Milestone 5 synthetic desktop matrix does not establish their Pi behavior.

Cancellation used an event requested after 0.1 seconds, passed through the existing callback; no node or candidate limit was changed:

| Scenario | Windows acknowledgement | Pi acknowledgement | Outcome |
| --- | ---: | ---: | --- |
| Owned Slash | 0.4799s | 1.4328s | `optimization_cancelled` |
| Joint | 0.4415s | 1.7673s | `optimization_cancelled` |

These are elapsed time from solve entry, not time after the event. They include pre-search fact/candidate preparation and scheduler effects. Cooperative cancellation is demonstrated, not immediate interruption or HTTP/browser abort acceptance. The service's concurrency guard remains held until its worker exits. A ~20-second joint request therefore creates a real busy/backpressure concern, even though this sample stayed below the node budget.

## Production-readiness assessment

| Issue | Classification | Assessment / acceptance needed |
| --- | --- | --- |
| Demonstrated better already-owned Single/joint choices missed | **Blocking cutover** | Establish frozen account regressions and a reviewed bounded correction. Current results are legal but leave directly verified supported DPS on the table. |
| High-impact observed offensive metadata gaps | **Blocking cutover for broad account recommendation claims** | Review the small named glove/Mixed hide queue first; unknown/unmet requirements must remain distinct. Full 5,435-row completion is unnecessary. |
| Purchased-upgrade coverage | **Blocking cutover for reliable budget advice** | Zero purchases returned, common candidates blocked by metadata, reviewed unowned forms missing quotes. Collect real exact-ID quotes after metadata approval and rerun budget scenarios; do not promise better equipment merely from a larger budget. |
| Static bundle packaging | **Blocking cutover** | `Dockerfile` has Python-only build/runtime stages; no Node frontend build. `pyproject.toml` package-data omits `gear_static/**`. `frontend/gear/vite.config.ts` writes ignored `tracker/ui/gear_static`. Require reproducible build, wheel/image asset inclusion, clean install and ARM64 route/asset acceptance. |
| Frontend/backend compatibility in the current dirty tree | **Blocking cutover until packaged/live acceptance** | Milestones 3–5 record real Python transport, generation/snapshot/price guards, manual trials and joint workflows. Current assessment exercises domain APIs, not all current frontend edits. Rerun focused Single optimize→inspect→preview→lock/reoptimize, purchase-list handling and joint switching on the actual packaged artifact. |
| Pi resource and response-time envelope | **Blocking cutover pending acceptance** | Core ARM64 parity is demonstrated; 20.25s two-role median and no observed cgroup caps need an explicit operational decision. Full deployed UI/load/three-four-role behavior remains unverified. |
| Current account freshness | **Important but deferrable with visible provenance** | Latest authoritative persisted snapshot used, all scan containers present; asynchronous ages remain. Require a fresh RuneLite scan before acting on purchases or making live-game acceptance claims. |
| Unsupported activity mechanics | **Important but deferrable for explicitly generic ordinary attacks** | Becomes blocking if claiming activity-specific suitability. Target mechanics, prayers, boosts, downtime, survival, specials, set/proc effects and endurance are not covered by these results. |
| General candidate/beam truncation | **Important but deferrable after demonstrated misses addressed** | Keep `Best configuration found`, diagnostics and no-optimality language. Current head-only experimental remedy is insufficient for all found cases. |
| NiceGUI Gear fallback | **Blocking cutover if not retained and verified** | Keep existing `/gear` registered and functional. `tracker/ui/gear_preview.py` already returns explicit 503 `gear_frontend_unavailable` with fallback when assets are missing; verify navigation and rollback in the packaged artifact. |
| Result history, generalized defensive objective, full catalog completion | **Optional / later scope** | No need to introduce infrastructure or expand this validation assignment. |

Useful existing compatibility controls include Python-authoritative metrics, exact physical identity, distinct owned/unowned/unknown semantics, same-origin browser protections, app-scoped calculation guard, worker execution, cooperative cancellation, pre/post snapshot checks and frontend generation guards. Their existence is supported by source and previous milestone tests; this assessment does not claim fresh live browser coverage of each one.

The strongest supported recommendation today is **retain `/gear-next/` as an explicitly bounded preview alongside NiceGUI `/gear`, defer replacing production Gear, and fix the demonstrated search witnesses plus the small offensive metadata queue before another acceptance pass**. Do not enable targeted-head refinement as a shortcut to cutover: it misses the budget hand witness and does not support joint search.

## Validation and reproducibility

Reused existing `tools.audit_gear_equipment.frozen_database`, `audit_database`, `tracker.gear.coverage_audit` candidate/scaffold diagnostics, `optimizer.optimize`, `evaluation.evaluate_configuration(s)` and the complete `_Search.solution` validator. Experimental calls used only the existing keyword `targeted_head_refinement=True` in a disposable assessment process. The source database image SHA-256 was checked unchanged after analysis. The local development database's frozen-image identity remained `2d74d48d1a30b9b95c0d180e4d346ab0295d242521c222fe444e2d24e7c4c9ef` when first inspected; no refresh command was run.

Focused existing tests: **162 passed in 6.45 seconds**:

```powershell
.venv\Scripts\python.exe -m pytest tests/gear/test_evaluation.py tests/gear/test_coverage_audit.py tests/gear/test_targeted_retention.py tests/gear/test_targeted_retention_integration.py tests/gear/test_catalog_coverage_phase2.py -q --no-cov --basetemp=.tmp/gear-quality-acceptance/pytest
```

This is an assessment, so no implementation tests were added and no new coverage percentage is claimed. Existing breakpoint tests are included in the selected retention tests. No new browser build/E2E, clean-wheel/container build, deployment, physical gameplay or production cutover was performed. The ARM64 calculation evidence above is separate from those outstanding gates.

Disposable reproduction helpers are `.tmp/gear_quality_capture.py`, `.tmp/gear_quality_run.py`, `.tmp/gear_quality_supplement.py`, `.tmp/gear_quality_memory.py`, `.tmp/gear_quality_pi.py` (plus `--checks` for Pi cancellation/cgroups). Running the capture again intentionally takes a new snapshot; reproduction of these numbers requires retaining the original captured image and pinned checkout inputs. Do not use `refresh-dev-db.ps1` for reproduction, since it replaces development observations.

References: [architecture/redesign plan](GEAR_OPTIMIZER_REDESIGN_PLAN.md), [Milestone 3](GEAR_MILESTONE_3.md), [Milestone 4](GEAR_MILESTONE_4.md), [Milestone 5 and ammunition follow-up](GEAR_MILESTONE_5.md), [original equipment audit](GEAR_EQUIPMENT_COVERAGE_AUDIT.md), [Phase 1](GEAR_CATALOG_COVERAGE_PHASE_1.md), [Phase 2](GEAR_CATALOG_COVERAGE_PHASE_2.md), [candidate retention](GEAR_CANDIDATE_RETENTION_ASSESSMENT.md), [targeted refinement](GEAR_TARGETED_RETENTION_REFINEMENT.md), [browser API](GEAR_BROWSER_API.md). Historical results in those documents retain their original account, target and source provenance.
