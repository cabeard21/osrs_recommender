import { expect, it } from "vitest";
import { optimizationRequest } from "../api/httpClient";
import {
  newDraft,
  newRole,
  normalize,
  initialState,
  reducer,
  saveDrafts,
  readDrafts,
} from "../state/scenario";
import { contextFixture, FixtureGearClient } from "../fixtures/client";

it("seeds independent catalog identities and incomplete edits into Multi roles", () => {
  const state = initialState();
  state.single.draft.targetSelection = {
    key: "goblin-standard",
    catalog_revision: "rev",
  };
  state.single.draft.combatTarget = {
    name: "Goblin",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
  };
  const multi = reducer(state, { type: "navigate", mode: "multi" }).multi.draft;
  const request = optimizationRequest(normalize(multi, "snapshot"));
  expect(request.roles.map((role) => role.target_selection)).toEqual([
    state.single.draft.targetSelection,
    state.single.draft.targetSelection,
  ]);
  expect(multi.roles[0].combatTarget).not.toBe(multi.roles[1].combatTarget);
  expect(multi.targetSelection).toBeUndefined();
});

it("does not overwrite an explicit role target from a stale top-level selection", () => {
  const draft = newDraft();
  draft.targetSelection = { key: "old", catalog_revision: "rev" };
  draft.combatTarget = {
    name: "Old",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
  };
  draft.roles[0].combatTarget = {
    name: "Current",
    defence_level: 10,
    magic_level: 1,
    bonuses: {},
  };
  draft.roles[0].targetSelection = { key: "current", catalog_revision: "rev" };
  expect(
    optimizationRequest(normalize(draft, "snapshot")).roles[0].target_selection
      ?.key,
  ).toBe("current");
});

it("serializes a joint request with per-role targets and looping phases", () => {
  const draft = newDraft();
  draft.roles.push(newRole(2));
  Object.assign(draft, {
    globalLocks: { head: null },
    topology: "ordered",
    orderedRoles: ["role-1", "role-2", "role-1"],
    loop: true,
  });
  Object.assign(draft.roles[1], {
    combatTarget: {
      name: "Other",
      defence_level: 50,
      magic_level: 60,
      bonuses: {},
    },
    weight: "0.5",
  });
  const request = optimizationRequest(normalize(draft, "snapshot", true));
  expect(request.roles).toHaveLength(2);
  expect(request.roles[1]).toMatchObject({
    weight: 0.5,
    target: { name: "Other", defence_level: 50 },
  });
  expect(request).toMatchObject({
    locks: { head: null },
    ordered_roles: ["role-1", "role-2", "role-1"],
    loop: true,
    base_role: "role-1",
  });
  expect(request).not.toHaveProperty("transitions");
});

it("preserves incomplete role targets and new topology fields in draft storage", () => {
  const state = initialState();
  state.context = contextFixture;
  state.multi.draft.roles.push(newRole(2));
  Object.assign(state.multi.draft, {
    topology: "ordered",
    orderedRoles: ["role-1", "role-2", "role-1"],
    loop: true,
    globalLocks: { head: null },
  });
  state.multi.draft.roles[1].combatTarget = {
    name: "Target",
    defence_level: 10,
    magic_level: 1,
    bonuses: {},
  };
  state.multi.draft.roles[1].targetInputs = { defence_level: "" };
  saveDrafts(state, sessionStorage);
  const restored = readDrafts(contextFixture.playerId, sessionStorage)!;
  expect(restored.multi.roles[1].targetInputs?.defence_level).toBe("");
  expect(() => normalize(restored.multi, "snapshot", true)).toThrow(/target/);
  expect(restored.multi.orderedRoles).toEqual(["role-1", "role-2", "role-1"]);
});

it("migrates v1 Multi targets into independent role drafts without losing incomplete input", () => {
  const draft = newDraft();
  draft.roles.push(newRole(2));
  draft.target = "Legacy target";
  draft.defence = "";
  sessionStorage.setItem(
    "gear-drafts-v1:legacy-player",
    JSON.stringify({
      version: 1,
      single: newDraft(),
      multi: draft,
      multiSeeded: true,
    }),
  );
  const restored = readDrafts("legacy-player", sessionStorage)!;
  expect(restored.multi.roles[0].combatTarget?.name).toBe("Legacy target");
  expect(restored.multi.roles[1].targetInputs?.defence_level).toBe("");
  expect(() => normalize(restored.multi, "snapshot", true)).toThrow(/target/);
  restored.multi.roles[0].combatTarget!.name = "Changed";
  expect(restored.multi.roles[1].combatTarget!.name).toBe("Legacy target");
});

