import { describe, expect, it } from "vitest";
import {
  equipmentChanges,
  example,
  formatMetric,
  leaders,
  METRICS,
  metricBounds,
  metricDelta,
  metricLeader,
  metricValue,
  normalizeMetric,
  project3d,
  type LabPoint,
} from "./model";

const point = (
  id: string,
  dps: number,
  defence: number,
  prayer: number,
): LabPoint => ({
  id,
  label: id,
  dps,
  defence,
  prayer,
  costGp: 0,
  equipment: [],
  potions: [],
  attackType: "stab",
  stance: "accurate",
});

describe("saved tradeoff example", () => {
  it("reads dynamic values and formats their declared units", () => {
    const dynamic = {
      ...point("dynamic", 2, 0, 0),
      values: { accuracy: 0.825, magic: 12 },
    };
    expect(metricValue(dynamic, "accuracy")).toBe(0.825);
    expect(
      formatMetric("accuracy", 0.825, {
        key: "accuracy",
        label: "Accuracy",
        shortLabel: "Accuracy",
        unit: "probability",
      }),
    ).toBe("82.50%");
    expect(
      formatMetric("magic", 12, {
        key: "magic",
        label: "Magic damage",
        shortLabel: "Magic damage",
        unit: "percent",
      }),
    ).toBe("12.00%");
    expect(metricBounds([dynamic], "accuracy")).toEqual([0.825, 0.825]);
    expect(
      leaders(
        [dynamic],
        [{ key: "accuracy", label: "Accuracy", shortLabel: "Accuracy" }],
      ),
    ).toEqual([dynamic]);
  });
  it("uses the one exported global cap and discloses its sample", () => {
    expect(example.target).toBe("Animated Black Armour");
    expect(example.evaluatedAt).toBe("2026-11-16T16:48:56.187026Z");
    expect(example.budgetGp).toBe(10_000_000);
    expect(example.totalCount).toBe(185);
    expect(example.sampled).toBe(true);
    expect(example.scope).toBe("Global frontier · maximum 8 swaps");
    expect(
      example.points.filter((p) => p.id !== "export-selected"),
    ).toHaveLength(128);
    expect(new Set(example.points.map((p) => p.id)).size).toBe(
      example.points.length,
    );
  });

  it("retains the export selection's exact scores and physical equipment", () => {
    const selected = example.points.find((p) => p.id === example.selectedId)!;
    expect(selected).toMatchObject({
      label: "Export selection",
      dps: 3.8839284511965873,
      defence: 17390,
      prayer: 8,
      costGp: 787500,
      potions: ["Combat potion"],
      attackType: "crush",
      stance: "accurate",
    });
    expect(selected.equipment.find((e) => e.slot === "legs")?.itemId).toBe(
      21304,
    );
    for (const candidate of example.points) {
      expect(
        [
          candidate.dps,
          candidate.defence,
          candidate.prayer,
          candidate.costGp,
        ].every(Number.isFinite),
      ).toBe(true);
      expect(
        candidate.equipment.every(
          (e) => e.name.length > 0 && Number.isInteger(e.itemId),
        ),
      ).toBe(true);
    }
  });
});

