/** Roll values are displayed in thousands; calculations retain full precision. */
export function formatDefenceRoll(value: number | null | undefined): string {
  return typeof value === "number"
    ? `${(value / 1000).toFixed(2)}k`
    : "unavailable";
}

export function formatRollGainPercent(
  gain: number,
  baseline: number | null | undefined,
): string {
  return typeof baseline === "number" && baseline !== 0
    ? `${((gain / baseline) * 100).toFixed(2)}%`
    : "percentage unavailable";
}
