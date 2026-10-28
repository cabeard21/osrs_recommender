# Codex Handoff — Milestone 2: Account-Aware Gear Companion

## Context and working branch

Work on the existing branch:

`refactor/account-companion`

Do **not** merge into `main`.

Milestone 1 established the Account Companion architecture:

```text
RuneLite/account state
    → AccountSnapshot
    → deterministic account/goal evaluation
    → bounded MCP tools
    → ChatGPT reasoning
```

Milestone 2 extends that architecture into the existing gear domain.

The prior architecture investigation reported two distinct gear-related paths:

1. A useful curated gear progression path based on generated item content, style/slot ladders, ownership, wear requirements, acquisition information, and prices.
2. A separate legacy recommendation path that turns selected gear acquisitions into weighted/ranked actions using roadmap weights, scoring, GP sensitivity, hysteresis, and persisted recommendation history.

M2 adapts **the first path** to Account Companion. It is not a rewrite of the legacy recommendation engine.

This handoff records the agreed scope. Verify implementation details against the current branch before editing; names such as `gear_progress`, `_slot_plan`, and `PriceFact` refer to components identified during the prior investigation. If the code has changed, follow the current implementation while preserving the contracts below.

## Architectural principle

> The application maintains authoritative observed OSRS account state and exposes deterministic account-aware tools. ChatGPT provides planning, recommendations, and conversational reasoning.

Account Companion owns facts including:

- Observed item ownership and bank/inventory/equipment membership.
- Observation coverage, timestamps, and provenance.
- Curated progression-ladder membership and authored order.
- Equipment requirements, satisfaction states, and blockers.
- Acquisition classification and acquisition-source information.
- Cached prices and their provenance.
- Bounded candidate discovery using factual filters.
- Limited, read-only evaluation of proposed gear acquisitions/changes.

ChatGPT owns reasoning including:

- Which candidate to choose or prioritize.
- Whether an upgrade is worth its cost.
- How to allocate a budget.
- Whether gear should take priority over Quest Cape or another goal.
- Activity-specific tradeoffs and conversational interpretation.

Do not introduce another weighted recommendation system. A calculation being deterministic does not make it a fact: weighted ranking and “best item” selection remain recommendation policy.

## Existing assets to preserve

Preserve and reuse where appropriate:

- Curated melee/ranged/magic progression ladders.
- Item identities, numeric IDs, and recognized variant IDs.
- Style and slot associations.
- Authored progression tiers/order.
- Known wear requirements and explicit unknown wear gates.
- Acquisition classifications and `acquired_from` information.
- Variant-aware ownership.
- Tri-state ownership based on observation coverage.
- Existing price infrastructure and catalog validation.
- Pure factual portions of `gear_progress` and ladder construction.

Ladder tier/order means **curated progression-guide order**. It is not DPS, numeric combat strength, universal BiS, value per GP, or a combat-stat difference. Preserve that distinction in service contracts, MCP descriptions, and documentation.

## Existing behavior to preserve

The current Gear dashboard is useful and must remain operational.

It may continue its existing rule selecting the highest wearable/obtainable progression rung. This is intentionally retained dashboard recommendation policy. Do not automatically expose that selection as an objective recommendation in the new MCP path.

| Surface | Intended semantics |
| --- | --- |
| Existing Gear dashboard | Curated progression recommendation |
| New Account Companion MCP | Account-aware progression facts and bounded candidates |

Do not substantially redesign the Gear page. Preserve the older advisor gear path unless a correctness fix requires a small change. The new MCP tools are additive during M2.

## Milestone objective

Implement **Account-aware Gear Companion**: extend Account Companion with provenance-aware item observations, adapt existing curated gear progression to that account boundary, integrate gear prices, and expose a small bounded MCP surface that lets ChatGPT reason about equipment choices.

## Phase 1 — Extend AccountSnapshot with item observations