it("copies a Single result's submitted target into an existing Multi draft", async () => {
  let state = initialState();
  state.context = contextFixture;
  state.single.draft.target = "Single submitted target";
  state.single.draft.defence = "70";
  const scenario = normalize(state.single.draft, contextFixture.snapshotId);
  state.single.result = await new FixtureGearClient("none", 0).optimize(
    scenario,
    new AbortController().signal,
  );
  state.multiSeeded = true;
  state.multi.draft.target = "Different Multi target";
  state.multi.draft.roles.push(newRole(2));
  state = reducer(state, { type: "use-single-in-multi" });
  expect(state.multi.draft.roles[0].combatTarget).toMatchObject({
    name: "Single submitted target",
    defence_level: 70,
  });
  expect(state.multi.draft.roles[0].targetInputs).toEqual({});
  expect(state.multi.draft.target).toBe("Different Multi target");
});

it("keeps the pending Multi run and its transition selection across a catalog refresh", async () => {
  let state = initialState();
  state = reducer(state, {
    type: "context",
    context: { ...contextFixture, live: { catalog_version: "old" } as never },
  });
  state = reducer(state, { type: "navigate", mode: "multi" });
  const scenario = normalize(state.multi.draft, contextFixture.snapshotId);
  const result = await new FixtureGearClient("none", 0).optimize(
    scenario,
    new AbortController().signal,
  );
  state = reducer(state, {
    type: "start",
    mode: "multi",
    scenario,
    generation: 1,
  });
  state = reducer(state, {
    type: "ui",
    mode: "multi",
    patch: { selectedTransition: "role-2:role-1" },
  });
  expect(state.multi.pending).toBe(true);
  expect(state.multi.generation).toBe(1);
  state = reducer(state, {
    type: "context",
    context: { ...contextFixture, live: { catalog_version: "new" } as never },
  });
  expect(state.multi.pending).toBe(true);
  expect(state.multi.selectedTransition).toBe("role-2:role-1");
  state = reducer(state, {
    type: "success",
    mode: "multi",
    generation: 1,
    result,
  });
  expect(state.multi.result).toEqual(result);
  expect(state.multi.contextStale).toBe(true);
  expect(state.multi.pending).toBe(false);
  expect(state.single.result).toBeNull();
});

it.each([
  { roles: [] },
  { baseRole: "missing" },
  { topology: "explicit", transitions: [] },
  { topology: "ordered", orderedRoles: ["missing", "role-1"] },
  {
    globalLocks: { weapon: 1 },
    roles: [{ ...newRole(1), locks: { weapon: 2 } }, newRole(2)],
  },
  { roles: [{ ...newRole(1), utility: true }, newRole(2)] },
  {
    roles: [
      { ...newRole(1), weight: "0" },
      { ...newRole(2), weight: "0" },
    ],
  },
])("rejects inconsistent joint drafts %j", (patch) => {
  const draft = { ...newDraft(), roles: [newRole(1), newRole(2)], ...patch };
  expect(() =>
    normalize(draft as ReturnType<typeof newDraft>, "snapshot", true),
  ).toThrow();
});

it("rejects dangling roles and contradictory global constraints", () => {
  const draft = newDraft();
  draft.roles.push(newRole(2));
  Object.assign(draft, {
    topology: "explicit",
    transitions: [["missing", "role-1"]],
  });
  expect(() => normalize(draft, "snapshot", true)).toThrow(/transition/i);
  Object.assign(draft, {
    topology: "base",
    globalLocks: { weapon: 4151 },
    exclusions: [4151],
  });
  expect(() => normalize(draft, "snapshot", true)).toThrow(/excluded/i);
});

it("preserves backend base topology for utility roles attached to a different parent", () => {
  const draft = newDraft();
  draft.roles = [
    newRole(1),
    newRole(2),
    {
      ...newRole(3),
      utility: true,
      parentRole: "role-2",
      locks: { weapon: 4151 },
    },
  ];
  const request = optimizationRequest(normalize(draft, "snapshot", true));
  expect(request.roles[2]).toMatchObject({
    style: "special",
    parent_role: "role-2",
    locks: { weapon: 4151 },
  });
  expect((request as Record<string, unknown>).transitions).toEqual([
    ["role-1", "role-2"],
    ["role-2", "role-1"],
  ]);
  // Python adds the parent↔utility transitions; browser must not add base↔utility edges.
});
