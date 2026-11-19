import type { SecondaryPriority } from "./contracts";
import { defenceRollStyles } from "./secondaryPriorities";
export const defenceStyles = [
  "stab",
  "slash",
  "crush",
  "ranged",
  "magic",
] as const;
export type DefenceStyle = (typeof defenceStyles)[number];
export const atomicObjectives = [
  ["prayer_bonus", "Prayer bonus"],
  ["melee_strength_bonus", "Melee strength"],
  ["ranged_strength_bonus", "Ranged strength"],
  ["magic_damage_bonus", "Magic damage"],
  ["gp_per_damage", "Running cost (GP per damage)"],
  ["wilderness_loss_gp", "Wilderness loss if PK’d (GP)"],
  ["accuracy", "Accuracy"],
] as const;
export type AtomicObjective = (typeof atomicObjectives)[number][0];
export type Objective =
  | {
      kind: "defence_roll";
      styles: DefenceStyle[];
      aggregation: "minimum" | "mean";
    }
  | { kind: AtomicObjective };
export interface ObjectiveDefinition {
  id: string;
  kind: Objective["kind"];
  label: string;
  unit: "roll" | "bonus" | "probability" | "percent" | "GP/damage" | "GP";
  direction?: "maximize" | "minimize";
  styles?: DefenceStyle[];
  aggregation?: "minimum" | "mean";
}
export function objectiveId(goal: Objective): string {
  return goal.kind === "defence_roll"
    ? "defence_roll:" + goal.aggregation + ":" + goal.styles.join("+")
    : goal.kind;
}
export function canonicalObjectives(value: unknown): Objective[] {
  if (!Array.isArray(value))
    throw new Error("Choose up to 64 distinct objectives.");
  const goals = value.map((entry: unknown): Objective => {
    if (!entry || typeof entry !== "object")
      throw new Error("Invalid objective.");
    const row = entry as Record<string, unknown>;
    if (row.kind === "defence_roll") {
      if (
        !Array.isArray(row.styles) ||
        !row.styles.length ||
        row.styles.some((s) => !defenceStyles.includes(s as DefenceStyle)) ||
        !["minimum", "mean"].includes(String(row.aggregation)) ||
        Object.keys(row).some(
          (k) => !["kind", "styles", "aggregation"].includes(k),
        )
      )
        throw new Error("Choose at least one valid defence roll per group.");
      const styles = defenceStyles.filter((s) =>
        (row.styles as unknown[]).includes(s),
      );
      return {
        kind: "defence_roll",
        styles,
        aggregation:
          styles.length === 1
            ? "minimum"
            : (row.aggregation as "minimum" | "mean"),
      };
    }
    if (
      !atomicObjectives.some(([id]) => id === row.kind) ||
      Object.keys(row).length !== 1
    )
      throw new Error("Choose a valid objective.");
    return { kind: row.kind as AtomicObjective };
  });
  return [
    ...new Map(goals.map((goal) => [objectiveId(goal), goal])).values(),
  ].sort((a, b) =>
    objectiveId(a) < objectiveId(b)
      ? -1
      : objectiveId(a) > objectiveId(b)
        ? 1
        : 0,
  );
}
export function legacyObjectives(
  priority: SecondaryPriority = "default",
): Objective[] {
  if (priority === "default") return [];
  const migrated = priority.endsWith("_defence")
    ? ((priority + "_roll") as SecondaryPriority)
    : priority;
  const styles = defenceRollStyles(migrated);
  if (styles.length)
    return canonicalObjectives([
      {
        kind: "defence_roll",
        styles,
        aggregation: migrated === "balanced_defence_roll" ? "mean" : "minimum",
      },
    ]);
  return canonicalObjectives([{ kind: migrated }]);
}
export function objectiveLabel(goal: Objective): string {
  return goal.kind === "defence_roll"
    ? (goal.styles.length === 1
        ? ""
        : goal.aggregation === "minimum"
          ? "Weakest: "
          : "Average: ") +
        goal.styles.join(" / ") +
        " defence"
    : atomicObjectives.find(([id]) => id === goal.kind)![1];
}
export function quickObjectives(
  styles: readonly DefenceStyle[],
  others: readonly AtomicObjective[],
  mode: "minimum" | "mean" | "separate",
): Objective[] {
  const rolls: Objective[] =
    mode === "separate"
      ? styles.map((style) => ({
          kind: "defence_roll",
          styles: [style],
          aggregation: "minimum",
        }))
      : styles.length
        ? [{ kind: "defence_roll", styles: [...styles], aggregation: mode }]
        : [];
  return canonicalObjectives([...rolls, ...others.map((kind) => ({ kind }))]);
}
export function quickSelection(goals: Objective[]) {
  const rolls = goals.filter(
    (g): g is Extract<Objective, { kind: "defence_roll" }> =>
      g.kind === "defence_roll",
  );
  return {
    representable:
      rolls.length <= 1 || rolls.every((g) => g.styles.length === 1),
    styles: defenceStyles.filter((s) =>
      rolls.some((g) => g.styles.includes(s)),
    ),
    others: goals
      .filter((g): g is { kind: AtomicObjective } => g.kind !== "defence_roll")
      .map((g) => g.kind),
    mode: (rolls.length > 1
      ? "separate"
      : (rolls[0]?.aggregation ?? "minimum")) as
      "minimum" | "mean" | "separate",
  };
}
export function objectiveValues(
  value: unknown,
  expected: Objective[],
  allowUnavailableCost = false,
): Record<string, number | null> {
  if (value === undefined && expected.length === 0) return {};
  if (
    value === undefined &&
    allowUnavailableCost &&
    expected.every((goal) => goal.kind === "gp_per_damage")
  )
    return { gp_per_damage: null };
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Missing objective measurements.");
  const measurements = value as Record<string, unknown>,
    ids = expected.map(objectiveId);
  if (
    Object.keys(measurements).some((key) => !ids.includes(key)) ||
    ids.some((id) => {
      const v = measurements[id];
      if (id === "gp_per_damage" && allowUnavailableCost && v == null)
        return false;
      return (
        typeof v !== "number" ||
        !Number.isFinite(v) ||
        (id === "gp_per_damage" && v < 0) ||
        (id === "wilderness_loss_gp" && (!Number.isSafeInteger(v) || v < 0))
      );
    })
  )
    throw new Error(
      "Objective measurements do not match the submitted objectives.",
    );
  return Object.fromEntries(
    ids.map((id) => [id, (measurements[id] as number | null) ?? null]),
  );
}
