import type { Scenario } from "./contracts";
import { object } from "./runtime";

export interface CarriedWeight {
  heaviest_kg: number;
  roles: Record<
    string,
    { worn_kg: number; backpack_kg: number; total_kg: number }
  >;
}

export function formatKg(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  return value.toLocaleString("en-US", { maximumFractionDigits: 3 }) + " kg";
}

export function validateCarriedWeight(
  value: unknown,
  roleIds: string[],
  objective: unknown,
): asserts value is CarriedWeight {
  const report = object(value);
  const roles = object(report.roles);
  if (!roleIds.length || Object.keys(roles).length !== roleIds.length)
    throw new Error("Invalid carried weight role IDs");
  const totals = roleIds.map((id) => {
    const { worn_kg, backpack_kg, total_kg } = object(roles[id]);
    if (
      typeof worn_kg !== "number" ||
      !Number.isFinite(worn_kg) ||
      typeof backpack_kg !== "number" ||
      !Number.isFinite(backpack_kg) ||
      typeof total_kg !== "number" ||
      !Number.isFinite(total_kg) ||
      Math.abs(worn_kg + backpack_kg - total_kg) > 1e-8
    )
      throw new Error("Invalid carried weight role total");
    return total_kg;
  });
  if (
    report.heaviest_kg !== objective ||
    report.heaviest_kg !== Math.max(...totals)
  )
    throw new Error("Invalid heaviest carried weight");
}

export function validateSolutionWeight(
  value: unknown,
  request: Scenario["request"],
) {
  if (!request.objectives?.some((o) => o.kind === "carried_weight_kg")) return;
  const report = object(value);
  validateCarriedWeight(
    report.carried_weight,
    request.roles.map((r) => r.id),
    object(report.objective_values).carried_weight_kg,
  );
}
