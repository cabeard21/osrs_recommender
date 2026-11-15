import { slots, type Equipment, type Slot } from "./contracts";

// Official-client format: Wiki converter revision 15263469.
// Coordinates mirror EquipmentGrid in the first three bank columns.
const positions: Record<Slot, readonly [number, number]> = {
  head: [1, 0],
  cape: [0, 1],
  neck: [1, 1],
  ammo: [2, 1],
  weapon: [0, 2],
  body: [1, 2],
  shield: [2, 2],
  legs: [1, 3],
  hands: [0, 4],
  feet: [1, 4],
  ring: [2, 4],
};

export function mobileBankTag(equipment: Equipment): string | null {
  if (
    slots.some((slot) => {
      const id = equipment[slot];
      return id !== null && (!Number.isSafeInteger(id) || id <= 0);
    })
  )
    return null;
  const entries = slots.flatMap((slot) => {
    const id = equipment[slot];
    return id === null ? [] : [[id, ...positions[slot]]];
  });
  return entries.length
    ? [1, entries.length, ...entries.flat()].join(",")
    : null;
}
