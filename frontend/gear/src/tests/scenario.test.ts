import { describe, expect, it } from "vitest";
import {
  initialState,
  newDraft,
  newRole,
  normalize,
  readDrafts,
  reducer,
  saveDrafts,
  storageKey,
} from "../state/scenario";
import { contextFixture, FixtureGearClient } from "../fixtures/client";
const reply = () =>
  new FixtureGearClient("none", 0).optimize(
    normalize(newDraft(), contextFixture.snapshotId),
    new AbortController().signal,
  );
describe("scenario normalization", () => {
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
it("rejects publication when the account fixture changes during a pending run", async () => {
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
  expect(state.single.result).toBeNull();
  expect(state.single.error).toContain("context changed");
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
