# OSRS Recommender — Milestone 1: Quest Cape Account Companion

You are working in the existing `osrs_recommender` repository.

## Context

This application originally grew around recommendation scoring, roadmaps, a golden corpus, PvP readiness, and other recommendation-domain concepts.

The new direction is simpler:

> The application maintains authoritative OSRS account state and exposes deterministic account-aware tools. ChatGPT provides planning, recommendations, and conversational reasoning.

Do **not** redesign or remove the existing recommender yet.

Milestone 1 is a thin vertical slice intended to prove this architecture before any major cleanup.

## Milestone 1 objective

Given the current RuneLite-synced account, ChatGPT should be able to accurately:

1. Inspect the player's Quest Cape progress.
2. Determine which remaining quests are currently available.
3. Identify meaningful skill-level blockers.
4. Evaluate the hypothetical effect of:
   - completing a quest;
   - training a skill to a required threshold.
5. Access those deterministic operations through MCP.
6. Use the results to answer a question such as:

   "I'm working toward my Quest Cape. What should I do next?"

The application should provide facts and counterfactuals.

**Do not implement recommendation ranking for what the player should do next. ChatGPT performs that reasoning.**

---

# Architectural target

The intended flow is:

```text
RuneLite / existing account sync
          ↓
   AccountSnapshot
          ↓
 RequirementEvaluator
          ↓
 Quest Cape evaluator
       ↙       ↘
available      evaluate
 actions        action
          ↓
         MCP
          ↓
       ChatGPT
```

The important architectural boundary is `AccountSnapshot`.

The quest/goals code should not need to know how RuneLite synchronization, database persistence, recommendation scoring, or the existing advisor internally work.

---

# Step 1 — Inspect the repository first

Before changing code:

1. Inspect the current project structure.
2. Locate the existing sources of:
   - skills;
   - quest completion;
   - inventory/bank/equipment if applicable;
   - account/player identity;
   - RuneLite synchronization;
   - quest metadata and prerequisite information;
   - MCP server/tool registration;
   - existing recommendation-domain models.
3. Identify logic that can be reused instead of duplicated.
4. Run the current automated test suite and establish the baseline.

Do not assume the architecture described below already maps directly to existing filenames or classes. Adapt the implementation cleanly to the repository.

Do not perform a large refactor merely to match terminology in this handoff.

---

# Step 2 — Introduce `AccountSnapshot`

Create a clean model representing the current factual state of an account.

Conceptually it should support data such as:

```python
AccountSnapshot(
    skills=...,
    quests=...,
    quest_points=...,
    bank_items=...,
    inventory=...,
    equipment=...,
    unlocks=...,
    spellbooks=...,
    diaries=...,
    combat_achievements=...,
    freshness=...,
)
```

Not every field must be populated in Milestone 1 if the existing application does not yet track it.

For Quest Cape, skills and quest completion are the critical fields.

Prefer a service boundary roughly equivalent to:

```python
snapshot = account_service.get_snapshot(player_id)
```

### Hard architectural rule

`AccountSnapshot` must not depend on recommendation-domain concepts such as:

```text
recommendation scores
roadmap weights
candidate rankings
golden corpus
hysteresis
PvP utility
advisor scoring
```

It represents facts, not recommendations.

Reuse the existing RuneLite/database synchronization implementation wherever practical. This milestone is about creating a clean read boundary over existing state, not rewriting synchronization.

---

# Step 3 — Requirement evaluation

Create or consolidate a deterministic requirement evaluator.

It should support at least the requirements necessary for OSRS quests:

```python
SkillRequirement(skill, level)
QuestRequirement(quest, completed=True)
```

If the repository already contains equivalent abstractions, reuse/refactor those instead of creating parallel systems.

The core behavior should be roughly:

```python
evaluate_requirement(snapshot, requirement) -> RequirementResult
```

A result should contain more information than a boolean.

For example:

```python
RequirementResult(
    satisfied=False,
    current=66,
    required=70,
    reason="Agility 66/70",
)
```

The evaluator must be deterministic and independent of recommendation scoring.

Do not build a universal expression language or generalized goal DSL.

---

# Step 4 — Implement Quest Cape as the only goal

Implement exactly one goal for this milestone:

```text
quest_cape
```

Use authoritative quest metadata already present in the repository if possible.

The goal evaluator needs enough information to understand:

- whether each relevant quest is completed;
- prerequisite quests;
- required skill levels;
- whether the quest can currently be started/completed based on modeled requirements.

Expose an application/service operation equivalent to:

```python
get_goal_status("quest_cape")
```

