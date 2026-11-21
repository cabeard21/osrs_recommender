import { describe, expect, it } from "vitest";
import type { OptimizationDTO } from "../api/contracts";
import {
  initialState,
  newDraft,
  newRole,
  normalize,
  readDrafts,
  reducer,
  saveDrafts,
  storageKey,
  upgradeStoredDraft,
} from "../state/scenario";
import { contextFixture, FixtureGearClient } from "../fixtures/client";
import { wildernessRiskCap, normalizedWilderness } from "../api/wilderness";
import { MAX_BUDGET_GP } from "../state/budget";
const reply = () =>
  new FixtureGearClient("none", 0).optimize(
    normalize(newDraft(), contextFixture.snapshotId),
    new AbortController().signal,
  );
describe("scenario normalization", () => {
  it("interprets an implicit trip size as uncapped risk and keeps legacy caps", () => {
    const wilderness = {
      depth: "level_21_plus",
      skulled: true,
      protect_item: false,
      spell_casts: 17,
    } as const;
    const objectives = [{ kind: "wilderness_loss_gp" as const }];
    expect(
      wildernessRiskCap({ budget_gp: 5, wilderness, objectives }),
    ).toBeNull();
    expect(wildernessRiskCap({ budget_gp: 5, wilderness })).toBe(5);
    expect(normalizedWilderness(wilderness, objectives)).toMatchObject({
      attacks_per_setup: 17,
    });
    expect(
      normalizedWilderness({ ...wilderness, spell_casts: null }, objectives),
    ).toMatchObject({ attacks_per_setup: 100 });
  });
  it("preserves the trip length and distinguishes zero loss from an uncapped trip", () => {
    const draft = {
      ...newDraft(),
      wilderness: {
        depth: "level_21_plus",
        skulled: false,
        protect_item: false,
      } as const,
      objectives: [{ kind: "wilderness_loss_gp" as const }],
      wildernessSpellCasts: "27",
    };
    expect(normalize(draft, "snapshot").request.wilderness).toEqual({
      ...draft.wilderness,
      attacks_per_setup: 27,
    });
    expect(
      normalize({ ...draft, wildernessLimitLoss: true }, "snapshot").request
        .wilderness?.max_loss_gp,
    ).toBe(0);
    expect(() =>
      normalize({ ...draft, wilderness: undefined }, "snapshot"),
    ).toThrow(/Wilderness/);
  });
  it("migrates legacy Wilderness drafts without converting their risk amount into a purchase cap", () => {
    const wilderness = {
      depth: "level_21_plus",
      skulled: false,
      protect_item: false,
    } as const;
    const old = {
      ...newDraft(),
      budget: "100k",
      wilderness,
      wildernessRiskBudget: undefined,
    };
    const migrated = upgradeStoredDraft(old)!;
    expect(migrated).toMatchObject({
      budget: String(MAX_BUDGET_GP),
      wildernessRiskBudget: "100k",
    });
    expect(normalize(migrated, "snapshot").request).toMatchObject({
      budget_gp: MAX_BUDGET_GP,
      wilderness: { ...wilderness, max_loss_gp: 100_000, spell_casts: 100 },
    });
    expect(upgradeStoredDraft(migrated)).toMatchObject({
      budget: String(MAX_BUDGET_GP),
      wildernessRiskBudget: "100k",
    });
  });
  it("retains a historical explicit zero loss cap when selecting the objective", () => {
    const draft = upgradeStoredDraft({
      ...newDraft(),
      wildernessLimitLoss: undefined,
      wildernessRiskBudget: "0",
      wilderness: {
        depth: "level_21_plus",
        skulled: true,
        protect_item: false,
      },
    })!;
    expect(
      normalize(
        { ...draft, objectives: [{ kind: "wilderness_loss_gp" }] },
        "snapshot",
      ).request.wilderness?.max_loss_gp,
    ).toBe(0);
  });
  it("validates the Wilderness cast count for Magic and ignores hidden invalid values", () => {
    const draft = {
      ...newDraft(),
      wilderness: {
        depth: "level_21_plus",
        skulled: false,
        protect_item: false,
      } as const,
      wildernessSpellCasts: "10001",
    };
    expect(normalize(draft, "snapshot").request.wilderness?.spell_casts).toBe(
      100,
    );
    const magic = {
      ...draft,
      roles: [{ ...draft.roles[0], style: "magic" as const }],
    };
    expect(() => normalize(magic, "snapshot")).toThrow(/casts.*1 to 10000/i);
    expect(
      normalize({ ...magic, wildernessSpellCasts: "1" }, "snapshot").request
        .wilderness?.spell_casts,
    ).toBe(1);
  });
  it("preserves backend defaults and explicit empty locks", () => {
    const d = newDraft();
    d.roles[0].locks = { ammo: null };
    const s = normalize(d, "snapshot");
    expect(s.request).toMatchObject({
      budget_gp: 0,
      mode: "usable",
      max_swaps: 8,
      reserved_supply_slots: 12,
      skill_overrides: {},
      expected_snapshot_id: "snapshot",
    });
    expect(s.request.roles[0].locks).toEqual({ ammo: null });
  });
  it.each(["", "-1", "1.5", "NaN"])(
    "rejects invalid integer budget %s",
    (budget) => {
      expect(() => normalize({ ...newDraft(), budget }, "x")).toThrow("Budget");
    },
  );
  it("rejects lock/exclusion conflicts", () => {
    const d = newDraft();
    d.roles[0].locks = { weapon: 4151 };
    d.exclusions = [4151];
    expect(() => normalize(d, "x")).toThrow("locked item");
  });
  it("keeps assumptions request-local and requires future access", () => {
    const d = newDraft();
    d.assumptions.attack = "99";
    expect(() => normalize(d, "x")).toThrow("hypothetical");
    d.mode = "future";
    expect(normalize(d, "x").request.skill_overrides).toEqual({ attack: 99 });
    expect(contextFixture).not.toHaveProperty("skill_overrides");
  });
});

