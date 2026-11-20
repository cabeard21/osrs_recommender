import type { CombatTarget } from "../api/contracts";

export function integer(value: string, name: string, min: number, max: number) {
  const n = Number(value);
  if (!value.trim() || !Number.isSafeInteger(n) || n < min || n > max)
    throw new Error(`${name} must be a whole number from ${min} to ${max}.`);
  return n;
}

export function validationMessage(check: () => unknown): string | undefined {
  try {
    check();
    return undefined;
  } catch (error) {
    return (error as Error).message;
  }
}

export function fightDuration(value = "60") {
  return integer(value, "Fight duration", 1, 3600);
}

export function activeTimeWeight(value: string) {
  const weight = Number(value);
  if (
    !value.trim() ||
    !Number.isFinite(weight) ||
    weight < 0 ||
    weight > 1000000
  )
    throw new Error("Active-time weight must be a number from 0 to 1,000,000.");
  return weight;
}

export function maxEquipmentActions(value: string) {
  return integer(value, "Equipment actions", 0, 12);
}

export function reservedSupplySlots(value: string) {
  return integer(value, "Supply slots", 0, 28);
}

type TargetInputs = Record<string, string>;

function readTargetHitpoints(target: CombatTarget, inputs: TargetInputs) {
  const next = { ...target };
  const errors: Record<string, string> = {};
  const sizeInput = inputs.size;
  if (sizeInput !== undefined) next.size = Number(sizeInput);
  const size = next.size ?? 1;
  if (
    (sizeInput !== undefined && !sizeInput.trim()) ||
    !Number.isSafeInteger(size) ||
    size < 0 ||
    size > 64
  )
    errors.size = "Target size requires a whole number between 0 and 64.";
  for (const key of ["hitpoints", "current_hitpoints"] as const) {
    const raw = inputs[key];
    if (raw !== undefined) next[key] = raw.trim() ? Number(raw) : null;
    const value = next[key];
    if (
      value != null &&
      (!Number.isSafeInteger(value) || value < 1 || value > 1000000)
    )
      errors[key] =
        `Target ${key === "hitpoints" ? "base" : "current"} hitpoints require a whole number from 1 to 1,000,000.`;
  }
  if (
    !errors.hitpoints &&
    !errors.current_hitpoints &&
    next.hitpoints != null &&
    next.current_hitpoints != null &&
    next.current_hitpoints > next.hitpoints
  )
    errors.current_hitpoints =
      "Target current hitpoints cannot exceed base hitpoints.";
  return { target: next, errors };
}

export function normalizeTargetHitpoints(
  target?: CombatTarget,
  inputs: TargetInputs = {},
): CombatTarget | undefined {
  if (!target) return target;
  const normalized = readTargetHitpoints(target, inputs);
  const [error] = Object.values(normalized.errors);
  if (error) throw new Error(error);
  return normalized.target;
}

export function validateTargetFlatArmour(
  target?: CombatTarget,
  inputs: TargetInputs = {},
) {
  const armour = target?.flat_armour ?? 0;
  if (
    (inputs.flat_armour !== undefined && !inputs.flat_armour.trim()) ||
    !Number.isSafeInteger(armour) ||
    Math.abs(armour) > 10000
  )
    throw new Error(
      "Target flat armour requires a whole number between -10000 and 10000.",
    );
}

export function roleTargetNumber(key: string, value: string, roleName: string) {
  const optional = [
    "ranged_light",
    "ranged_standard",
    "ranged_heavy",
    "damage_cap",
  ].includes(key);
  if (optional && !value.trim()) return null;
  const number = Number(value);
  const min =
    key === "flat_armour"
      ? -10000
      : key.startsWith("bonuses.") || key.startsWith("ranged_")
        ? -64
        : key === "damage_cap"
          ? 1
          : 0;
  const max =
    key === "size"
      ? 64
      : key === "weakness_percent"
        ? 1000
        : key === "damage_cap"
          ? Number.MAX_SAFE_INTEGER
          : 10000;
  if (
    !value.trim() ||
    !Number.isSafeInteger(number) ||
    number < min ||
    number > max
  ) {
    const label = key.startsWith("bonuses.")
      ? `${key.slice(8)} defence bonus`
      : key.replaceAll("_", " ");
    throw new Error(
      `${roleName.trim() || "Configuration"} target ${label} must be a whole number from ${min} to ${max}.`,
    );
  }
  return number;
}

export function targetFieldErrors(
  target: CombatTarget,
  inputs: TargetInputs = {},
  roleName?: string,
): Partial<Record<string, string>> {
  const { errors } = readTargetHitpoints(target, inputs);
  if (!target.name.trim()) errors.name = "Target name is required.";
  const armourError = validationMessage(() =>
    validateTargetFlatArmour(target, inputs),
  );
  if (armourError) errors.flat_armour = armourError;
  if (roleName) {
    for (const [key, value] of Object.entries(inputs)) {
      if (key === "hitpoints" || key === "current_hitpoints" || errors[key])
        continue;
      const error = validationMessage(() =>
        roleTargetNumber(key, value, roleName),
      );
      if (error) errors[key] = error;
    }
  }
  return errors;
}
