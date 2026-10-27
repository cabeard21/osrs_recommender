import { slots, type Item, type OptimizationDTO } from "./contracts";

type Alternatives = NonNullable<OptimizationDTO["result"]["alternatives"]>;

/** Contextual rows are exact whole-loadout comparisons supplied by Python. */
export function parseAlternatives(
  value: unknown,
  items: Item[],
  excluded: number[],
): Alternatives {
  if (value === undefined) return {};
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid contextual alternatives");
  const parsed: Alternatives = {};
  for (const [slot, rows] of Object.entries(value)) {
    const uiSlot = slot === "ammunition" ? "ammo" : slot;
    if (
      slot === "ammo" ||
      !slots.includes(uiSlot as (typeof slots)[number]) ||
      !Array.isArray(rows) ||
      rows.length > 5
    )
      throw new Error("Invalid contextual alternative slot");
    const seen = new Set<number | null>();
    parsed[slot] = rows.map((row: unknown) => {
      if (!row || typeof row !== "object" || Array.isArray(row))
        throw new Error("Invalid contextual alternative");
      const { item_id, score, score_delta, purchase_cost_gp } = row as Record<
        string,
        unknown
      >;
      if (
        (item_id !== null &&
          (!Number.isSafeInteger(item_id) ||
            Number(item_id) <= 0 ||
            excluded.includes(Number(item_id)) ||
            !items.some((i) => i.id === item_id && i.slot === uiSlot))) ||
        seen.has(item_id as number | null) ||
        typeof score !== "number" ||
        !Number.isFinite(score) ||
        score < 0 ||
        typeof score_delta !== "number" ||
        !Number.isFinite(score_delta) ||
        !Number.isSafeInteger(purchase_cost_gp) ||
        Number(purchase_cost_gp) < 0
      )
        throw new Error("Invalid contextual alternative facts");
      seen.add(item_id as number | null);
      return {
        item_id: item_id as number | null,
        score,
        score_delta,
        purchase_cost_gp: purchase_cost_gp as number,
      };
    });
  }
  return parsed;
}