it("clears reverted draft changes while retaining account freshness", async () => {
  const draft = { ...newDraft(), budget: "10k" };
  const scenario = normalize(draft, contextFixture.snapshotId);
  const result = await new FixtureGearClient("none", 0).optimize(
    scenario,
    new AbortController().signal,
  );
  let state = reducer(initialState(), {
    type: "context",
    context: contextFixture,
  });
  state = reducer(state, { type: "edit", mode: "single", draft });
  state = reducer(state, {
    type: "start",
    mode: "single",
    scenario,
    generation: 2,
  });
  state = reducer(state, {
    type: "success",
    mode: "single",
    generation: 2,
    result,
  });
  state = reducer(state, {
    type: "edit",
    mode: "single",
    draft: { ...draft, budget: "12k" },
  });
  expect(state.single.draftChanged).toBe(true);
  state = reducer(state, {
    type: "edit",
    mode: "single",
    draft: { ...draft, budget: "10000" },
  });
  expect(state.single.outdated).toBe(false);
  expect(state.single.acceptedDraft).toEqual(draft);
  state = reducer(state, {
    type: "context",
    context: { ...contextFixture, snapshotId: "updated" },
  });
  expect(state.single).toMatchObject({
    outdated: true,
    draftChanged: false,
    contextStale: true,
  });
});

