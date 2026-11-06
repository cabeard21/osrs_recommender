import type { Item } from "./contracts";
import { object } from "./runtime";

/** Purchase identities may differ from carried equipment only via its preparation. */
export function purchaseItemIds(
  required: readonly number[],
  preparations: unknown,
  items: readonly Item[],
): Set<number> {
  const allowed = new Set(
    required.filter((id) => {
      const preparation = items.find((item) => item.id === id)?.facts
        ?.preparation;
      return !preparation || preparation.market_item_id === id;
    }),
  );
  if (preparations === undefined) return allowed;
  if (!Array.isArray(preparations))
    throw new Error("Invalid purchase preparation");
  for (const value of preparations) {
    const row = object(value);
    const usable = row.usable_item_id;
    const market = row.market_item_id;
    const fact = items.find((item) => item.id === usable)?.facts;
    const reviewed = fact?.preparation;
    if (
      !Number.isSafeInteger(usable) ||
      !required.includes(Number(usable)) ||
      fact?.item_id !== usable ||
      !reviewed ||
      reviewed.usable_item_id !== usable ||
      reviewed.market_item_id !== market ||
      reviewed.source_item_id !== row.source_item_id ||
      (market !== null &&
        (!Number.isSafeInteger(market) || Number(market) <= 0))
    )
      throw new Error("Invalid purchase preparation");
    if (market !== null) allowed.add(Number(market));
  }
  return allowed;
}