describe("tradeoff display helpers", () => {
  it("preserves fractional mean rolls and weighted bonuses and their signed deltas", () => {
    const roll = {
      key: "mean_roll",
      label: "Mean defense roll",
      shortLabel: "Mean defense roll",
      unit: "roll",
    };
    const bonus = {
      key: "weighted_prayer",
      label: "Weighted prayer bonus",
      shortLabel: "Weighted prayer bonus",
      unit: "bonus",
    };
    expect(formatMetric(roll.key, 17390.5, roll)).toBe("17,390.5");
    expect(formatMetric(bonus.key, 20.25, bonus)).toBe("20.25");
    expect(formatMetric("custom", 1.125)).toBe("1.125");
    expect(metricDelta(roll.key, 17390.5, 17390.25, roll)).toBe("+0.25");
    expect(metricDelta(roll.key, 17390.25, 17390.5, roll)).toBe("-0.25");
    expect(metricDelta(bonus.key, 20.25, 20, bonus)).toBe("+0.25");
    expect(metricDelta(bonus.key, 20, 20.25, bonus)).toBe("-0.25");
  });
  it("defines three independent axes with explicit units", () => {
    expect(METRICS.map((m) => m.key)).toEqual(["dps", "defence", "prayer"]);
    expect(formatMetric("dps", 3.883928)).toBe("3.884");
    expect(formatMetric("defence", 17390)).toBe("17,390");
    expect(formatMetric("prayer", 8)).toBe("8");
  });

  it("normalizes each axis independently without dropping constant axes", () => {
    expect(
      metricBounds([point("a", 1, 10, 8), point("b", 4, 100, 8)], "prayer"),
    ).toEqual([8, 8]);
    expect(metricBounds([], "dps")).toEqual([0, 1]);
    expect(normalizeMetric(8, [8, 8])).toBe(0.5);
    expect(normalizeMetric(25, [0, 100])).toBe(0.25);
    expect(normalizeMetric(-5, [0, 100])).toBe(0);
    expect(normalizeMetric(150, [0, 100])).toBe(1);
  });

  it("reports signed differences in actual units", () => {
    expect(metricDelta("dps", 3.5, 4)).toBe("-0.500");
    expect(metricDelta("defence", 20000, 17390)).toBe("+2,610");
    expect(metricDelta("prayer", 8, 8)).toBe("0");
  });

  it("chooses unique objective leaders deterministically without reordering input", () => {
    const points = [
      point("z", 4, 10, 8),
      point("a", 4, 100, 8),
      point("b", 1, 20, 12),
    ];
    const before = JSON.stringify(points);
    expect(leaders(points).map((p) => p.id)).toEqual(["a", "b"]);
    expect(leaders([])).toEqual([]);
    expect(JSON.stringify(points)).toBe(before);
  });

  it("uses the same tied endpoint regardless of input order", () => {
    const tied = [point("z", 4, 10, 8), point("a", 4, 100, 8)];
    expect(metricLeader(tied, "dps")?.id).toBe("a");
    expect(metricLeader([...tied].reverse(), "dps")?.id).toBe("a");
    expect(metricLeader(tied, "defence")?.id).toBe("a");
    expect(metricLeader([], "prayer")).toBeUndefined();
  });

  it("compares item IDs and includes added and removed slots", () => {
    const baseline = {
      ...point("a", 1, 1, 1),
      equipment: [
        { slot: "cape", itemId: 6568, name: "Obsidian cape" },
        { slot: "shield", itemId: 1, name: "Shield" },
      ],
    };
    const next = {
      ...point("b", 1, 1, 1),
      equipment: [
        { slot: "cape", itemId: 20050, name: "Obsidian cape (r)" },
        { slot: "body", itemId: 2, name: "Body" },
      ],
    };
    expect(equipmentChanges(next, baseline)).toEqual([
      { slot: "body", from: "Empty", to: "Body" },
      { slot: "cape", from: "Obsidian cape", to: "Obsidian cape (r)" },
      { slot: "shield", from: "Shield", to: "Empty" },
    ]);
    expect(equipmentChanges(baseline, baseline)).toEqual([]);
  });

  it("rotates all three coordinates without mutating the data", () => {
    const input = { x: 1, y: 2, z: 3 };
    expect(project3d(input, 0, 0)).toEqual({ x: 1, y: 2, depth: 3 });
    const yaw = project3d(input, 90, 0);
    expect(yaw.x).toBeCloseTo(3);
    expect(yaw.depth).toBeCloseTo(-1);
    const pitch = project3d(input, 0, 90);
    expect(pitch.y).toBeCloseTo(-3);
    expect(pitch.depth).toBeCloseTo(2);
    expect(input).toEqual({ x: 1, y: 2, z: 3 });
  });
});
