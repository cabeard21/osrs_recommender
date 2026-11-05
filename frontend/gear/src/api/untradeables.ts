/** Untradeable acquisitions are hypothetical, separate from GE purchases. */
export function validateUntradeables(
  value: unknown,
  equipped: number[],
  purchases: number[],
  enabled: boolean,
): number[] {
  if (value === undefined) return [];
  if (
    !Array.isArray(value) ||
    value.some(
      (id, index) =>
        !Number.isSafeInteger(id) ||
        id <= 0 ||
        !equipped.includes(id) ||
        purchases.includes(id) ||
        (index > 0 && value[index - 1] >= id),
    ) ||
    (!enabled && value.length > 0)
  )
    throw new Error("Invalid untradeable acquisition requirements");
  return value as number[];
}