Add the general account facts needed by gear, rather than gear-specific recommendation fields.

At minimum, represent:

```text
Observed items:
    numeric item ID
    quantity where available
    observed container(s)

Container observation state:
    bank
    inventory
    equipment

Provenance:
    whether each relevant container has been successfully observed
    available observation/sync timestamps
```

Preserve the ownership distinction:

| State | Meaning |
| --- | --- |
| `owned` | An observation establishes ownership through a base or recognized variant ID. |
| `unowned` | The item is absent and the necessary containers have successfully been observed under the existing coverage semantics. |
| `unknown` | Observations do not establish ownership, and coverage is insufficient to establish absence. |

Do not turn an absent item into `unowned` merely because it is missing from one container. Do not interpret an unobserved container as an empty container. Ownership describes the available observations; preserve their age rather than implying a live guarantee.

Retain variant-aware identity: a recognized variant can establish ownership of the corresponding catalog item. Preserve actual observed IDs and container provenance.

Only add account type if an M2 path needs it. Do not copy liquid GP, GP sensitivity, activity preferences, or other legacy `PlayerState` fields without an actual M2 requirement.

### Equipment limitation

The investigation found that the RuneLite pipeline records equipment-container membership but does not preserve exact equipment-array positions.

Represent **observed in equipment container**. Do not claim an item is currently equipped in a particular slot unless captured data proves that fact. An authored catalog slot is distinct from an observed equipment slot.

Do not expand the RuneLite protocol during M2 merely to recover exact slots. Prefer the limited truthful contract. If an agreed capability genuinely cannot work without protocol changes, report the conflict before expanding scope.

### Snapshot identity

Make relevant item observations and coverage part of snapshot identity/fingerprint semantics, consistent with M1. A meaningful item-state change must not leave hypothetical evaluations appearing current. Preserve M1 behavior for existing account facts and document any identity-contract change.

## Phase 2 — Adapt gear to AccountSnapshot

Create a gear service boundary consistent with M1 architecture:

```text
AccountSnapshot
    + curated gear catalog/ladders
    + requirement evaluation
    + price facts
    → GearService
```

The new service must operate independently of:

- Weighted recommendation scoring.
- Roadmap weights or GP sensitivity.
- Recommendation hysteresis.
- Recommendation persistence/history.
- Golden ordering judgments or tuning infrastructure.

Reuse/refactor pure portions of `gear_progress` and ladder construction where practical. Avoid duplicating the entire gear pipeline. Avoid reconstructing a legacy `PlayerState` simply to route the new service back through the recommender.

Keep persistence/account acquisition at the existing service boundary; factual evaluation should consume a coherent snapshot and supplied catalog/price facts.

## Phase 3 — Requirement evaluation

Use the Account Companion requirement-evaluation boundary established in M1 for requirement leaves actually needed by the gear corpus.

The investigation found primarily skill and quest wear requirements. Verify the current content before relying on this assumption.

Preserve:

- Satisfied requirements.
- Known blockers.
- Unknown wear gates.
- Explicit unsupported requirement leaves.

Unsupported leaves must not silently pass or become a known failure. Return an explicit unknown/unsupported status with enough detail for ChatGPT to explain the limitation. Do not add support for every AST leaf merely because the shared schema permits it.

### Variant inconsistency

Resolve the reported inconsistency between variant-aware gear ownership and primary-ID-only `item:` requirement evaluation in the new Account Companion path. Ownership and applicable item-requirement checks must use consistent identity semantics.

Add a targeted regression. Do not redesign all legacy requirement evaluation unless necessary for the new shared boundary; document remaining compatibility differences if any.

## Phase 4 — Separate progression facts from selection policy

The factual projection should expose, per style/slot:

- Authored ladder and ordered rungs.
- Tier/order with explicit curated-progression semantics.
- Ownership status and observed containers.
- Equipment-container observation.
- Wear status and requirement blockers.
- Acquisition classification and known source information.
- Price facts and provenance.