it("resets archive selections and rejects late points of a same-scenario run", async () => {
  const first = await reply();
  const live = (runId: string) =>
    ({
      run_id: runId,
      result: {},
      scenario: { include_untradeables: false },
    }) as unknown as OptimizationDTO;
  const point = {
    type: "objective-select" as const,
    mode: "single" as const,
    fingerprint: first.fingerprint,
    runId: "first",
    groupId: "frontier-global-1",
    swapLimit: 1,
    solution: {
      ...first.solutions[0],
      id: "frontier-global-1-objective-point",
    },
  };
  let state = initialState();
  state = reducer(state, {
    type: "start",
    mode: "single",
    scenario: first.scenario,
    generation: 1,
  });
  state = reducer(state, {
    type: "success",
    mode: "single",
    generation: 1,
    result: { ...first, live: live("first") },
  });
  state = reducer(state, point);
  expect(state.single.objectiveSwapLimit).toBe(1);
  const pendingPoint = {
    ...point,
    selectionRevision: state.single.selectionRevision,
  };
  state = reducer(state, {
    ...point,
    solution: { ...point.solution, id: "frontier-global-1-objective-newer" },
  });
  expect(reducer(state, pendingPoint)).toBe(state);
  state = reducer(state, {
    type: "start",
    mode: "single",
    scenario: first.scenario,
    generation: 2,
  });
  state = reducer(state, {
    type: "success",
    mode: "single",
    generation: 2,
    result: { ...first, live: live("second") },
  });
  expect(state.single.objectiveSwapLimit).toBeUndefined();
  expect(reducer(state, point)).toBe(state);
});
it("normalizes independent Auto configurations while rejecting Auto utility roles", () => {
  const draft = {
    ...newDraft(),
    roles: [newRole(1), newRole(2)].map((role) => ({
      ...role,
      autoDiscipline: true,
      allowedDisciplines: ["melee", "ranged"] as ("melee" | "ranged")[],
    })),
  };
  expect(normalize(draft, "snapshot").request.roles).toHaveLength(2);
  expect(() =>
    normalize(
      {
        ...draft,
        roles: [draft.roles[0], { ...draft.roles[1], utility: true }],
      },
      "snapshot",
    ),
  ).toThrow("ordinary combat configuration");
});
describe("workspace reducer", () => {
  it("seeds multi once and preserves independent drafts across navigation", () => {
    let s = initialState();
    s.single.draft.budget = "123";
    s = reducer(s, { type: "navigate", mode: "multi" });
    expect(s.multi.draft.roles).toHaveLength(2);
    expect(s.multi.draft.budget).toBe("123");
    s = reducer(s, {
      type: "edit",
      mode: "multi",
      draft: { ...s.multi.draft, budget: "456" },
    });
    s = reducer(s, { type: "navigate", mode: "single" });
    expect(s.single.draft.budget).toBe("123");
    s = reducer(s, { type: "navigate", mode: "multi" });
    expect(s.multi.draft.budget).toBe("456");
  });
  it("isolates submitted scenarios, invalidates edited results, and ignores stale responses", async () => {
    let s = initialState();
    const result = await reply();
    s = reducer(s, {
      type: "start",
      mode: "single",
      scenario: result.scenario,
      generation: 1,
    });
    s = reducer(s, { type: "success", mode: "single", generation: 1, result });
    s = reducer(s, {
      type: "edit",
      mode: "single",
      draft: { ...s.single.draft, budget: "42" },
    });
    expect(s.single.outdated).toBe(true);
    expect(s.single.result?.scenario.request.budget_gp).toBe(0);
    expect(s.single.submitted?.request.budget_gp).toBe(0);
    const after = reducer(s, {
      type: "success",
      mode: "single",
      generation: 1,
      result,
    });
    expect(after).toBe(s);
  });
  it("retains previous accepted results and suppresses responses after cancellation", async () => {
    let s = initialState();
    const result = await reply();
    for (const generation of [1, 2]) {
      s = reducer(s, {
        type: "start",
        mode: "single",
        scenario: result.scenario,
        generation,
      });
      s = reducer(s, { type: "success", mode: "single", generation, result });
    }
    expect(s.single.previous).toEqual(result);
    s = reducer(s, {
      type: "start",
      mode: "single",
      scenario: result.scenario,
      generation: 3,
    });
    s = reducer(s, { type: "cancel", mode: "single" });
    expect(
      reducer(s, { type: "success", mode: "single", generation: 3, result }),
    ).toBe(s);
  });
  it("isolates trial equipment and rejects trials after draft or curve changes", async () => {
    let s = initialState();
    const result = await reply();
    s = reducer(s, {
      type: "start",
      mode: "single",
      scenario: result.scenario,
      generation: 1,
    });
    s = reducer(s, { type: "success", mode: "single", generation: 1, result });
    const equipment = {
      ...result.solutions[0].loadouts[0].equipment,
      weapon: 9185,
    };
    const trial = await new FixtureGearClient().evaluate(
      result,
      "best-found",
      "role-1",
      equipment,
    );
    s = reducer(s, { type: "trial", mode: "single", trial });
    expect(s.single.trial?.equipment.weapon).toBe(9185);
    expect(s.single.result?.solutions[0].loadouts[0].equipment.weapon).toBe(
      4151,
    );
    expect(s.single.draft.roles[0].locks).toEqual({});
    s = reducer(s, {
      type: "edit",
      mode: "single",
      draft: { ...s.single.draft, budget: "1" },
    });
    expect(s.single.trial).toBeNull();
    expect(
      reducer(s, { type: "trial", mode: "single", trial }).single.trial,
    ).toBeNull();
  });
  it("invalidates results when context fingerprints change", async () => {
    const result = await reply();
    let s = initialState();
    s = reducer(s, {
      type: "start",
      mode: "single",
      scenario: result.scenario,
      generation: 1,
    });
    s = reducer(s, { type: "success", mode: "single", generation: 1, result });
    s = reducer(s, {
      type: "context",
      context: { ...contextFixture, snapshotId: "changed" },
    });
    expect(s.single.outdated).toBe(true);
  });
  it("persists only versioned drafts per fixture player", () => {
    const s = initialState();
    s.context = contextFixture;
    s.single.draft.mode = "future";
    s.single.draft.assumptions.attack = "99";
    saveDrafts(s, sessionStorage);
    const raw = sessionStorage.getItem(storageKey(contextFixture.playerId))!;
    expect(raw).not.toContain("snapshot");
    expect(raw).not.toContain("result");
    expect(
      readDrafts(contextFixture.playerId, sessionStorage)?.single.assumptions
        .attack,
    ).toBe("99");
    expect(readDrafts("another-player", sessionStorage)).toBeNull();
    sessionStorage.setItem(storageKey(contextFixture.playerId), "{bad");
    expect(readDrafts(contextFixture.playerId, sessionStorage)).toBeNull();
  });
});
it("carries Single equipment into Multi with all eleven slots explicitly locked", async () => {
  let state = initialState();
  const result = await reply();
  state = reducer(state, {
    type: "start",
    mode: "single",
    scenario: result.scenario,
    generation: 1,
  });
  state = reducer(state, {
    type: "success",
    mode: "single",
    generation: 1,
    result,
  });
  state = reducer(state, { type: "use-single-in-multi" });
  expect(state.mode).toBe("multi");
  expect(Object.keys(state.multi.draft.roles[0].locks)).toHaveLength(11);
  expect(state.multi.draft.roles[0].locks.ammo).toBeNull();
  expect(state.multi.draft.roles).toHaveLength(2);
});
it("preserves incomplete draft fields through reload without persisting results", () => {
  const state = initialState();
  state.context = contextFixture;
  state.single.draft.budget = "";
  state.single.draft.roles[0].weight = "";
  saveDrafts(state, sessionStorage);
  expect(
    readDrafts(contextFixture.playerId, sessionStorage)?.single.budget,
  ).toBe("");
});
it("records a rejected result as a finished failed attempt", async () => {
  const result = await reply();
  const startedAt = "2026-11-20T17:00:00.000Z";
  const finishedAt = "2026-11-20T17:01:00.000Z";
  const pending = reducer(initialState(), {
    type: "start",
    mode: "single",
    scenario: result.scenario,
    generation: 1,
    attempt: {
      status: "running",
      playerId: contextFixture.playerId,
      snapshotId: result.snapshotId,
      startedAt,
      finishedAt: null,
      error: null,
      progressId: null,
      progress: null,
      retryCount: 0,
    },
  });
  const state = reducer(pending, {
    type: "success",
    mode: "single",
    generation: 1,
    at: finishedAt,
    result: { ...result, snapshotId: "unrelated-snapshot" },
  });
  expect(state.single.pending).toBe(false);
  expect(state.single.result).toBeNull();
  expect(state.single.attempt).toMatchObject({
    status: "failed",
    finishedAt,
    error: { code: "invalid_response", message: state.single.error },
  });
});
it("retains the submitted snapshot when account observations change during a pending run", async () => {
  const result = await reply();
  let state = initialState();
  state = reducer(state, {
    type: "start",
    mode: "single",
    scenario: result.scenario,
    generation: 1,
  });
  state = reducer(state, {
    type: "context",
    context: { ...contextFixture, snapshotId: "new" },
  });
  state = reducer(state, {
    type: "success",
    mode: "single",
    generation: 1,
    result,
  });
  expect(state.single.result?.snapshotId).toBe(result.snapshotId);
  expect(state.single.contextStale).toBe(true);
  expect(state.single.error).toBeNull();
});

