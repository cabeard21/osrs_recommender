import { emptyEquipment, slots } from "./contracts";
import type { CombatPerformance, Equipment, Metrics, Slot } from "./contracts";
export const uiSlot = (slot: unknown) =>
  slot === "ammunition" ? "ammo" : slot;
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid Gear API response");
  return value as Record<string, unknown>;
}
export function requireFields(value: unknown, fields: Record<string, string>) {
  const row = object(value);
  for (const [key, type] of Object.entries(fields)) {
    if (typeof row[key] !== type)
      throw new Error(`Invalid Gear API field: ${key}`);
  }
  return row;
}
export function strings(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((entry) => typeof entry === "string")
  );
}
export function performanceMetrics(value: CombatPerformance): Metrics {
  if (
    value.supported !== true ||
    [value.dps, value.max_hit, value.accuracy, value.attack_interval].some(
      (n) => typeof n !== "number" || !Number.isFinite(n),
    )
  )
    throw new Error("Unsupported or invalid combat performance");
  if (
    value.dps! < 0 ||
    !Number.isSafeInteger(value.max_hit) ||
    value.max_hit! < 0 ||
    value.accuracy! < 0 ||
    value.accuracy! > 1 ||
    value.attack_interval! <= 0 ||
    !strings(value.limitations) ||
    Object.values(object(value.bonuses)).some(
      (bonus) => typeof bonus !== "number" || !Number.isFinite(bonus),
    )
  )
    throw new Error("Invalid combat performance metadata");
  if (value.tome_bonus != null) {
    const t = value.tome_bonus;
    if (
      !Number.isSafeInteger(t.item_id) ||
      t.item_id <= 0 ||
      !["fire", "water", "earth"].includes(t.element) ||
      t.damage_percent !== 10 ||
      ![0, 20].includes(t.accuracy_percent) ||
      !Number.isSafeInteger(t.minimum_hit) ||
      t.minimum_hit < 0 ||
      t.minimum_hit > value.max_hit! ||
      !(t.fire_pages === null || ["burnt", "searing"].includes(t.fire_pages))
    )
      throw new Error("Invalid tome effect metadata");
  }
  return {
    dps: value.dps!,
    maxHit: value.max_hit!,
    accuracy: value.accuracy!,
    seconds: value.attack_interval!,
  };
}
export function equipmentMap(value: unknown): Equipment {
  const equipment = emptyEquipment();
  for (const [key, id] of Object.entries(object(value))) {
    const slot = uiSlot(key) as Slot;
    if (!slots.includes(slot) || !Number.isSafeInteger(id) || Number(id) <= 0)
      throw new Error("Invalid result equipment assignment");
    equipment[slot] = id as number;
  }
  return equipment;
}
export function sameValue(expected: unknown, actual: unknown): boolean {
  if (Array.isArray(expected))
    return (
      Array.isArray(actual) &&
      expected.length === actual.length &&
      expected.every((v, i) => sameValue(v, actual[i]))
    );
  if (expected && typeof expected === "object") {
    const left = object(expected),
      right = object(actual);
    return (
      Object.keys(left).length === Object.keys(right).length &&
      Object.entries(left).every(([k, v]) => sameValue(v, right[k]))
    );
  }
  return expected === actual;
}