Keep `_slot_plan` or equivalent dashboard selection policy separate from the MCP factual view. Reuse shared factual rung evaluation beneath both where practical:

```text
Evaluated gear facts
    → existing dashboard selection policy
    → new MCP factual view
```

Do not label the highest available rung an Account Companion recommendation. Do not introduce hidden scoring or utility ranking inside candidate discovery. Stable authored ordering is acceptable and must be labeled accurately.

## Phase 5 — Price integration

Make the curated gear catalog/ladders used by M2 eligible for price refresh. The investigation found that existing refresh scope could omit ladder-only items because it was derived from legacy capabilities/candidates/training methods.

Preserve sound existing resolution and caching behavior. Expose enough information to explain:

```text
selected amount
source and selection basis
underlying trade timestamp, where available
fetch/cache timestamp
existing freshness/confidence information
explicit unknown price
```

Do not collapse missing prices to zero. Do not treat untradeable items as purchasable. An observed price is not a guaranteed executable quote.

Do not invent a new arbitrary stale-price cutoff or redesign the price subsystem. Preserve existing stale/fallback semantics and make them visible. Where useful, compute age from available timestamps without inventing unavailable provenance.

### Selected-price provenance defect

Investigate the reported older-advisor defect: a selected `PriceFact` may attach `high_trade_at` even when its amount came from the low-price leg.

If confirmed, fix it and add a focused regression demonstrating that selected amount, selected leg/basis, and trade timestamp agree. Keep unrelated pricing behavior unchanged.

Account snapshot identity and price freshness are separate concerns. Preserve relevant price timestamps/basis in evaluations so a price refresh is not confused with an account-state change.

## Phase 6 — Implement GearService

Use naming and placement consistent with M1. The service should support the four capabilities below without embedding recommendation policy or exposing persistence internals through MCP.

Preserve:

- Read-only, immutable account evaluation.
- Snapshot identity/fingerprints.
- Explicit unknown states.
- Bounded results.
- Observation and price provenance.
- Clear errors for invalid styles, slots, identifiers, and conflicting requests.

Keep implementation choices proportionate. Do not create a generalized gear goal/action framework or force gear into Quest Cape abstractions where they do not fit.

## Phase 7 — MCP surface

Implement four new Account Companion operations:

```text
get_gear_progression
get_gear_candidates
get_item_details
evaluate_gear_change
```

Follow M1 patterns for fresh snapshot acquisition, identity, read-only annotations, bounded serialization, and expected-snapshot validation where applicable. Each operation must evaluate against a coherent snapshot.

Use `get_gear_progression`, not the legacy `get_gear_setup`: the latter already means a computed recommended setup in the older advisor.

### 1. get_gear_progression

**Request**

- Required style: `melee | ranged | magic`.
- Optional slot.
- Appropriate bounds if the projection requires pagination or truncation.

**Response**

- Snapshot identity.
- Account observation/coverage and freshness metadata.
- Requested style and slot scope.
- Authored progression rungs with tier/order.
- Ownership and observed containers.
- Equipment-container observation, without invented equipped slots.
- Wear status, blockers, and unknown/unsupported requirements.
- Acquisition classification and price facts.
- Bounds and total/omitted information where needed.

This describes the account in relation to the curated catalog. It must not return an inferred optimal setup or an objective best-item recommendation.

### 2. get_gear_candidates

**Request**

- Required style.
- Optional slot.
- Bounded limit/cursor using conventions appropriate to the existing MCP.
- Optional factual filters such as ownership state, wearable state, and acquisition classification.

Do not add filters such as `best`, `worth_buying`, `good_value`, or `optimal`.

**Response**

- Snapshot identity and relevant observation metadata.
- Bounded item list with stable content identity and numeric/variant IDs as appropriate.
- Style, authored slot, and curated progression membership/order.
- Ownership, equipment observation, wear status, blockers, acquisition, and price facts.
- Total/omitted information and continuation information where applicable.