it.each(["", "1.5", "10001", "-10001"])(
  "rejects invalid global flat armour %s",
  (armour) => {
    const draft = newDraft();
    draft.targetInputs = { flat_armour: armour };
    draft.combatTarget = {
      name: "Custom",
      defence_level: 1,
      magic_level: 1,
      bonuses: {},
      flat_armour: Number(armour),
    };
    expect(() => normalize(draft, "snapshot")).toThrow(/flat armour/i);
  },
);
it("preserves negative custom global armour", () => {
  const draft = newDraft();
  draft.combatTarget = {
    name: "Custom",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
    flat_armour: -5,
  };
  expect(
    normalize(draft, "snapshot").request.target.definition?.flat_armour,
  ).toBe(-5);
});

it.each(["", "-1", "1.5", "65"])("rejects invalid target size %s", (size) => {
  for (const scope of ["global", "role"]) {
    const draft = newDraft();
    const target = {
      name: "Custom",
      defence_level: 1,
      magic_level: 1,
      bonuses: {},
      size: Number(size),
    };
    if (scope === "global") {
      draft.combatTarget = target;
      draft.targetInputs = { size };
    } else {
      draft.roles[0].combatTarget = target;
      draft.roles[0].targetInputs = { size };
    }
    expect(() => normalize(draft, "snapshot")).toThrow(
      /size|target configuration/i,
    );
  }
});

