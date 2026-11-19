import type {
  JointSolutionDTO,
  ObjectiveFrontierGroup,
  OptimizationReply,
} from "../api/contracts";
import type { LabExample, LabPoint } from "./model";

const PREFIX = "gear-tradeoff-lab:";
const VERSION = 1;
const LIFETIME_MS = 2 * 60 * 60 * 1000;
const MAX_SESSIONS = 3;
const TOKEN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const INVALID =
  "This Tradeoff Lab snapshot is invalid. Open the lab again from the optimizer result.";
const STORAGE_ERROR =
  "Unable to open the Tradeoff Lab using browser storage. Allow local storage or free some browser storage and try again.";

type Envelope = {
  version: number;
  createdAt: number;
  expiresAt: number;
  snapshot: LabExample;
};
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const text = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= 512;
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(text);

function assertSnapshot(value: unknown): asserts value is LabExample {
  if (
    !record(value) ||
    !text(value.target) ||
    !text(value.evaluatedAt) ||
    !Number.isFinite(Date.parse(value.evaluatedAt)) ||
    !finite(value.budgetGp) ||
    value.budgetGp < 0 ||
    !Number.isSafeInteger(value.totalCount) ||
    Number(value.totalCount) < 0 ||
    typeof value.sampled !== "boolean" ||
    !text(value.scope) ||
    !text(value.selectedId) ||
    !text(value.sourceDescription) ||
    !Array.isArray(value.metrics) ||
    value.metrics.length < 1 ||
    value.metrics.length > 65 ||
    !Array.isArray(value.points) ||
    !value.points.length ||
    value.points.length > 2048
  )
    throw new Error(INVALID);
  if (
    value.sampleCount !== undefined &&
    (!Number.isSafeInteger(value.sampleCount) ||
      Number(value.sampleCount) < 0 ||
      Number(value.sampleCount) > value.points.length)
  )
    throw new Error(INVALID);
  const keys = value.metrics.map((metric: unknown) => {
    if (
      !record(metric) ||
      !text(metric.key) ||
      (metric.direction !== undefined &&
        !["minimize", "maximize"].includes(String(metric.direction))) ||
      !text(metric.label) ||
      !text(metric.shortLabel) ||
      ![
        "dps",
        "roll",
        "bonus",
        "probability",
        "percent",
        "GP/damage",
        "GP",
      ].includes(String(metric.unit))
    )
      throw new Error(INVALID);
    return metric.key;
  });
  if (new Set(keys).size !== keys.length || keys[0] !== "dps")
    throw new Error(INVALID);
  const ids = new Set<string>();
  for (const point of value.points) {
    if (
      !record(point) ||
      !text(point.id) ||
      ids.has(point.id) ||
      !text(point.label) ||
      !finite(point.dps) ||
      !finite(point.defence) ||
      !finite(point.prayer) ||
      !finite(point.costGp) ||
      point.costGp < 0 ||
      !record(point.values) ||
      keys.some((key) => {
        const number = (point.values as Record<string, unknown>)[key];
        return key === "wilderness_loss_gp"
          ? !Number.isSafeInteger(number) || Number(number) < 0
          : key === "gp_per_damage"
            ? number !== null && (!finite(number) || number < 0)
            : !finite(number);
      }) ||
      point.values.dps !== point.dps ||
      !Array.isArray(point.equipment) ||
      point.equipment.length > 1000 ||
      !strings(point.potions) ||
      !text(point.attackType) ||
      !text(point.stance)
    )
      throw new Error(INVALID);
    const slots = new Set<string>();
    for (const item of point.equipment) {
      if (
        !record(item) ||
        !text(item.slot) ||
        slots.has(item.slot) ||
        !text(item.name) ||
        !Number.isSafeInteger(item.itemId) ||
        Number(item.itemId) < 1
      )
        throw new Error(INVALID);
      slots.add(item.slot);
    }
    ids.add(point.id);
  }
  if (!ids.has(value.selectedId)) throw new Error(INVALID);
}