Define candidate precisely:

> An item in the curated Account Companion progression catalog satisfying the requested factual filters.

Candidate does not mean every viable OSRS item, objective BiS, DPS-ranked, budget-optimal, or guaranteed valid in a joint loadout. Preserve authored ordering or another documented stable factual order; do not silently rank desirability.

### 3. get_item_details

**Request**

- Stable content identifier and/or unambiguous numeric item ID, following the existing content model.

Handle ambiguous numeric/variant/style matches explicitly. Return applicable memberships or a clear ambiguity result; do not guess one interpretation.

**Response**

- Identity/name, numeric IDs, and recognized variants.
- Style/slot associations and curated progression memberships.
- Wear requirements and account-aware evaluation.
- Acquisition classification and known acquisition source.
- Ownership and observed containers.
- Price facts and observation/price provenance.
- Snapshot identity.

Do not return combat statistics absent from the catalog. Clearly distinguish an unknown identifier from an item outside supported curated coverage.

This operation covers the factual price drill-down role for the new surface. Do not introduce another new price-only tool, and do not remove the old advisor's price tool if compatibility requires it.

### 4. evaluate_gear_change

Implement a deliberately limited v1 using M1 read-only hypothetical principles.

**Request**

- One or more proposed catalog gear items/changes, with a small explicit maximum.
- Style/slot context where needed to resolve authored membership.
- Expected snapshot identity following M1's counterfactual convention, with clear stale-snapshot handling.

Choose a structure appropriate to the existing item model. Define duplicate/alias handling explicitly so repeated representations of the same proposed item do not double-count cost. Reject or clearly describe conflicting proposals rather than pretending to validate a full loadout.

**Response**

- Snapshot identity and evaluation context.
- Proposed item identity and authored target slot.
- Ownership and observed-container facts.
- Wear status, blockers, and unsupported/unknown requirements.
- Acquisition classification.
- Whether purchase is established as necessary, unnecessary for an already-held item, or unknown/not applicable.
- Known selected price and its provenance.
- Purchase subtotal only under the rules below.
- Curated progression relationship where supported, labeled as authored order rather than strength.
- Explicit limitations and unknown aspects.

**Cost semantics**

- For this limited proposal model, an observed owned item does not require purchasing another copy unless the supported request explicitly requires an additional quantity.
- An unowned tradeable item with a usable known price can contribute that amount to an estimated purchase subtotal.
- Unknown ownership or a missing required price must not silently contribute zero.
- An untradeable acquisition is not a GE purchase and must not be presented as achievable through a GP total.
- Return a complete purchase subtotal only when purchase requirements and required prices are sufficiently known. If not, return an explicit unknown/incomplete result with reasons. A partial known amount, if exposed, must be clearly labeled and must not masquerade as the proposal's total acquisition cost.
- Do not infer sale proceeds from presumed replaced gear.

**Explicitly unsupported**

Do not claim:

- Exact currently replaced item.
- Combat-stat, offensive/defensive bonus, or DPS delta.
- Complete joint-loadout validity.
- Two-handed/offhand compatibility.
- Ammunition compatibility.
- Activity-specific suitability.

Do not treat ladder-tier differences as combat-stat differences. Even if isolated additional data exists, do not let this milestone become a stat/loadout modeling project without a scope decision.

**Read-only guarantee**

Do not mutate the persisted account, the real snapshot, equipment observations, or ownership. Verify snapshot fingerprint stability and persistence immutability in focused tests. Evaluation is factual inspection of a proposal, not an instruction to equip, buy, or record an acquisition.

## Phase 8 — Preserve dashboard and legacy compatibility

Check representative behavior for:

- Melee, ranged, and magic progression.
- Ownership and requirement displays.
- Next/earn/aspirational behavior.
- Prices and unknown-price display.

