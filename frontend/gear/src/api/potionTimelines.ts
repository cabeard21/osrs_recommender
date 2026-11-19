import {
  canonicalObjectives,
  objectiveId,
  objectiveValues,
} from "./objectives";
import type {
  JointSolutionDTO,
  OptimizationReply,
  PotionTimeline,
  PotionTimelineMeasurement,
} from "./contracts";
import { object, requireFields, strings } from "./runtime";

export function parsePotionTimeline(
  value: unknown,
  result: OptimizationReply,
  solution: JointSolutionDTO,
  roleIds: string[],
): PotionTimeline {
  const row = requireFields(value, {
    snapshot_id: "string",
    catalog_version: "string",
    model_version: "string",
    decay_model_version: "string",
    configuration_fingerprint: "string",
    secondary_priority: "string",
  });
  if (
    row.snapshot_id !== result.snapshotId ||
    row.catalog_version !== result.catalogVersion ||
    row.model_version !== result.modelVersion ||
    row.decay_model_version !== "potion-decay-v1" ||
    !row.configuration_fingerprint ||
    row.secondary_priority !==
      (result.scenario.request.secondary_priority ?? "default")
  )
    throw new Error("Potion timeline does not match the selected result");
  const nullableNumber = (v: unknown, nonnegative = false) =>
    v === null ||
    (typeof v === "number" && Number.isFinite(v) && (!nonnegative || v >= 0));
  const objectives = result.scenario.request.objectives;
  const goals =
    objectives === undefined ? undefined : canonicalObjectives(objectives);
  const validateObjectives = (
    point: Record<string, unknown>,
    aggregate = true,
  ) => {
    if (!goals) return;
    const ids = goals
      .map(objectiveId)
      .filter((id) => aggregate || id !== "wilderness_loss_gp");
    const values = object(point.objective_values ?? {});
    if (
      Object.keys(values).some((id) => !ids.includes(id)) ||
      ids.some((id) =>
        id === "wilderness_loss_gp"
          ? !Number.isSafeInteger(values[id]) ||
            Number(values[id]) < 0 ||
            values[id] !== solution.wilderness_risk?.loss_gp
          : id === "gp_per_damage"
            ? values[id] != null && !nullableNumber(values[id], true)
            : point.dps === null
              ? values[id] !== undefined && !nullableNumber(values[id])
              : typeof values[id] !== "number" || !Number.isFinite(values[id]),
      )
    )
      throw new Error("Invalid potion timeline objective measurements");
  };
  const measurement = (value: unknown): PotionTimelineMeasurement => {
    const point = object(value);
    validateObjectives(point);
    const levels = object(point.levels),
      roles = object(point.roles);
    if (
      !Number.isSafeInteger(point.time_seconds) ||
      (point.time_seconds as number) < 0 ||
      !nullableNumber(point.dps, true) ||
      !nullableNumber(point.secondary_value) ||
      !Object.keys(levels).length ||
      Object.values(levels).some(
        (v) => !Number.isSafeInteger(v) || (v as number) < 0,
      ) ||
      Object.keys(roles).length !== roleIds.length ||
      roleIds.some((id) => !(id in roles))
    )
      throw new Error("Invalid potion timeline measurement");
    for (const value of Object.values(roles)) {
      const role = object(value);
      validateObjectives(role, false);
      if (
        !nullableNumber(role.dps, true) ||
        !nullableNumber(role.secondary_value) ||
        !strings(role.reasons)
      )
        throw new Error("Invalid potion timeline role measurement");
    }
    return point as unknown as PotionTimelineMeasurement;
  };
  const baseline = measurement(row.baseline);
  if (
    !Array.isArray(row.samples) ||
    row.samples.length < 2 ||
    row.samples.length > 100
  )
    throw new Error("Invalid potion timeline samples");
  const samples = row.samples.map(measurement);
  if (
    baseline.time_seconds !== 0 ||
    samples[0].time_seconds !== 0 ||
    samples.some(
      (p, i) => i > 0 && p.time_seconds <= samples[i - 1].time_seconds,
    )
  )
    throw new Error("Invalid potion timeline ordering");
  const close = (a: number | null, b: number | null | undefined) =>
    typeof a === "number" &&
    typeof b === "number" &&
    Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(b));
  if (
    !close(samples[0].dps, solution.score) ||
    (row.secondary_priority !== "default" &&
      !close(samples[0].secondary_value, solution.secondary_value))
  )
    throw new Error(
      "Fresh potion timeline measurements do not match the selected result",
    );
  if (goals) {
    const expected = objectiveValues(
      solution.objective_values ?? {},
      goals,
      true,
    );
    for (const [id, value] of Object.entries(expected))
      if (
        value === null
          ? samples[0].objective_values?.[id] != null
          : !close(samples[0].objective_values?.[id] ?? null, value)
      )
        throw new Error(
          "Fresh objective timeline does not match the selected result",
        );
  }
  return { ...row, baseline, samples } as unknown as PotionTimeline;
}
