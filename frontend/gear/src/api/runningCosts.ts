import { object, strings } from "./runtime";

export function validateRunningCost(value: unknown): void {
  if (value === undefined) return;
  const cost = object(value);
  if (
    !["known", "unavailable"].includes(String(cost.status)) ||
    !Array.isArray(cost.resources) ||
    !strings(cost.reasons)
  )
    throw new Error("Invalid running cost");
  const nonnegative = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value) && value >= 0;
  for (const field of ["gp_per_attack", "gp_per_hour", "gp_per_damage"]) {
    if (cost[field] !== null && !nonnegative(cost[field]))
      throw new Error("Invalid running cost measurement");
  }
  for (const value of cost.resources) {
    const r = object(value);
    if (
      !Number.isSafeInteger(r.item_id) ||
      Number(r.item_id) <= 0 ||
      typeof r.name !== "string" ||
      typeof r.price_layer !== "string" ||
      (r.supplied_by !== null && typeof r.supplied_by !== "string") ||
      (r.unit_price_gp !== null && !nonnegative(r.unit_price_gp))
    )
      throw new Error("Invalid running cost resource");
    for (const field of [
      "required_quantity",
      "consumed_quantity",
      "supplied_quantity",
    ])
      if (!nonnegative(r[field]))
        throw new Error("Invalid resource consumption");
  }
}
