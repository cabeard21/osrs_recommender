import { sameValue } from "./runtime";
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
  ["prayer_bonus", "Prayer bonus"],
  ["melee_strength_bonus", "Melee strength bonus"],
  ["ranged_strength_bonus", "Ranged strength bonus"],
  ["magic_damage_bonus", "Magic damage bonus"],
  ["accuracy", "Accuracy"],
] as const;

export function validateSecondaryPriority(
  value: Record<string, unknown>,
  expected: SecondaryPriority,
  measured = false,
) {
  if ((value.secondary_priority ?? "default") !== expected)
    throw new Error("Tradeoff metric does not match the submitted priority");
  if (!measured) return;
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
