import savedExample from "./example.json";

export type MetricKey = string;
export interface LabMetric {
  key: string;
  label: string;
  shortLabel: string;
  unit?: string;
}

export interface LabPoint {
  id: string;
  label: string;
  dps: number;
  defence: number;
  prayer: number;
  values?: Record<string, number>;
  costGp: number;
  equipment: { slot: string; itemId: number; name: string }[];
  potions: string[];
  attackType: string;
  stance: string;
}

export interface LabExample {
  target: string;
  evaluatedAt: string;
  budgetGp: number;
  totalCount: number;
  sampled: boolean;
  scope: string;
  selectedId: string;
  points: LabPoint[];
  metrics?: LabMetric[];
  sourceDescription?: string;
  sampleCount?: number;
}

/** Compact projection of temp.txt: one cap, unchanged scores and physical items. */
export const example: LabExample = savedExample;

export const METRICS: LabMetric[] = [
  { key: "dps", label: "DPS", shortLabel: "DPS" },
  { key: "defence", label: "Stab defense roll", shortLabel: "Stab defense" },
  { key: "prayer", label: "Prayer bonus", shortLabel: "Prayer bonus" },
] as const;

export function metricValue(point: LabPoint, key: MetricKey): number {
  return (
    point.values?.[key] ??
    (key === "dps"
      ? point.dps
      : key === "defence"
        ? point.defence
        : key === "prayer"
          ? point.prayer
          : NaN)
  );
}

export function formatMetric(
  key: MetricKey,
  value: number,
  metric?: LabMetric,
): string {
  if (!Number.isFinite(value)) return "Unavailable";
  if (metric?.unit === "probability") return `${(value * 100).toFixed(2)}%`;
  if (metric?.unit === "percent") return `${value.toFixed(2)}%`;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: key === "dps" ? 3 : 0,
    maximumFractionDigits: 3,
  });
}

export function metricBounds(
  points: LabPoint[],
  key: MetricKey,
): [number, number] {
  const values = points
    .map((point) => metricValue(point, key))
    .filter(Number.isFinite);
  return values.length ? [Math.min(...values), Math.max(...values)] : [0, 1];
}

export function normalizeMetric(
  value: number,
  [low, high]: [number, number],
): number {
  return high === low
    ? 0.5
    : Math.min(1, Math.max(0, (value - low) / (high - low)));
}

export function metricDelta(
  key: MetricKey,
  value: number,
  baseline: number,
  metric?: LabMetric,
): string {
  const delta = value - baseline;
  return `${delta > 0 ? "+" : ""}${formatMetric(key, delta, metric)}`;
}

/** Keep tied leaders stable regardless of the order of chart/table projections. */
export function metricLeader(
  points: LabPoint[],
  key: MetricKey,
): LabPoint | undefined {
  return points.reduce<LabPoint | undefined>(
    (best, candidate) =>
      !best ||
      metricValue(candidate, key) > metricValue(best, key) ||
      (metricValue(candidate, key) === metricValue(best, key) &&
        candidate.id.localeCompare(best.id) < 0)
        ? candidate
        : best,
    undefined,
  );
}

export function leaders(
  points: LabPoint[],
  metrics: LabMetric[] = METRICS,
): LabPoint[] {
  const selected = metrics.map(({ key }) => metricLeader(points, key));
  return selected.filter(
    (point, i): point is LabPoint =>
      point !== undefined &&
      selected.findIndex((other) => other?.id === point.id) === i,
  );
}

export function equipmentChanges(
  point: LabPoint,
  baseline: LabPoint,
): { slot: string; from: string; to: string }[] {
  const slots = [
    ...new Set(
      [...point.equipment, ...baseline.equipment].map((item) => item.slot),
    ),
  ].sort();
  return slots.flatMap((slot) => {
    const before = baseline.equipment.find((item) => item.slot === slot);
    const after = point.equipment.find((item) => item.slot === slot);
    return before?.itemId === after?.itemId
      ? []
      : [{ slot, from: before?.name ?? "Empty", to: after?.name ?? "Empty" }];
  });
}

/** Orthographic yaw about Y, then pitch about X; normalized data stays untouched. */
export function project3d(
  point: { x: number; y: number; z: number },
  yaw: number,
  pitch: number,
): { x: number; y: number; depth: number } {
  const y = (yaw * Math.PI) / 180,
    p = (pitch * Math.PI) / 180;
  const x = point.x * Math.cos(y) + point.z * Math.sin(y);
  const z = -point.x * Math.sin(y) + point.z * Math.cos(y);
  return {
    x,
    y: point.y * Math.cos(p) - z * Math.sin(p),
    depth: point.y * Math.sin(p) + z * Math.cos(p),
  };
}