The result should be structured, deterministic data.

For example:

```json
{
  "goal": "quest_cape",
  "completed": 112,
  "remaining": 48,
  "available_now": 17,
  "blocked": 31,
  "skill_blockers": [
    {
      "skill": "agility",
      "current": 66,
      "thresholds": [68, 70]
    }
  ]
}
```

Exact schema may differ if a better representation fits the existing application.

Important characteristics:

- distinguish completed vs remaining quests;
- identify remaining quests that are currently available;
- explain why blocked quests are blocked;
- aggregate meaningful unmet skill thresholds;
- retain enough quest-level detail for ChatGPT to inspect the reasoning.

### Do not rank quests here.

`get_goal_status` answers:

> "What is true?"

It does not answer:

> "What should the player do?"

---

# Step 5 — `get_available_actions`

Add a deterministic operation equivalent to:

```python
get_available_actions(goal="quest_cape")
```

For Milestone 1 support exactly two action types:

```text
complete_quest
train_skill
```

## Quest actions

Generate `complete_quest` actions for appropriate unfinished quests that are currently actionable.

For example:

```json
{
  "type": "complete_quest",
  "quest": "regicide"
}
```

## Skill actions

Generate actions only for meaningful required thresholds.

Example:

If the player has:

```text
Agility 66
```

and outstanding quest requirements include:

```text
68
70
```

generate:

```text
Train Agility → 68
Train Agility → 70
```

Do **not** generate every intermediate level:

```text
67
68
69
70
```

The returned result should distinguish naturally doable quests from useful requirement-clearing actions.

Again:

### No recommendation score.
### No priority score.
### No ranking engine.

It is acceptable to use deterministic presentation ordering, such as quest name or skill/level, as long as that ordering is not represented as recommendation quality.

---

# Step 6 — Counterfactual `evaluate_action`

Implement:

```python
evaluate_action(goal="quest_cape", action=...)
```

This must be completely read-only.

Conceptually:

```python
before = evaluate_goal(real_snapshot)

hypothetical = copy(real_snapshot)
apply(action, hypothetical)

after = evaluate_goal(hypothetical)

return diff(before, after)
```

Never persist the hypothetical state.

Support exactly these mutations initially.

## `train_skill`

Example:

```json
{
  "type": "train_skill",
  "skill": "agility",
  "target_level": 70
}
```

Useful result information includes:

```text
requirements newly satisfied
quests newly available
blocked quests helped but still blocked
remaining blockers changed
```

Example:

```json
{
  "requirements_newly_satisfied": 4,
  "quests_newly_available": ["Quest A", "Quest B"],
  "quests_helped_but_still_blocked": ["Quest C", "Quest D"]
}
```

## `complete_quest`

Example:

```json
{
  "type": "complete_quest",
  "quest": "regicide"
}
```

Useful result information includes:

```text
Quest Cape completion delta
quests newly available
downstream quest chain affected
remaining blocker changes
```

The evaluator should report factual impact rather than assign value.

Do not return fields such as:

```text
score
priority
recommendation
utility
best_action
efficiency_rating
```

ChatGPT can compare multiple evaluations itself.

---

# Step 7 — MCP surface

Expose the Quest Cape slice through the existing MCP server.

At minimum ChatGPT needs operations equivalent to:

```text
get_account_summary
get_goal_status
get_available_actions
evaluate_action
```

If account-summary functionality already exists, reuse it.

Do not create dozens of MCP tools.

Prefer a small, clear interface with structured JSON responses.

The MCP interface should expose enough context that ChatGPT can:

1. understand the current account;
2. see Quest Cape status;
3. inspect available actions;
4. select several interesting actions;
5. counterfactually evaluate them;
6. explain the tradeoffs conversationally.

Tool descriptions should clearly state that:

- results are deterministic account facts;
- `evaluate_action` is hypothetical and read-only;
- the server does not decide which action the player should choose.

---

# Tests

Add focused automated coverage.

## `AccountSnapshot`

Verify:

- data matches the existing account-state source;
- snapshot creation does not invoke recommendation generation;
- snapshot code has no dependency on recommendation-domain classes;
- missing/unknown data is represented explicitly rather than silently fabricated.

## Requirements

Cover at least:

- satisfied skill requirement;
- unsatisfied skill requirement;
- completed quest prerequisite;
- incomplete quest prerequisite;
- multiple blockers on one quest.

## Quest Cape

Verify:

- completed quest counts;
- remaining quest counts;
- currently available quests;
- blocked quests;
- skill blocker thresholds;
- prerequisite chains.

