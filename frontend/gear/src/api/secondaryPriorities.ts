import { sameValue, object } from "./runtime";
import type { OptimizationReply, SecondaryPriority } from "./contracts";

export const secondaryPriorities = [
  ["default", "None — DPS only"],
  ["balanced_defence", "Balanced defence"],
  ["magic_ranged_defence", "Magic & ranged defence"],
  ["stab_defence", "Stab defence"],
  ["slash_defence", "Slash defence"],
  ["crush_defence", "Crush defence"],
  ["ranged_defence", "Ranged defence"],
  ["magic_defence", "Magic defence"],
  ["balanced_defence_roll", "Balanced defence roll"],
  ["magic_ranged_defence_roll", "Magic & ranged defence roll"],
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

export function defenceRollStyles(
  priority: SecondaryPriority,
): readonly ("stab" | "slash" | "crush" | "ranged" | "magic")[] {
  if (!priority.endsWith("_defence_roll")) return [];
  if (priority === "balanced_defence_roll")
    return ["stab", "slash", "crush", "ranged", "magic"];
  if (priority === "magic_ranged_defence_roll") return ["magic", "ranged"];
  return [
    priority.replace("_defence_roll", "") as
      "stab" | "slash" | "crush" | "ranged" | "magic",
  ];
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
    (a.scenario.request.secondary_priority ?? "default") ===
      (b.scenario.request.secondary_priority ?? "default") &&
    (a.scenario.request.max_dps_loss_pct ?? 10) ===
      (b.scenario.request.max_dps_loss_pct ?? 10) &&
    sameValue(a.live?.frontier_policy ?? null, b.live?.frontier_policy ?? null)
  );
}