export function selectedLabSolution(
  result: OptimizationReply,
  selectedId: string,
): JointSolutionDTO | undefined {
  const selected = result.solutions.find(
    (solution) => solution.id === selectedId,
  )?.live;
  if (selected) return selected;
  if (selectedId === "best-found")
    return result.live?.result.selected_solution ?? undefined;
  if (selectedId === "unrestricted")
    return (
      result.unrestricted?.live ?? result.live?.result.unrestricted ?? undefined
    );
  return (
    result.live?.result.discipline_results?.find(
      (row) => `discipline-${row.discipline}-best-found` === selectedId,
    )?.selected_solution ?? undefined
  );
}

function targetDescription(result: OptimizationReply): string {
  const request = result.scenario.request;
  const targets = [
    ...new Set(
      request.roles.map(
        (role) => role.combatTarget?.name?.trim() || request.target.name,
      ),
    ),
  ];
  const label =
    targets.length > 1
      ? `Multiple role targets: ${targets.join(", ")}`
      : (targets[0] ?? request.target.name);
  return label.length > 512 ? `${label.slice(0, 511)}…` : label;
}

export function createLabSnapshot(
  result: OptimizationReply,
  group: ObjectiveFrontierGroup,
  selectedId: string,
): LabExample {
  const definitions =
    result.live?.result.objective_definitions ??
    result.live?.objective_definitions ??
    [];
  const metrics = [
    { key: "dps", label: "DPS", shortLabel: "DPS", unit: "dps" },
    ...definitions.map((definition) => ({
      key: definition.id,
      label: definition.label,
      shortLabel:
        definition.unit === "GP/damage" ? "GP/damage" : definition.label,
      unit: definition.unit,
      ...(definition.direction && { direction: definition.direction }),
    })),
  ];
  const names = new Map(
    (result.live?.items ?? []).map((item) => [item.numeric_item_id, item.name]),
  );
  for (const item of result.items ?? [])
    if (!names.has(item.id)) names.set(item.id, item.name);
  const roles = new Map(
    result.scenario.request.roles.map((role) => [role.id, role.name]),
  );
  const toPoint = (
    id: string,
    label: string,
    raw: JointSolutionDTO,
  ): LabPoint => {
    const values: Record<string, number | null> = {
      dps: raw.score,
      ...raw.objective_values,
    };
    for (const metric of metrics)
      if (metric.key === "gp_per_damage" && values[metric.key] == null)
        values[metric.key] = null;
      else if (!finite(values[metric.key]))
        throw new Error(
          "A saved objective value is unavailable. Run optimization again before opening the lab.",
        );
    const loadouts = Object.entries(raw.loadouts);
    const equipment = loadouts
      .flatMap(([roleId, loadout]) =>
        Object.entries(loadout.equipment)
          .filter(([, itemId]) => Number.isSafeInteger(itemId) && itemId > 0)
          .map(([slot, itemId]) => ({
            slot:
              loadouts.length > 1
                ? `${roles.get(roleId) ?? roleId} [${roleId}] · ${slot}`
                : slot,
            itemId,
            name: names.get(itemId) ?? `Item ${itemId}`,
          })),
      )
      .sort((a, b) => a.slot.localeCompare(b.slot));
    const options = loadouts.map(([, loadout]) => loadout.combat_option);
    return {
      id,
      label,
      dps: raw.score,
      defence: 0,
      prayer: 0,
      values,
      costGp: raw.purchase_cost_gp,
      equipment,
      potions:
        raw.potions?.resources?.map((resource) => resource.name) ??
        raw.potions?.selected_ids ??
        [],
      attackType: [
        ...new Set(
          options.map((option) => option?.attack_type ?? "Unavailable"),
        ),
      ].join(", "),
      stance: [
        ...new Set(options.map((option) => option?.stance ?? "Unavailable")),
      ].join(", "),
    };
  };
  const points = group.points.map((point, index) =>
    toPoint(
      point.id,
      `Loadout ${String(index + 1).padStart(3, "0")}`,
      point.solution,
    ),
  );
  const selected = selectedLabSolution(result, selectedId);
  if (
    !points.some((point) => point.id === selectedId) &&
    selected &&
    (group.swap_limit === null || selected.maximum_actions <= group.swap_limit)
  )
    points.push(toPoint(selectedId, "Current selection", selected));
  // The absolute DPS leader can sit outside the priced Pareto sample.
  const baseline = group.baseline_solution;
  const capId = group.baseline_solution_id;
  if (
    baseline &&
    capId &&
    metrics.some((m) => m.key === "gp_per_damage") &&
    baseline.objective_values?.gp_per_damage == null &&
    !points.some((point) => point.id === capId) &&
    !(
      selected &&
      selected.score === baseline.score &&
      selected.objective_values?.gp_per_damage == null
    )
  )
    points.push(toPoint(capId, "Highest DPS setup", baseline));
  if (!points.length)
    throw new Error(
      "There are no saved configurations available for this tradeoff lab.",
    );
  const hasSelection = points.some((point) => point.id === selectedId);
  const baselineId = hasSelection
    ? selectedId
    : points.reduce((best, point) => (point.dps > best.dps ? point : best)).id;
  const snapshot: LabExample = {
    target: targetDescription(result),
    evaluatedAt: result.evaluatedAt,
    budgetGp: result.scenario.request.budget_gp,
    totalCount: group.total_count ?? group.points.length,
    sampleCount: group.points.length,
    sampled: group.sampled,
    scope:
      group.swap_limit === null
        ? "Saved frontier · unrestricted swaps"
        : `Saved frontier · maximum ${group.swap_limit} swaps`,
    selectedId: baselineId,
    points,
    metrics,
    sourceDescription: hasSelection
      ? "Saved from the current optimization result."
      : "The current selection was unavailable for this frontier; the highest saved DPS configuration is the comparison baseline.",
  };
  assertSnapshot(snapshot);
  return snapshot;
}