Adapt the dashboard to shared factual infrastructure where straightforward, but keep its existing selection semantics. Preserve existing legacy advisor behavior apart from targeted correctness fixes.

Do not delete scoring, golden/tuning infrastructure, or recommendation history still used elsewhere. Do not expand browser testing into exhaustive style/slot permutations.

## Phase 9 — Focused tests

Use representative equivalence classes, meaningful boundary cases, and known regressions. Do not recreate the exhaustive test machinery removed during the refactor.

| Area | Required coverage |
| --- | --- |
| Snapshot observations | Bank, inventory, equipment; quantities where available; provenance/coverage retained. |
| Ownership | Variant establishes ownership; complete scans plus absence means unowned; incomplete coverage plus absence means unknown. |
| Identity | Relevant observation/coverage changes affect snapshot identity; read-only evaluation leaves it unchanged. |
| Requirements | Satisfied and blocked skill/quest gates; explicit unknown wear gates; unsupported leaves remain unknown/unsupported; applicable item checks recognize variants. |
| Progression | Correct style/slot ladders; authored order retained; factual ownership/wear/acquisition output; no weighted recommender dependency. |
| Prices | Known selected price; missing price; existing stale/fallback behavior; untradeable handling; ladder-only refresh inclusion; selected-leg timestamp regression if confirmed. |
| Proposal evaluation | Owned/unowned/unknown purchase cases; incomplete subtotal; duplicate/alias handling; multiple proposals; stated limitations; no persistence mutation. |
| MCP contracts | All four operations; bounds and omissions; explicit unknowns; snapshot identity; stale expected snapshot handling; identifier ambiguity/errors. |
| Compatibility | Representative existing Gear dashboard behavior and M1 behavior remain intact. |

Run the repository's applicable required gates. Report exact commands and results, distinguishing executed checks from checks that could not run. Do not claim live RuneLite/MCP/dashboard validation based only on unit tests.

## Phase 10 — Documentation

Update architecture and MCP documentation to explain:

1. **Curated progression:** authored guide ordering, not numeric strength, DPS ranking, universal BiS, or exhaustive equipment coverage.
2. **Ownership uncertainty:** owned/unowned/unknown and how container coverage affects absence claims.
3. **Equipment observations:** membership is available; exact equipped slots are not necessarily captured.
4. **Requirement states:** blockers versus unknown/unsupported requirements.
5. **Price semantics:** selection basis, timestamps, missing values, existing freshness behavior, and incomplete purchase subtotals.
6. **MCP responsibility:** factual bounded services; ChatGPT supplies prioritization and recommendations.
7. **Legacy compatibility:** dashboard selection and the old weighted recommender remain available and are not the new MCP architecture.
8. **Hypothetical limits:** no full loadout simulation, combat deltas, or real account mutation.

Provide compact request/response examples using actual implemented schemas. Use clearly labeled fixture/example values, not invented current account observations or live prices.

## Explicitly out of scope

Do not implement:

- Combat DPS calculations or a new numeric equipment-stat model.
- Activity-specific BiS or boss-specific gearing.
- Generalized budget optimization or value-per-GP scoring.
- New recommendation weights or gear scoring.
- Generalized gear goals/actions or a universal goal framework.
- A full equipment/loadout simulator.
- Replacement of legacy recommendation history.
- Removal of the legacy recommender or golden/tuning dependencies still used elsewhere.
- Broad catalog expansion beyond the curated progression source.
- A major dashboard redesign.
- Generalized requirement support unrelated to current gear needs.
- A RuneLite protocol expansion solely to recover exact equipment slots.

If an agreed capability genuinely requires one of these, report the concrete conflict and the smallest possible resolution before expanding scope. Do not ask product questions that the repository can answer.

## Architectural constraints