it("preserves global and per-role target size", () => {
  const draft = newDraft();
  const target = {
    name: "Custom",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
    size: 5,
  };
  draft.combatTarget = target;
  draft.roles[0].combatTarget = { ...target, size: 3 };
  const request = normalize(draft, "snapshot").request;
  expect(request.target.definition?.size).toBe(5);
  expect(request.roles[0].combatTarget?.size).toBe(3);
});

it("preserves role defence bonuses of -100 when edited", () => {
  const draft = newDraft();
  draft.roles[0].combatTarget = {
    name: "Acidic Bloodveld",
    defence_level: 2,
    magic_level: 1,
    bonuses: { slash: -100 },
    ranged_heavy: -100,
  };
  draft.roles[0].targetInputs = {
    "bonuses.slash": "-100",
    ranged_heavy: "-100",
  };
  const target = normalize(draft, "snapshot").request.roles[0].combatTarget;
  expect(target?.bonuses.slash).toBe(-100);
  expect(target?.ranged_heavy).toBe(-100);
});

it("preserves a zero size without assuming a footprint", () => {
  const draft = newDraft();
  const target = {
    name: "Custom",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
    size: 0,
  };
  draft.combatTarget = target;
  draft.roles[0].combatTarget = target;
  const request = normalize(draft, "snapshot").request;
  expect(request.target.definition?.size).toBe(0);
  expect(request.roles[0].combatTarget?.size).toBe(0);
});