Use fixed test fixtures rather than the developer's live account for core unit tests.

## Available actions

Verify:

- completed quests are not proposed;
- blocked quests are not incorrectly labeled available;
- appropriate available quests generate actions;
- skill actions use meaningful thresholds;
- intermediate irrelevant levels are not generated;
- duplicate threshold actions are consolidated where appropriate.

## Counterfactual evaluation

Verify:

### Training

A hypothetical skill increase can:

- satisfy requirements;
- unlock quests;
- partially advance quests without fully unlocking them.

### Quest completion

A hypothetical completed quest can:

- increment Quest Cape progress;
- unlock direct dependents;
- affect downstream chains.

### Read-only safety

After every evaluation:

```text
database/account state before == database/account state after
```

This deserves an explicit regression test.

## MCP

Add interface-level tests verifying that:

```text
get_goal_status
get_available_actions
evaluate_action
```

return the same underlying domain/application results as direct service calls.

Avoid duplicating business logic inside MCP handlers.

---

# Acceptance test

Create either an automated integration test or a documented manual acceptance procedure for this conversation:

> "I'm working toward my Quest Cape. What should I do next?"

The MCP must give ChatGPT enough information to perform approximately this sequence:

```text
get_goal_status("quest_cape")

get_available_actions("quest_cape")

evaluate_action(<interesting quest>)

evaluate_action(<interesting skill threshold>)

possibly evaluate_action(<second alternative>)
```

ChatGPT—not the OSRS application—then explains why one action may be attractive compared with another.

The application itself should never need a `recommend_best_action()` function for this flow.

---

# Explicit non-goals

Do not implement any of the following during Milestone 1:

- generic universal goal framework;
- general goal DSL;
- diary goals;
- Fire Cape goal;
- Barrows Gloves goal;
- arbitrary user-defined goals;
- recommendation rankings;
- recommendation scoring;
- efficiency scoring;
- time-to-completion optimization;
- XP/hour modeling;
- GP/hour modeling;
- quest-guide generation;
- full dashboard redesign;
- legacy recommender deletion;
- database cleanup solely for the new architecture;
- golden corpus removal;
- migration of every existing feature onto `AccountSnapshot`;
- gear refactoring;
- broad MCP expansion.

Avoid "future-proofing" Milestone 1 into another large framework.

Implement Quest Cape concretely. Extract abstractions only where the implementation naturally requires them.

---

# Compatibility requirement

Do not break the current application while introducing this slice.

The legacy recommender may continue using its existing architecture during Milestone 1.

Prefer:

```text
new clean path alongside old system
```

over:

```text
rewrite everything before new path works
```

Any modifications to shared account synchronization or persistence code must preserve existing behavior unless a demonstrated bug requires a correction.

---

# Definition of Done

Milestone 1 is complete when all of these are true:

```text
[ ] AccountSnapshot exists as a clean factual account-state boundary
[ ] AccountSnapshot does not depend on recommendation-domain logic
[ ] Existing RuneLite-synced account state can populate the snapshot
[ ] Quest Cape remaining quests are calculated correctly
[ ] Quest prerequisites are evaluated correctly
[ ] Skill blockers and meaningful thresholds are calculated correctly
[ ] get_goal_status("quest_cape") works
[ ] get_available_actions("quest_cape") works
[ ] evaluate_action supports complete_quest
[ ] evaluate_action supports train_skill
[ ] hypothetical evaluations never mutate persisted account state
[ ] MCP exposes the required operations
[ ] MCP handlers delegate to application/domain services rather than reimplementing logic
[ ] automated tests cover the new behavior
[ ] existing regression suite still passes
[ ] ChatGPT can use the MCP to answer "What should I do next for Quest Cape?"
```

---

# Implementation approach

Work through the milestone independently.

Use the existing repository as the source of truth for actual class names, persistence models, schemas, package structure, and MCP conventions.

Make reasonable implementation decisions without stopping for confirmation when the intent is clear.

If the repository differs significantly from the architecture assumed here, preserve the architectural intent rather than mechanically reproducing these sample names.

Keep changes narrowly scoped to Milestone 1.

At completion, provide:

1. A concise architecture summary.
2. Files added/changed.
3. Important design decisions.
4. Tests added.
5. Exact commands used to verify the implementation.
6. Test/lint/type-check results.
7. Any remaining limitations or data-quality gaps.
8. A short manual MCP acceptance procedure I can run against my actual RuneLite-synced account.
9. Any observations that should inform Milestone 2, but **do not implement Milestone 2**.

Do not commit changes unless explicitly instructed to do so.