| Component | Responsibility |
| --- | --- |
| AccountSnapshot | Authoritative observed account facts, coverage, and provenance. |
| Requirement evaluation | Deterministic satisfaction/blocker/unknown facts. |
| Gear catalog/ladders | Curated OSRS progression knowledge. |
| Price service | Price facts, resolution, and provenance. |
| GearService | Deterministic account-aware gear projection and limited proposal evaluation. |
| MCP | Bounded interface and serialization. |
| ChatGPT | Recommendation, prioritization, and tradeoff reasoning. |

Avoid dependencies in the opposite direction. GearService must not depend on recommendation scoring, roadmaps, hysteresis, golden judgments, or recommendation-history persistence.

Keep snapshot facts distinct from proposal assumptions, authored progression, and price observations. Reuse M1 where it transfers cleanly; revise a narrow M1 abstraction when the second domain demonstrates a concrete need, without inventing a generalized framework.

## Suggested execution order

1. Inspect branch state, applicable repository instructions, M1 implementation, gear facts/policy separation, and current tests. Preserve unrelated changes.
2. Briefly identify files likely to change and any concrete contract conflict. Proceed with implementation when the agreed scope is feasible; do not repeat the architecture investigation as a separate deliverable.
3. Extend AccountSnapshot and shared ownership/requirement semantics.
4. Extract/adapt reusable factual gear projection and integrate prices.
5. Implement GearService and the four MCP tools.
6. Add focused regression/contract tests and preserve dashboard compatibility.
7. Update documentation and run applicable gates.
8. Return the implementation report and practical live acceptance steps below.

Remain on `refactor/account-companion`; do not merge to `main`. Follow existing repository/session rules for committing or pushing, and do not assume this handoff authorizes deployment.

## Definition of done

M2 is complete when:

- AccountSnapshot carries the item observations and provenance required by gear.
- Variant-aware tri-state ownership is consistent across the new gear and applicable requirement paths.
- GearService evaluates curated gear facts independently of the weighted recommender.
- The four new tools expose bounded truthful contracts with snapshot identity and unknown states.
- Ladder-only items are included in appropriate price-refresh scope.
- The selected-price provenance defect is fixed if confirmed.
- Proposal evaluation has correct known/unknown purchase semantics and does not mutate real account state.
- The existing Gear dashboard and representative M1 behavior remain functional.
- Focused tests and applicable gates pass, or concrete environmental blockers are reported.
- Architecture/MCP documentation accurately describes capabilities and limitations.

## Practical acceptance scenario

The user should be able to ask ChatGPT:

> “I've got about 5m. I'm mostly working on Quest Cape, but my ranged gear feels behind. Is there anything worth buying?”

The combined M1/M2 tools should let ChatGPT:

1. Inspect current Quest Cape progress using M1 tools.
2. Inspect ranged progression and observation coverage.
3. Request bounded curated candidates using factual filters.
4. Drill into a few items, ownership, blockers, and prices.
5. Evaluate one or more purchase proposals against an expected account snapshot.
6. Explain price/ownership uncertainty and unsupported equipment comparisons.
7. Reason conversationally about whether gear or another account goal deserves priority.

The application supplies facts; ChatGPT makes the recommendation. The user's stated budget is conversational context, not a reason to add a budget optimizer.

Provide a short acceptance checklist with actual commands/tool requests after implementation. If live access is unavailable, provide the steps for the user to run and clearly mark them as pending.

## Final implementation report

Return a concise report covering:

- What changed and the resulting behavior.
- Important files/modules and the final service boundary.
- Final MCP tool names and high-level request/response contracts.
- Snapshot/ownership/requirement semantics and any M1 abstraction changes.
- Price-refresh and provenance changes.
- How existing dashboard behavior was preserved.
- Checks run with actual results.
- Any pending live acceptance checks or concrete blockers.
- Remaining limitations and explicitly deferred capabilities.

Do not present authored progression as measured combat performance. Do not claim current prices or account state without actual observations. Do not expand M2 into another recommendation framework.
