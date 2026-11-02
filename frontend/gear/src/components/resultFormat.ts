import { emptyEquipment } from "../api/contracts";
import type { Draft, Equipment } from "../api/contracts";

const TICK_SECONDS = 0.6;

/** One game tick is 0.6s, so the raw float carries binary noise. */
export function formatInterval(seconds: number): string {
  const ticks = Math.round(seconds / TICK_SECONDS);
  return `${ticks} ${ticks === 1 ? "tick" : "ticks"} (${(ticks * TICK_SECONDS).toFixed(1)}s)`;
}

export const EQUIPMENT_ACCESS_LABELS: Record<Draft["mode"], string> = {
  owned: "Owned only",
  usable: "Owned + purchasable",
  future: "Hypothetical access",
};

/** The API names the ammo slot "ammunition"; the UI's slot list uses "ammo". */
export function equipmentFor(equipment: Record<string, number>): Equipment {
  return {
    ...emptyEquipment(),
    ...Object.fromEntries(
      Object.entries(equipment).map(([slot, id]) => [
        slot === "ammunition" ? "ammo" : slot,
        id,
      ]),
    ),
  };
}
