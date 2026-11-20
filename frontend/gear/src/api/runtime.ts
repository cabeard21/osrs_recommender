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
  if (
    value.wilderness_weapon_passive != null &&
    typeof value.wilderness_weapon_passive !== "boolean"
  )
    throw new Error("Invalid Wilderness weapon passive");
  if (
    value.direct_dps != null &&
    (!Number.isFinite(value.direct_dps) || value.direct_dps < 0)
  )
    throw new Error("Invalid direct DPS metadata");
  if (value.status_damage != null) {
    const status = value.status_damage;
    if (
      !["venom", "poison", "unknown"].includes(status.kind) ||
      !Number.isSafeInteger(status.duration_seconds) ||
      status.duration_seconds < 1 ||
      status.duration_seconds > 3600 ||
      ![status.expected_damage, status.dps, status.application_chance].every(
        (n) => typeof n === "number" && Number.isFinite(n) && n >= 0,
      ) ||
      status.application_chance > 1 ||
      !strings(status.limitations) ||
      value.direct_dps == null ||
      Math.abs(value.direct_dps + status.dps - value.dps!) > 1e-8 ||
      Math.abs(status.expected_damage / status.duration_seconds - status.dps) >
        1e-8
    )
      throw new Error("Invalid status damage metadata");
  }
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
  if (value.dragonbane_bonus != null) {
    const effect = object(value.dragonbane_bonus);
    const crossbow = [21012, 25916, 25918].includes(Number(effect.item_id));
    const expected =
      effect.item_id === 22978
        ? [20, 20]
        : effect.item_id === 30070
          ? [75, 40]
          : crossbow
            ? [30, 25]
            : null;
    if (
      !Number.isSafeInteger(effect.item_id) ||
      expected === null ||
      effect.accuracy_percent !== expected[0] ||
      effect.damage_percent !== expected[1] ||
      typeof effect.slayer_damage_additive !== "boolean" ||
      (effect.slayer_damage_additive && !crossbow)
    )
      throw new Error("Invalid dragonbane effect metadata");
  }
  if (value.demonbane_bonus != null) {
    const effect = object(value.demonbane_bonus);
    if (
      !(
        effect.item_id === null ||
        (Number.isSafeInteger(effect.item_id) && Number(effect.item_id) > 0)
      ) ||
      !(
        effect.spell === null ||
        ["inferior_demonbane", "superior_demonbane", "dark_demonbane"].includes(
          String(effect.spell),
        )
      ) ||
      ![
        effect.accuracy_percent,
        effect.damage_percent,
        effect.vulnerability_percent,
      ].every(
        (n) => Number.isSafeInteger(n) && Number(n) >= 0 && Number(n) <= 1000,
      ) ||
      typeof effect.mark_of_darkness !== "boolean"
    )
      throw new Error("Invalid demonbane effect metadata");
  }
  if (value.leafy_bonus != null) {
    const effect = value.leafy_bonus;
    if (
      effect.item_id !== 20727 ||
      effect.damage_numerator !== 47 ||
      effect.denominator !== 40
    )
      throw new Error("Invalid leafy effect metadata");
  }
  if (value.size_damage_bonus != null) {
    const effect = object(value.size_damage_bonus);
    if (
      !Number.isSafeInteger(effect.item_id) ||
      Number(effect.item_id) < 1 ||
      !Number.isSafeInteger(effect.target_size) ||
      Number(effect.target_size) < 0 ||
      Number(effect.target_size) > 64 ||
      !Number.isSafeInteger(effect.max_hit_bonus) ||
      Number(effect.max_hit_bonus) < 0 ||
      Number(effect.max_hit_bonus) > 6400
    )
      throw new Error("Invalid target size effect metadata");
  }
  if (value.seeking_arrow_bonus != null) {
    const effect = value.seeking_arrow_bonus;
    if (effect.item_id !== 33601 || effect.minimum_hit !== 3)
      throw new Error("Invalid Seeking arrow effect metadata");
  }
  if (value.salve_bonus != null) {
    const effect = object(value.salve_bonus);
    const { item_id, accuracy_percent, damage_percent, suppresses_slayer } =
      effect;
    if (
      !Number.isSafeInteger(item_id) ||
      Number(item_id) <= 0 ||
      ![accuracy_percent, damage_percent].every(
        (n) => typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 20,
      ) ||
      (accuracy_percent === 0 && damage_percent === 0) ||
      typeof suppresses_slayer !== "boolean"
    )
      throw new Error("Invalid Salve amulet effect metadata");
  }
  if (value.slayer_effects !== undefined) {
    if (
      !Array.isArray(value.slayer_effects) ||
      value.slayer_effects.some(
        (effect) =>
          !effect ||
          !Number.isSafeInteger(effect.item_id) ||
          effect.item_id <= 0 ||
          !["mask", "magic_dart"].includes(effect.kind) ||
          ![
            effect.accuracy_numerator,
            effect.damage_numerator,
            effect.denominator,
          ].every((n) => Number.isSafeInteger(n) && n > 0) ||
          (effect.base_max_hit !== null &&
            (!Number.isSafeInteger(effect.base_max_hit) ||
              effect.base_max_hit < 0)),
      )
    )
      throw new Error("Invalid Slayer effect metadata");
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
