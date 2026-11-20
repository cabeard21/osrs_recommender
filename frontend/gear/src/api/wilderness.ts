import type {
  Draft,
  Role,
  Scenario,
  WildernessDeathSettings,
  WildernessRisk,
} from "./contracts";
import { disciplinesOf } from "./combatOptions";
import { object, requireFields } from "./runtime";

export const defaultWilderness: WildernessDeathSettings = {
  depth: "level_21_plus",
  skulled: false,
  protect_item: false,
};
export const DEFAULT_WILDERNESS_SPELL_CASTS = 100;
export const MAX_WILDERNESS_SPELL_CASTS = 10_000;

export function wildernessMayUseMagic(roles: readonly Role[]): boolean {
  return roles.some(
    (role) => !role.utility && disciplinesOf(role).includes("magic"),
  );
}

export function isWildernessDeathSettings(
  value: unknown,
): value is WildernessDeathSettings {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = object(value);
  return (
    (row.depth === "level_1_20" || row.depth === "level_21_plus") &&
    typeof row.skulled === "boolean" &&
    typeof row.protect_item === "boolean" &&
    Object.keys(row).length === 3
  );
}

export function fixedTrip(draft: Pick<Draft, "objectives">): boolean {
  return !!draft.objectives?.some(
    (objective) => objective.kind === "wilderness_loss_gp",
  );
}
export function limitTripLoss(draft: Draft): boolean {
  return (
    draft.wildernessLimitLoss ??
    (!!draft.wildernessRiskBudget && draft.wildernessRiskBudget !== "0")
  );
}

export function wildernessRiskCap(
  request: Pick<Scenario["request"], "wilderness" | "budget_gp" | "objectives">,
): number | null | undefined {
  if (
    request.wilderness &&
    (request.wilderness.attacks_per_setup != null || fixedTrip(request))
  )
    return request.wilderness.max_loss_gp ?? null;
  return request.wilderness
    ? (request.wilderness.max_loss_gp ?? request.budget_gp)
    : undefined;
}

/** Historical API responses omitted the separate risk cap or spell casts. */
export function normalizedWilderness(
  value: unknown,
  objectives?: unknown,
): Record<string, unknown> | null {
  if (value == null) return null;
  const policy = object(value);
  return {
    ...policy,
    ...(Array.isArray(objectives) &&
    objectives.some((o) => o?.kind === "wilderness_loss_gp")
      ? {
          attacks_per_setup:
            policy.attacks_per_setup ??
            policy.spell_casts ??
            DEFAULT_WILDERNESS_SPELL_CASTS,
        }
      : {}),
    max_loss_gp: policy.max_loss_gp ?? null,
    spell_casts: policy.spell_casts ?? null,
  };
}

const positiveInteger = (value: unknown) =>
  Number.isSafeInteger(value) && Number(value) > 0;
const lossEstimate = (value: unknown) =>
  value === null || (Number.isSafeInteger(value) && Number(value) >= 0);
const outcomes = new Set([
  "kept",
  "gravestone",
  "dropped",
  "broken",
  "mangled",
  "destroyed",
  "converted",
  "unknown",
]);

export function riskWithinBudget(
  value: unknown,
  maxRisk: number | null,
): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    (maxRisk === null || value <= maxRisk)
  );
}

export function parseWildernessRisk(
  value: unknown,
  request: Scenario["request"],
  feasible = true,
  objectiveValues?: unknown,
): WildernessRisk | undefined {
  const cap = wildernessRiskCap(request);
  if (value == null) {
    if (cap !== undefined && feasible)
      throw new Error("Wilderness risk is missing from a feasible result");
    return undefined;
  }
  const row = requireFields(value, { rules_revision: "string" });
  if (
    cap === undefined ||
    !row.rules_revision ||
    !lossEstimate(row.loss_gp) ||
    !lossEstimate(row.without_protect_item_gp) ||
    (feasible && !riskWithinBudget(row.loss_gp, cap)) ||
    !Array.isArray(row.items) ||
    !Array.isArray(row.quantities)
  )
    throw new Error("Invalid Wilderness risk estimate");
  if (
    feasible &&
    request.objectives?.some((o) => o.kind === "wilderness_loss_gp") &&
    object(objectiveValues ?? {}).wilderness_loss_gp !== row.loss_gp
  )
    throw new Error("Wilderness objective does not match the estimated loss");
  for (const value of row.items) {
    const item = requireFields(value, { outcome: "string" });
    if (
      !positiveInteger(item.item_id) ||
      !positiveInteger(item.quantity) ||
      !lossEstimate(item.loss_gp) ||
      !outcomes.has(String(item.outcome))
    )
      throw new Error("Invalid Wilderness item loss");
  }
  for (const value of row.quantities) {
    const resource = object(value);
    if (
      !positiveInteger(resource.item_id) ||
      !positiveInteger(resource.resource_id) ||
      !positiveInteger(resource.quantity) ||
      (resource.kind !== "ammo" &&
        resource.kind !== "charge" &&
        resource.kind !== "rune") ||
      (resource.kind === "rune" && resource.item_id !== resource.resource_id)
    )
      throw new Error("Invalid Wilderness resource quantity");
  }
  return value as WildernessRisk;
}
