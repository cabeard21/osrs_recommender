import { sameValue, object } from "./runtime";
import type { OptimizationReply, SecondaryPriority } from "./contracts";

export const secondaryPriorities = [
  ["default", "None — DPS only"],
  ["balanced_defence_roll", "Balanced defence roll"],
  ["melee_defence_roll", "Melee defence roll"],
  ["melee_magic_defence_roll", "Melee & magic defence roll"],
  ["melee_ranged_defence_roll", "Melee & ranged defence roll"],
  ["magic_ranged_defence_roll", "Magic & ranged defence roll"],
  ["stab_magic_defence_roll", "Stab & magic defence roll"],
  ["stab_ranged_defence_roll", "Stab & ranged defence roll"],
  ["stab_magic_ranged_defence_roll", "Stab & magic & ranged defence roll"],
  ["slash_magic_defence_roll", "Slash & magic defence roll"],
  ["slash_ranged_defence_roll", "Slash & ranged defence roll"],
  ["slash_magic_ranged_defence_roll", "Slash & magic & ranged defence roll"],
  ["crush_magic_defence_roll", "Crush & magic defence roll"],
  ["crush_ranged_defence_roll", "Crush & ranged defence roll"],
  ["crush_magic_ranged_defence_roll", "Crush & magic & ranged defence roll"],
  ["stab_defence_roll", "Stab defence roll"],
  ["slash_defence_roll", "Slash defence roll"],
  ["crush_defence_roll", "Crush defence roll"],
  ["ranged_defence_roll", "Ranged defence roll"],
  ["magic_defence_roll", "Magic defence roll"],
  ["prayer_bonus", "Prayer bonus"],
  ["melee_strength_bonus", "Melee strength bonus"],
  ["ranged_strength_bonus", "Ranged strength bonus"],
  ["magic_damage_bonus", "Magic damage bonus"],
  ["accuracy", "Accuracy"],
] as const;

// Historical results keep their original labels and measurements.
const legacyDefencePriorities = [
  ["balanced_defence", "Balanced defence"],
  ["magic_ranged_defence", "Magic & ranged defence"],
  ["stab_defence", "Stab defence"],
  ["slash_defence", "Slash defence"],
  ["crush_defence", "Crush defence"],
  ["ranged_defence", "Ranged defence"],
  ["magic_defence", "Magic defence"],
] as const;
export function secondaryPriorityLabel(priority: SecondaryPriority): string {
  return (
    [...secondaryPriorities, ...legacyDefencePriorities].find(
      ([id]) => id === priority,
    )?.[1] ?? priority
  );
}
export function migrateSecondaryPriority(
  priority: SecondaryPriority,
): SecondaryPriority {
  return legacyDefencePriorities.some(([id]) => id === priority)
    ? (`${priority}_roll` as SecondaryPriority)
    : priority;
}
export function defenceRollExplanation(priority: SecondaryPriority): string {
  if (priority === "balanced_defence_roll")
    return "Balanced defence roll is the mean of all five player defence rolls. ";
  if (priority === "magic_ranged_defence_roll")
    return "Magic & ranged defence roll is the lower of those two player defence rolls. ";
  if (defenceRollStyles(priority).length > 1)
    return `${secondaryPriorityLabel(priority)} is the lowest of the ${defenceRollStyles(priority).join(", ")} player defence rolls. `;
  return "";
}

export function defenceRollStyles(
  priority: SecondaryPriority,
): readonly ("stab" | "slash" | "crush" | "ranged" | "magic")[] {
  if (!priority.endsWith("_defence_roll")) return [];
  if (priority === "balanced_defence_roll")
    return ["stab", "slash", "crush", "ranged", "magic"];
  if (priority === "magic_ranged_defence_roll") return ["magic", "ranged"];
  if (priority === "melee_defence_roll") return ["stab", "slash", "crush"];
  if (priority === "melee_magic_defence_roll")
    return ["stab", "slash", "crush", "magic"];
  if (priority === "melee_ranged_defence_roll")
    return ["stab", "slash", "crush", "ranged"];
  return priority.replace("_defence_roll", "").split("_") as (
    "stab" | "slash" | "crush" | "ranged" | "magic"
  )[];
}

export function validateSecondaryPriority(
  value: Record<string, unknown>,
  expected: SecondaryPriority,
  measured = false,
) {
  if ((value.secondary_priority ?? "default") !== expected)
    throw new Error("Tradeoff metric does not match the submitted priority");
  if (!measured) return;
  const styles = defenceRollStyles(expected);
  if (styles.length) {
    const loadouts = object(value.loadouts);
    if (!Object.keys(loadouts).length)
      throw new Error("Missing player defence rolls");
    for (const loadout of Object.values(loadouts)) {
      const performance = object(object(loadout).performance);
      // Utility roles deliberately omit damage and defensive scoring.
      if (
        performance.supported === true &&
        !("dps" in performance) &&
        !("bonuses" in performance)
      )
        continue;
      const rolls = object(performance.player_defence_rolls);
      if (
        styles.some(
          (style) =>
            !Number.isSafeInteger(rolls[style]) || Number(rolls[style]) < 0,
        )
      )
        throw new Error("Invalid player defence roll components");
    }
  }
  if (expected === "default") {
    if (value.secondary_value !== undefined && value.secondary_value !== null)
      throw new Error(
        "Default tradeoff metric must not invent a measured value",
      );
  } else if (
    typeof value.secondary_value !== "number" ||
    !Number.isFinite(value.secondary_value)
  )
    throw new Error("Invalid tradeoff metric measured value");
}

export function matchesSecondaryPriority(
  a: OptimizationReply,
  b: OptimizationReply,
) {
  return (
    sameValue(
      a.scenario.request.objectives ?? null,
      b.scenario.request.objectives ?? null,
    ) &&
    (a.scenario.request.secondary_priority ?? "default") ===
      (b.scenario.request.secondary_priority ?? "default") &&
    (a.scenario.request.max_dps_loss_pct ?? 10) ===
      (b.scenario.request.max_dps_loss_pct ?? 10) &&
    sameValue(a.live?.frontier_policy ?? null, b.live?.frontier_policy ?? null)
  );
}
