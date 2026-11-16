import { expect, it } from "vitest";
import {
  canonicalObjectives,
  objectiveId,
  legacyObjectives,
  quickObjectives,
} from "../api/objectives";

it("canonicalizes styles, singleton reductions and duplicate objectives", () => {
  const goals = canonicalObjectives([
    {
      kind: "defence_roll",
      styles: ["magic", "stab", "magic"],
      aggregation: "minimum",
    },
    { kind: "defence_roll", styles: ["stab", "magic"], aggregation: "minimum" },
    { kind: "defence_roll", styles: ["ranged"], aggregation: "mean" },
  ]);
  expect(goals).toHaveLength(2);
  expect(goals.map(objectiveId)).toContain("defence_roll:minimum:stab+magic");
  expect(goals.map(objectiveId)).toContain("defence_roll:minimum:ranged");
});
it("rejects empty and unknown defence groups", () => {
  expect(() =>
    canonicalObjectives([
      { kind: "defence_roll", styles: [], aggregation: "minimum" },
    ]),
  ).toThrow();
  expect(() => canonicalObjectives([{ kind: "unknown" }])).toThrow();
});
it("migrates each existing recipe without changing its meaning", () => {
  expect(legacyObjectives("stab_magic_ranged_defence_roll")).toEqual([
    {
      kind: "defence_roll",
      styles: ["stab", "ranged", "magic"],
      aggregation: "minimum",
    },
  ]);
  expect(legacyObjectives("balanced_defence_roll")[0]).toMatchObject({
    aggregation: "mean",
  });
  expect(legacyObjectives("default")).toEqual([]);
});
it("supports separate quick objectives and independent bonuses", () => {
  expect(
    quickObjectives(["stab", "magic"], ["prayer_bonus"], "separate"),
  ).toHaveLength(3);
  expect(
    quickObjectives(["stab", "magic"], ["accuracy"], "minimum"),
  ).toHaveLength(2);
});
it("validates measurements and rejects invalid objective descriptors", async () => {
  const { objectiveValues, objectiveLabel, quickSelection } =
    await import("../api/objectives");
  expect(() => canonicalObjectives(null)).toThrow();
  expect(() => canonicalObjectives([null])).toThrow();
  expect(() =>
    canonicalObjectives([
      { kind: "defence_roll", styles: ["poison"], aggregation: "mean" },
    ]),
  ).toThrow();
  expect(() =>
    canonicalObjectives([{ kind: "accuracy", styles: [] }]),
  ).toThrow();
  expect(() => objectiveValues(null, [])).toThrow();
  expect(() =>
    objectiveValues({ accuracy: NaN }, [{ kind: "accuracy" }]),
  ).toThrow();
  expect(objectiveValues({ accuracy: 0.5 }, [{ kind: "accuracy" }])).toEqual({
    accuracy: 0.5,
  });
  expect(objectiveLabel({ kind: "accuracy" })).toBe("Accuracy");
  expect(
    objectiveLabel({
      kind: "defence_roll",
      styles: ["stab", "magic"],
      aggregation: "mean",
    }),
  ).toContain("Average");
  expect(quickSelection([]).representable).toBe(true);
});