function parseEnvelope(encoded: string): Envelope {
  const value: unknown = JSON.parse(encoded);
  if (
    !record(value) ||
    value.version !== VERSION ||
    !finite(value.createdAt) ||
    !finite(value.expiresAt) ||
    value.expiresAt <= value.createdAt ||
    value.expiresAt - value.createdAt > LIFETIME_MS
  )
    throw new Error(INVALID);
  assertSnapshot(value.snapshot);
  return value as Envelope;
}

function savedSessions(storage: Storage): { key: string; createdAt: number }[] {
  const keys = Array.from({ length: storage.length }, (_, i) =>
    storage.key(i),
  ).filter((key): key is string => key !== null && key.startsWith(PREFIX));
  return keys.flatMap((key) => {
    try {
      const envelope = parseEnvelope(storage.getItem(key) ?? "");
      if (envelope.expiresAt > Date.now())
        return [{ key, createdAt: envelope.createdAt }];
    } catch {
      /* Only this feature's malformed or expired handoffs are removed. */
    }
    storage.removeItem(key);
    return [];
  });
}

export function storeLabSnapshot(
  snapshot: LabExample,
  storage?: Storage,
): string {
  assertSnapshot(snapshot);
  const token = crypto.randomUUID();
  const createdAt = Date.now();
  const encoded = JSON.stringify({
    version: VERSION,
    createdAt,
    expiresAt: createdAt + LIFETIME_MS,
    snapshot,
  });
  try {
    const target = storage ?? localStorage;
    const previous = savedSessions(target).sort(
      (a, b) => b.createdAt - a.createdAt,
    );
    target.setItem(PREFIX + token, encoded);
    for (const old of previous.slice(MAX_SESSIONS - 1))
      target.removeItem(old.key);
  } catch {
    throw new Error(STORAGE_ERROR);
  }
  return token;
}

export function loadLabSnapshot(token: string, storage?: Storage): LabExample {
  if (!TOKEN.test(token)) throw new Error(INVALID);
  let encoded: string | null;
  try {
    encoded = (storage ?? localStorage).getItem(PREFIX + token);
  } catch {
    throw new Error(STORAGE_ERROR);
  }
  if (!encoded)
    throw new Error(
      "This Tradeoff Lab snapshot is unavailable. Open the lab again from the optimizer result.",
    );
  let envelope: Envelope;
  try {
    envelope = parseEnvelope(encoded);
  } catch {
    throw new Error(INVALID);
  }
  if (envelope.expiresAt <= Date.now())
    throw new Error(
      "This Tradeoff Lab snapshot has expired. Open the lab again from the optimizer result.",
    );
  return envelope.snapshot;
}
