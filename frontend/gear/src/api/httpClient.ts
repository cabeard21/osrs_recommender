import {
  canonicalObjectives,
  objectiveId,
  objectiveValues,
} from "./objectives";
import { parsePotionTimeline } from "./potionTimelines";
import { createProgressId, pollOptimizationProgress } from "./progress";
import { validateUntradeables } from "./untradeables";
import { validateRunningCost } from "./runningCosts";
import { purchaseItemIds } from "./preparedPurchases";
import {
  normalizedWilderness,
  parseWildernessRisk,
  wildernessRiskCap,
} from "./wilderness";
import {
  object,
  requireFields,
  strings,
  equipmentMap,
  performanceMetrics,
  sameValue,
  uiSlot,
} from "./runtime";
import { parseJointSolution } from "./jointResults";
import { validateSecondaryPriority } from "./secondaryPriorities";
import {
  validateOptimizationPolicy,
  validateRefinementDiagnostics,
  validateAssignmentDiagnostics,
} from "./optimizationModes";
import { apiSlot, optimizationRequest } from "./optimizationRequest";
export { optimizationRequest } from "./optimizationRequest";
export { performanceMetrics } from "./runtime";
import { emptyEquipment, slots } from "./contracts";
import { parseAlternatives } from "./contextualAlternatives";
import type {
  ContextDTO,
  Equipment,
  GearClient,
  GearContext,
  Item,
  ItemPage,
  OptimizationReply,
  OptimizationProgress,
  OptimizationDTO,
  CombatPerformance,
  CombatOption,
  PhysicalItem,
  Scenario,
  Slot,
  Trial,
  EvaluationDTO,
  FixedEvaluation,
  Solution,
  SupportPolicy,
  JointSolutionDTO,
  PotionTimeline,
} from "./contracts";

function scans(value: unknown) {
  for (const scan of Object.values(object(value))) {
    if (scan !== null)
      requireFields(scan, { scanned_at: "string", source: "string" });
  }
}
export function parseOptimization(
  value: unknown,
  scenario: Scenario,
): OptimizationReply {
  const envelope = requireFields(value, {
    api_version: "string",
    evaluated_at: "string",
    price_revision: "string",
    scenario_fingerprint: "string",
  });
  if (envelope.api_version !== "gear-ui-v1" || !Array.isArray(envelope.items))
    throw new Error("Unsupported optimization response");
  const submitted = optimizationRequest(scenario);
  function matches(expected: unknown, actual: unknown): boolean {
    if (Array.isArray(expected))
      return (
        Array.isArray(actual) &&
        expected.length === actual.length &&
        expected.every((entry, index) => matches(entry, actual[index]))
      );
    if (expected && typeof expected === "object")
      return (
        !!actual &&
        typeof actual === "object" &&
        Object.entries(expected).every(([key, entry]) =>
          matches(entry, (actual as Record<string, unknown>)[key]),
        )
      );
    return expected === actual;
  }
  const normalizedServerScenario = {
    ...object(envelope.scenario),
    roles: (object(envelope.scenario).roles as unknown[]).map((role) => ({
      ...object(role),
      on_slayer_task: object(role).on_slayer_task ?? false,
      safe_spotting: object(role).safe_spotting ?? false,
      fight_duration_seconds: object(role).fight_duration_seconds ?? 60,
      mark_of_darkness: object(role).mark_of_darkness ?? false,
    })),
    fire_tome_pages: object(envelope.scenario).fire_tome_pages ?? "burnt",
    include_untradeables:
      object(envelope.scenario).include_untradeables ?? false,
    max_dps_loss_pct: object(envelope.scenario).max_dps_loss_pct ?? 10,
    optimization_mode: object(envelope.scenario).optimization_mode ?? "fast",
    secondary_priority:
      object(envelope.scenario).secondary_priority ?? "default",
    potions: object(envelope.scenario).potions ?? {
      mode: "disabled",
      allowed_ids: [],
      selected_ids: [],
    },
  };
  if (!matches(submitted, normalizedServerScenario))
    throw new Error(
      "Optimization scenario does not match the submitted constraints",
    );
  const serverScenario = object(envelope.scenario);
  const submittedConstraints = object(submitted);
  if (
    !sameValue(serverScenario.locks ?? {}, submitted.locks ?? {}) ||
    !sameValue(
      normalizedWilderness(
        serverScenario.wilderness,
        serverScenario.objectives,
      ),
      normalizedWilderness(
        submitted.wilderness,
        submittedConstraints.objectives,
      ),
    ) ||
    !sameValue(
      serverScenario.transitions ?? [],
      submittedConstraints.transitions ?? [],
    ) ||
    !sameValue(
      serverScenario.ordered_roles ?? [],
      submittedConstraints.ordered_roles ?? [],
    ) ||
    (serverScenario.loop ?? false) !== (submittedConstraints.loop ?? false)
  )
    throw new Error("Optimization scenario contains unsubmitted constraints");
  for (const [index, role] of submitted.roles.entries()) {
    const serverRole = object((serverScenario.roles as unknown[])[index]);
    const serverTarget = object(serverRole.target);
    if (
      !sameValue(serverRole.locks, role.locks) ||
      Object.entries(object(serverTarget.bonuses)).some(
        ([key, bonus]) => bonus !== (role.target.bonuses[key] ?? 0),
      )
    )
      throw new Error(
        "Optimization target bonuses or locks do not match the submitted target",
      );
  }
  const result = requireFields(envelope.result, {
    snapshot_id: "string",
    catalog_version: "string",
    model_version: "string",
    assumptions_fingerprint: "string",
  });
  if (
    result.support_policy !== undefined &&
    result.support_policy !== submitted.support_policy
  )
    throw new Error(
      "Equipment support policy does not match the submitted request",
    );
  if (
    result.support_provenance !== undefined &&
    typeof result.support_provenance !== "string"
  )
    throw new Error("Invalid equipment support provenance");
  const jointAuto =
    scenario.request.roles.length > 1 &&
    scenario.request.roles.some((role) => role.autoDiscipline);
  const assignmentCount = jointAuto
    ? scenario.request.roles.reduce(
        (count, role) =>
          count *
          (role.autoDiscipline ? (role.allowedDisciplines?.length ?? 3) : 1),
        1,
      )
    : undefined;
  validateOptimizationPolicy(
    envelope,
    result,
    scenario.request.optimization_mode ?? "fast",
    !jointAuto && scenario.request.roles[0]?.autoDiscipline
      ? (scenario.request.roles[0].allowedDisciplines?.length ?? 3)
      : 1,
    assignmentCount,
  );
  const priority = scenario.request.secondary_priority ?? "default";
  validateSecondaryPriority(envelope, priority);
  validateSecondaryPriority(result, priority);
  const expectedFrontierPolicy =
    priority === "default"
      ? null
      : {
          policy: "tradeoff-frontier-v2",
          ...(priority.endsWith("_defence_roll")
            ? { defensive_roll_model: "player-defence-roll-v1" }
            : {}),
          metric_lane_equipment_fraction: 0.25,
          expansion_limit:
            scenario.request.optimization_mode === "thorough"
              ? 1500000
              : 500000,
          refinement_assignment_limit:
            scenario.request.optimization_mode === "thorough" ? 10000 : 0,
          finalist_assignment_limit: 2048,
        };
  for (const row of [envelope, result]) {
    if (scenario.request.objectives !== undefined) {
      const policy = object(row.frontier_policy);
      const count = canonicalObjectives(scenario.request.objectives).length;
      if (
        !["vector-pareto-v1", "vector-pareto-v2"].includes(
          String(policy.policy),
        ) ||
        policy.objective_count !== count ||
        policy.expansion_limit !==
          (scenario.request.optimization_mode === "thorough"
            ? 1500000
            : 500000) *
            count
      )
        throw new Error(
          "Vector objective search policy does not match the submitted objectives",
        );
      continue;
    }
    if (
      (row.frontier_policy !== undefined ||
        result.secondary_frontiers !== undefined) &&
      !sameValue(row.frontier_policy, expectedFrontierPolicy)
    )
      throw new Error("Frontier work policy does not match submitted scenario");
  }
  object(result.search);
  if (jointAuto) {
    validateAssignmentDiagnostics(result.search, scenario);
  } else if (scenario.request.roles[0]?.autoDiscipline) {
    const allowed = scenario.request.roles[0].allowedDisciplines ?? [
      "melee",
      "ranged",
      "magic",
    ];
    if (
      !Array.isArray(result.discipline_comparison) ||
      result.discipline_comparison.length !== allowed.length
    )
      throw new Error("Missing Auto discipline comparison");
    const seen = new Set<string>();
    for (const value of result.discipline_comparison) {
      const row = object(value);
      if (
        !allowed.includes(row.discipline as import("./contracts").Style) ||
        seen.has(String(row.discipline)) ||
        !strings(row.reasons) ||
        !["best_found", "no_feasible_solution_found"].includes(
          String(row.status),
        ) ||
        (row.score !== null &&
          (typeof row.score !== "number" ||
            !Number.isFinite(row.score) ||
            row.score < 0)) ||
        (row.purchase_cost_gp !== null &&
          (!Number.isSafeInteger(row.purchase_cost_gp) ||
            Number(row.purchase_cost_gp) < 0))
      )
        throw new Error("Invalid Auto discipline comparison");
      seen.add(String(row.discipline));
    }
    if (scenario.request.optimization_mode === "thorough") {
      const branches = object(
        object(object(result.search).discipline_selection).branches,
      );
      for (const discipline of allowed)
        validateRefinementDiagnostics(
          object(branches[discipline]).local_refinement,
          scenario.request.max_swaps,
        );
    }
  } else if (scenario.request.optimization_mode === "thorough")
    validateRefinementDiagnostics(
      object(result.search).local_refinement,
      scenario.request.max_swaps,
    );
  if (!strings(result.limitations))
    throw new Error("Invalid result limitations");
  const baseline = requireFields(envelope.baseline, { status: "string" });
  if (
    !["available", "unavailable"].includes(baseline.status as string) ||
    !strings(baseline.reasons)
  )
    throw new Error("Invalid current equipment baseline");
  equipmentMap(baseline.equipment);
  if (baseline.status === "available")
    performanceMetrics(baseline.performance as CombatPerformance);
  else if (baseline.performance !== null)
    throw new Error("Unavailable baseline must withhold combat metrics");
  const items = envelope.items.map(parseItem);
  const joint = scenario.request.roles.length > 1;
  const solutions: Solution[] = [];
  let unrestricted: Solution | null = null;
  if (joint) {
    if (!Array.isArray(result.curve))
      throw new Error("Missing joint swap-efficiency curve");
    const limits = new Set<number>();
    for (const point of result.curve) {
      const row = requireFields(point, {
        swap_limit: "number",
        status: "string",
      });
      if (
        !["best_found", "no_feasible_solution_found"].includes(
          String(row.status),
        ) ||
        (row.solution !== null && row.status !== "best_found")
      )
        throw new Error("Invalid curve point status");
      if (
        !Number.isSafeInteger(row.swap_limit) ||
        Number(row.swap_limit) < 0 ||
        Number(row.swap_limit) > scenario.request.max_swaps ||
        limits.has(Number(row.swap_limit))
      )
        throw new Error("Invalid curve action limit");
      limits.add(Number(row.swap_limit));
      if (row.solution !== null)
        solutions.push(
          parseJointSolution(
            row.solution,
            scenario,
            items,
            `curve-${row.swap_limit}`,
            Number(row.swap_limit),
          ),
        );
      else if (row.status !== "no_feasible_solution_found")
        throw new Error("Invalid missing curve solution status");
      if (
        row.relative_performance !== null &&
        (typeof row.relative_performance !== "number" ||
          !Number.isFinite(row.relative_performance))
      )
        throw new Error("Invalid curve performance ratio");
    }
    if (result.unrestricted !== null)
      unrestricted = parseJointSolution(
        result.unrestricted,
        scenario,
        items,
        "unrestricted",
        12,
      );
    for (const [id, share] of Object.entries(object(result.active_time_shares)))
      if (
        !scenario.request.roles.some((r) => r.id === id && !r.utility) ||
        typeof share !== "number" ||
        !Number.isFinite(share) ||
        share < 0 ||
        share > 1
      )
        throw new Error("Invalid active-time share");
    if (
      !sameValue(
        solutions.find((s) => s.actionLimit === scenario.request.max_swaps)
          ?.live ?? null,
        result.selected_solution,
      )
    )
      throw new Error(
        "Selected solution does not match the requested curve point",
      );
  } else if (result.selected_solution !== null) {
    const selected = requireFields(result.selected_solution, {
      score: "number",
      purchase_cost_gp: "number",
    });
    const wildernessRisk = parseWildernessRisk(
      selected.wilderness_risk,
      scenario.request,
      true,
      selected.objective_values,
    );
    validateRunningCost(selected.running_cost);
    validateSecondaryPriority(selected, priority, true);
    if (
      !Number.isFinite(selected.score) ||
      !Number.isSafeInteger(selected.purchase_cost_gp) ||
      Number(selected.purchase_cost_gp) < 0 ||
      !Array.isArray(selected.purchases)
    )
      throw new Error("Invalid acquisition result");
    const role = scenario.request.roles[0];
    const loadout = object(object(selected.loadouts)[role.id]);
    if (
      role.autoDiscipline &&
      !(role.allowedDisciplines ?? ["melee", "ranged", "magic"]).includes(
        loadout.discipline as import("./contracts").Style,
      )
    )
      throw new Error("Invalid resolved Auto discipline");
    validateRunningCost(loadout.running_cost);
    const equipment = equipmentMap(loadout.equipment);
    for (const id of Object.values(equipment))
      if (
        id !== null &&
        (!items.some((i) => i.id === id) ||
          scenario.request.excluded_item_ids.includes(id))
      )
        throw new Error("Missing physical result item metadata");
    const allowedPurchases = purchaseItemIds(
      Object.values(equipment).filter((id): id is number => id !== null),
      loadout.preparations,
      items,
    );
    const purchased = new Set<number>();
    const purchases = selected.purchases.map((p) => {
      const row = requireFields(p, {
        item_id: "number",
        conditional: "boolean",
      });
      if (
        !Number.isSafeInteger(row.item_id) ||
        Number(row.item_id) <= 0 ||
        !allowedPurchases.has(Number(row.item_id)) ||
        purchased.has(Number(row.item_id)) ||
        (row.quantity !== undefined && row.quantity !== 1) ||
        (row.cost_gp !== null &&
          (!Number.isSafeInteger(row.cost_gp) || Number(row.cost_gp) < 0))
      )
        throw new Error("Invalid purchase fact");
      purchased.add(Number(row.item_id));
      return row.item_id as number;
    });
    validateUntradeables(
      selected.unowned_untradeable_item_ids,
      Object.values(equipment).filter((id): id is number => id !== null),
      purchases,
      scenario.request.include_untradeables === true &&
        scenario.request.mode !== "owned",
    );
    solutions.push({
      id: "best-found",
      actionLimit: scenario.request.max_swaps,
      loadouts: [
        {
          roleId: role.id,
          name: "Best configuration found",
          equipment,
          metrics: performanceMetrics(loadout.performance as CombatPerformance),
          performance: loadout.performance as CombatPerformance,
          combatOption: loadout.combat_option as CombatOption | undefined,
          selectedPrayerIds: loadout.selected_prayer_ids as
            string[] | undefined,
          discipline: loadout.discipline as
            import("./contracts").Style | undefined,
        },
      ],
      weightedDps: selected.score as number,
      purchases,
      cost: selected.purchase_cost_gp as number,
      ...(wildernessRisk ? { wildernessRisk } : {}),
      shared: [],
      transitions: [],
    });
  }
  const frontierIds = new Set<string>();
  function parseFrontiers(
    frontiers: unknown,
    discipline?: string,
    runningCost = false,
  ) {
    if (!Array.isArray(frontiers))
      throw new Error("Invalid secondary frontiers");
    for (const value of frontiers) {
      const group = requireFields(value, { sampled: "boolean" });
      if (
        group.swap_limit !== null &&
        (!Number.isSafeInteger(group.swap_limit) ||
          Number(group.swap_limit) < 0 ||
          Number(group.swap_limit) > scenario.request.max_swaps)
      )
        throw new Error("Invalid frontier swap limit");
      if (
        group.baseline_dps !== null &&
        (typeof group.baseline_dps !== "number" ||
          !Number.isFinite(group.baseline_dps) ||
          group.baseline_dps < 0)
      )
        throw new Error("Invalid frontier baseline");
      if (!Array.isArray(group.points) || group.points.length > 64)
        throw new Error("Invalid frontier points");
      for (const value of group.points) {
        const point = requireFields(value, {
          id: "string",
          dps_loss: "number",
          ...(runningCost ? {} : { secondary_gain: "number" as const }),
        });
        if (runningCost) {
          const cost = object(object(point.solution).running_cost);
          validateRunningCost(cost);
          if (cost.status !== "known" || cost.gp_per_damage === null)
            throw new Error(
              "Cost frontier point requires a known GP per damage",
            );
        }
        if (
          frontierIds.has(String(point.id)) ||
          solutions.some((s) => s.id === point.id) ||
          !Number.isFinite(point.dps_loss) ||
          Number(point.dps_loss) < 0 ||
          (!runningCost && !Number.isFinite(point.secondary_gain)) ||
          (point.dps_loss_pct !== null &&
            (typeof point.dps_loss_pct !== "number" ||
              !Number.isFinite(point.dps_loss_pct) ||
              point.dps_loss_pct < 0 ||
              point.dps_loss_pct > (scenario.request.max_dps_loss_pct ?? 10)))
        )
          throw new Error("Invalid frontier measurement");
        if (
          discipline &&
          !String(point.id).startsWith(`discipline-${discipline}-`)
        )
          throw new Error("Invalid discipline frontier identity");
        if (
          discipline &&
          Object.values(object(object(point.solution).loadouts)).some(
            (loadout) => object(loadout).discipline !== discipline,
          )
        )
          throw new Error("Mismatched frontier discipline");
        frontierIds.add(String(point.id));
        solutions.push(
          parseJointSolution(
            point.solution,
            scenario,
            items,
            String(point.id),
            group.swap_limit === null ? 12 : Number(group.swap_limit),
          ),
        );
      }
    }
  }
  function parseObjectiveFrontiers(
    source: Record<string, unknown>,
    discipline?: string,
  ) {
    if (scenario.request.objectives === undefined) return;
    const objectives = canonicalObjectives(scenario.request.objectives);
    // The API omits empty objective fields when serializing a DPS-only run.
    const emptyObjectiveList = objectives.length === 0 ? [] : undefined;
    const {
      objective_definitions: definitions = emptyObjectiveList,
      objective_frontiers: frontiers = emptyObjectiveList,
    } = source;
    if (
      !Array.isArray(definitions) ||
      definitions.some((v) => {
        const d = object(v);
        return (
          (d.id === "gp_per_damage" || d.id === "wilderness_loss_gp") &&
          (d.kind !== d.id ||
            d.unit !== (d.id === "wilderness_loss_gp" ? "GP" : "GP/damage") ||
            d.direction !== "minimize")
        );
      }) ||
      !sameValue(
        definitions.map((value) => object(value).id).sort(),
        objectives.map(objectiveId).sort(),
      )
    )
      throw new Error(
        "Objective definitions do not match the submitted scenario",
      );
    if (!Array.isArray(frontiers))
      throw new Error("Missing objective frontiers");
    for (const raw of frontiers) {
      const group = object(raw);
      if (
        !Array.isArray(group.points) ||
        group.points.length > Math.max(128, 2 * (objectives.length + 1)) ||
        typeof group.sampled !== "boolean"
      )
        throw new Error("Invalid objective frontier sample");
      for (const entry of group.points) {
        const point = object(entry);
        if (typeof point.id !== "string" || frontierIds.has(point.id))
          throw new Error("Invalid objective frontier identity");
        if (
          discipline &&
          Object.values(object(object(point.solution).loadouts)).some(
            (loadout) => object(loadout).discipline !== discipline,
          )
        )
          throw new Error("Mismatched objective frontier discipline");
        objectiveValues(object(point.solution).objective_values, objectives);
        frontierIds.add(point.id);
        solutions.push(
          parseJointSolution(
            point.solution,
            scenario,
            items,
            point.id,
            group.swap_limit === null ? 100 : Number(group.swap_limit),
          ),
        );
      }
    }
  }
  parseObjectiveFrontiers(result);
  if (result.secondary_frontiers !== undefined)
    parseFrontiers(result.secondary_frontiers);
  if (result.running_cost_frontiers !== undefined)
    parseFrontiers(result.running_cost_frontiers, undefined, true);
  const branchAlternatives = new Map<
    string,
    ReturnType<typeof parseAlternatives>
  >();
  if (result.discipline_results !== undefined) {
    const allowed =
      !jointAuto && scenario.request.roles[0]?.autoDiscipline
        ? (scenario.request.roles[0].allowedDisciplines ?? [
            "melee",
            "ranged",
            "magic",
          ])
        : [];
    if (
      !Array.isArray(result.discipline_results) ||
      result.discipline_results.length !== allowed.length
    )
      throw new Error("Invalid Auto discipline results");
    const seen = new Set<string>();
    for (const value of result.discipline_results) {
      const branch = object(value);
      const discipline = String(branch.discipline);
      if (
        !allowed.includes(discipline as import("./contracts").Style) ||
        seen.has(discipline) ||
        !strings(branch.reasons) ||
        !strings(branch.limitations) ||
        !["best_found", "no_feasible_solution_found"].includes(
          String(branch.status),
        ) ||
        (branch.status === "best_found") !== (branch.selected_solution !== null)
      )
        throw new Error("Invalid Auto discipline result");
      const summary = (result.discipline_comparison as unknown[])
        .map(object)
        .find((row) => row.discipline === discipline);
      if (
        !summary ||
        summary.status !== branch.status ||
        summary.score !== branch.score ||
        summary.purchase_cost_gp !== branch.purchase_cost_gp ||
        (branch.selected_solution !== null &&
          (object(branch.selected_solution).score !== branch.score ||
            object(branch.selected_solution).purchase_cost_gp !==
              branch.purchase_cost_gp))
      )
        throw new Error("Auto discipline summary does not match its result");
      seen.add(discipline);
      object(branch.search);
      if (scenario.request.optimization_mode === "thorough")
        validateRefinementDiagnostics(
          object(branch.search).local_refinement,
          scenario.request.max_swaps,
        );
      if (branch.selected_solution !== null) {
        const parsed = parseJointSolution(
          branch.selected_solution,
          scenario,
          items,
          `discipline-${discipline}-best-found`,
          scenario.request.max_swaps,
        );
        if (
          parsed.loadouts.some((loadout) => loadout.discipline !== discipline)
        )
          throw new Error("Mismatched selected discipline");
        solutions.push(parsed);
      }
      if (branch.objective_frontiers !== undefined)
        parseObjectiveFrontiers(branch, discipline);
      parseFrontiers(branch.secondary_frontiers, discipline);
      if (branch.running_cost_frontiers !== undefined)
        parseFrontiers(branch.running_cost_frontiers, discipline, true);
      branchAlternatives.set(
        discipline,
        parseAlternatives(
          branch.alternatives,
          items,
          scenario.request.excluded_item_ids,
          wildernessRiskCap(scenario.request),
        ),
      );
    }
  }
  if (result.snapshot_id !== scenario.request.expected_snapshot_id)
    throw new Error(
      "The result does not match the submitted account snapshot.",
    );
  const dto = structuredClone(value) as OptimizationDTO;
  if (dto.result.discipline_results)
    dto.result.discipline_results = dto.result.discipline_results.map(
      (branch) => ({
        ...branch,
        alternatives: branchAlternatives.get(branch.discipline)!,
      }),
    );
  dto.result.alternatives = parseAlternatives(
    result.alternatives,
    items,
    scenario.request.excluded_item_ids,
    wildernessRiskCap(scenario.request),
  );
  return {
    source: "live",
    scenario: structuredClone(scenario),
    fingerprint: envelope.scenario_fingerprint as string,
    snapshotId: result.snapshot_id as string,
    evaluatedAt: envelope.evaluated_at as string,
    catalogVersion: result.catalog_version as string,
    modelVersion: result.model_version as string,
    priceRevision: envelope.price_revision as string,
    solutions,
    unrestricted,
    selectedSolutionId: joint
      ? `curve-${scenario.request.max_swaps}`
      : "best-found",
    warnings: dto.result.limitations,
    items,
    live: dto,
  };
}

export class GearApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status?: number,
    public phase?: string,
  ) {
    super(message);
  }
}
function concreteEquipment(equipment: Equipment): Record<string, number> {
  return Object.fromEntries(
    Object.entries(equipment)
      .filter(([, id]) => id !== null)
      .map(([slot, id]) => [apiSlot(slot as Slot), id as number]),
  );
}
function parseFixedEvaluation(
  value: unknown,
  expected: Equipment,
  items: Item[],
  request: Scenario["request"],
): FixedEvaluation {
  const row = requireFields(value, { status: "string" });
  if (
    !["valid", "invalid", "unsupported"].includes(String(row.status)) ||
    !Array.isArray(row.reasons) ||
    !Array.isArray(row.purchases) ||
    !Array.isArray(row.assumed_item_ids)
  )
    throw new Error("Invalid fixed-equipment evaluation");
  if (
    row.status === "valid" &&
    request.objectives?.some(
      (o) => o.kind === "gp_per_damage" || o.kind === "wilderness_loss_gp",
    )
  )
    objectiveValues(
      row.objective_values,
      canonicalObjectives(request.objectives),
      true,
    );
  const equipment = equipmentMap(row.equipment);
  if (!sameValue(equipment, expected))
    throw new Error(
      "Evaluation equipment does not match the requested configuration",
    );
  for (const [slot, id] of Object.entries(equipment))
    if (
      id !== null &&
      !items.some(
        (i) => i.id === id && (row.status !== "valid" || i.slot === slot),
      )
    )
      throw new Error("Missing physical evaluation item metadata");
  for (const reason of row.reasons)
    requireFields(reason, { path: "string", message: "string" });
  if (row.status === "valid")
    performanceMetrics(row.performance as CombatPerformance);
  else if (row.performance !== null || row.reasons.length === 0)
    throw new Error(
      "Invalid evaluations must withhold metrics and explain why",
    );
  if (
    row.purchase_cost_gp !== null &&
    (!Number.isSafeInteger(row.purchase_cost_gp) ||
      Number(row.purchase_cost_gp) < 0)
  )
    throw new Error("Invalid evaluation acquisition total");
  const allowedPurchases = purchaseItemIds(
    Object.values(equipment).filter((id): id is number => id !== null),
    row.preparations,
    items,
  );
  const purchased = new Set<number>();
  for (const entry of row.purchases) {
    const purchase = requireFields(entry, {
      item_id: "number",
      conditional: "boolean",
    });
    if (
      !Number.isSafeInteger(purchase.item_id) ||
      !allowedPurchases.has(Number(purchase.item_id)) ||
      purchased.has(Number(purchase.item_id)) ||
      (purchase.quantity !== undefined && purchase.quantity !== 1) ||
      (purchase.cost_gp !== null &&
        (!Number.isSafeInteger(purchase.cost_gp) ||
          Number(purchase.cost_gp) < 0))
    )
      throw new Error("Invalid evaluation purchase fact");
    purchased.add(Number(purchase.item_id));
  }
  if (
    row.assumed_item_ids.some(
      (id) =>
        !Number.isSafeInteger(id) || !Object.values(equipment).includes(id),
    )
  )
    throw new Error("Invalid evaluation assumed acquisitions");
  if (row.status === "valid" && row.purchase_cost_gp === null)
    throw new Error("Valid evaluation requires acquisition total");
  parseWildernessRisk(
    row.wilderness_risk,
    request,
    row.status === "valid",
    row.objective_values,
  );
  validateUntradeables(
    row.unowned_untradeable_item_ids,
    Object.values(equipment).filter((id): id is number => id !== null),
    [...purchased],
    request.include_untradeables === true && request.mode !== "owned",
  );
  return structuredClone(value) as FixedEvaluation;
}
export function parseEvaluation(
  value: unknown,
  result: OptimizationReply,
  solutionId: string,
  roleId: string,
  equipment: Equipment,
): Trial {
  const baselineEquipment = result.solutions
    .find((s) => s.id === solutionId)
    ?.loadouts.find((l) => l.roleId === roleId)?.equipment;
  if (result.source !== "live" || !result.live || !baselineEquipment)
    throw new Error("Live evaluation requires an accepted live configuration");
  if (result.live.scenario.include_untradeables === undefined)
    throw new GearApiError(
      "Saved result uses an older acquisition policy; reoptimize before evaluating",
      "stale_context",
    );
  const envelope = requireFields(value, {
    api_version: "string",
    evaluated_at: "string",
    scenario_fingerprint: "string",
    snapshot_id: "string",
    catalog_version: "string",
    model_version: "string",
    assumptions_fingerprint: "string",
    price_revision: "string",
  });
  const comparableScenario = (value: unknown) => {
    const row = object(value);
    return {
      ...row,
      wilderness: normalizedWilderness(row.wilderness, row.objectives),
    };
  };
  if (
    envelope.api_version !== "gear-ui-v1" ||
    !Array.isArray(envelope.items) ||
    !sameValue(
      comparableScenario(result.live.scenario),
      comparableScenario(envelope.scenario),
    ) ||
    envelope.scenario_fingerprint !== result.fingerprint
  )
    throw new Error(
      "Evaluation scenario does not match the original recommendation",
    );
  if (
    envelope.snapshot_id !== result.snapshotId ||
    envelope.catalog_version !== result.catalogVersion ||
    envelope.model_version !== result.modelVersion ||
    ((result.scenario.request.potions?.mode ?? "disabled") === "disabled" &&
      envelope.assumptions_fingerprint !==
        result.live.result.assumptions_fingerprint) ||
    envelope.price_revision !== result.priceRevision
  )
    throw new GearApiError(
      "Evaluation context changed; refresh and reoptimize",
      "stale_context",
    );
  if ((result.scenario.request.potions?.mode ?? "disabled") !== "disabled") {
    const expectedIds = result.solutions.find((s) => s.id === solutionId)?.live
      ?.potions?.selected_ids;
    if (
      !expectedIds ||
      [envelope.baseline, envelope.proposed].some(
        (evaluation) =>
          !sameValue(
            object(object(evaluation).potions).selected_ids,
            expectedIds,
          ),
      )
    )
      throw new Error(
        "Evaluation potions do not match the selected recommendation",
      );
  }
  const items = envelope.items.map(parseItem);
  if (items.some((i) => i.facts?.catalog_version !== result.catalogVersion))
    throw new Error(
      "Evaluation item catalog does not match calculation provenance",
    );
  const baseline = parseFixedEvaluation(
      envelope.baseline,
      baselineEquipment,
      items,
      result.scenario.request,
    ),
    proposed = parseFixedEvaluation(
      envelope.proposed,
      equipment,
      items,
      result.scenario.request,
    );
  const valid = baseline.status === "valid" && proposed.status === "valid";
  if (valid) {
    const deltas = requireFields(envelope.deltas, {
      dps: "number",
      max_hit: "number",
      accuracy: "number",
      attack_interval: "number",
      purchase_cost_gp: "number",
    });
    if (
      [
        deltas.dps,
        deltas.max_hit,
        deltas.accuracy,
        deltas.attack_interval,
        deltas.purchase_cost_gp,
      ].some((n) => !Number.isFinite(n)) ||
      !Number.isSafeInteger(deltas.max_hit) ||
      !Number.isSafeInteger(deltas.purchase_cost_gp) ||
      !Array.isArray(deltas.equipment_changes) ||
      !Array.isArray(deltas.added_purchase_ids) ||
      !Array.isArray(deltas.removed_purchase_ids)
    )
      throw new Error("Invalid evaluation comparison");
    if (
      result.scenario.request.objectives?.some(
        (o) => o.kind === "gp_per_damage",
      )
    ) {
      const costChange = object(deltas.objective_values ?? {}).gp_per_damage;
      const original = baseline.objective_values?.gp_per_damage;
      const updated = proposed.objective_values?.gp_per_damage;
      if (
        original == null || updated == null
          ? costChange != null
          : costChange !== updated - original
      )
        throw new Error("Invalid running cost comparison");
    }
    if (
      result.scenario.request.objectives?.some(
        (o) => o.kind === "wilderness_loss_gp",
      ) &&
      baseline.status === "valid" &&
      proposed.status === "valid" &&
      object(deltas.objective_values ?? {}).wilderness_loss_gp !==
        Number(proposed.wilderness_risk?.loss_gp) -
          Number(baseline.wilderness_risk?.loss_gp)
    )
      throw new Error("Invalid Wilderness loss comparison");
    for (const change of deltas.equipment_changes) {
      const row = requireFields(change, { slot: "string" }),
        slot = uiSlot(row.slot) as Slot;
      if (
        !slots.includes(slot) ||
        row.baseline_item_id !== baselineEquipment[slot] ||
        row.proposed_item_id !== equipment[slot]
      )
        throw new Error("Invalid equipment comparison");
    }
    for (const [key, purchases] of [
      ["added_purchase_ids", proposed.purchases],
      ["removed_purchase_ids", baseline.purchases],
    ] as const)
      if (
        (deltas[key] as unknown[]).some(
          (id) =>
            !Number.isSafeInteger(id) ||
            !purchases.some((p) => p.item_id === id),
        )
      )
        throw new Error("Invalid purchase comparison");
  } else if (envelope.deltas !== null)
    throw new Error("Invalid evaluations cannot provide numeric differences");
  return {
    source: "live",
    resultFingerprint: result.fingerprint,
    solutionId,
    roleId,
    equipment: structuredClone(equipment),
    baseline: baseline.performance
      ? performanceMetrics(baseline.performance)
      : null,
    proposed: proposed.performance
      ? performanceMetrics(proposed.performance)
      : null,
    live: structuredClone(value) as EvaluationDTO,
  };
}
export function parseItem(value: unknown): Item {
  const row = requireFields(value, {
    item_id: "number",
    numeric_item_id: "number",
    name: "string",
    slot: "string",
    catalog_version: "string",
  });
  if (
    !Number.isSafeInteger(row.item_id) ||
    Number(row.item_id) <= 0 ||
    row.item_id !== row.numeric_item_id ||
    !slots.includes(uiSlot(row.slot) as Slot)
  )
    throw new Error("Invalid physical item identity");
  const ownership = requireFields(row.ownership, {
    status: "string",
    meaning: "string",
    quantity: "number",
  });
  const price = requireFields(row.price, {
    layer: "string",
    selection_reason: "string",
  });
  if (
    price.amount_gp !== null &&
    (typeof price.amount_gp !== "number" ||
      !Number.isSafeInteger(price.amount_gp) ||
      price.amount_gp < 0)
  )
    throw new Error("Invalid item price");
  const wear = requireFields(row.wear, {
    status: "string",
    requirements_complete: "boolean",
  });
  const equipment = requireFields(row.equipment, {
    id: "number",
    attack_speed: "number",
    two_handed: "boolean",
  });
  if (
    equipment.id !== row.item_id ||
    !strings(equipment.attack_styles) ||
    Object.values(object(equipment.bonuses)).some(
      (bonus) => typeof bonus !== "number" || !Number.isFinite(bonus),
    )
  )
    throw new Error("Invalid equipment metadata");
  if (
    !["owned", "unowned", "unknown"].includes(ownership.status as string) ||
    !["satisfied", "unsatisfied", "unknown"].includes(wear.status as string) ||
    typeof row.acquisition !== "string"
  )
    throw new Error("Invalid item observation status");
  if (
    row.support_status !== undefined &&
    (!["verified", "community_assumed", "unreviewed"].includes(
      String(row.support_status),
    ) ||
      !strings(row.support_assumptions) ||
      (row.support_status === "community_assumed" &&
        (!Array.isArray(row.support_assumptions) ||
          row.support_assumptions.length === 0)))
  )
    throw new Error("Invalid equipment support provenance");
  scans(ownership.container_scans);
  for (const key of [
    "selected_trade_at",
    "fetched_at",
    "provider",
    "source",
    "confidence",
    "policy",
  ]) {
    if (price[key] !== null && typeof price[key] !== "string")
      throw new Error(`Invalid price provenance: ${key}`);
  }
  if (
    !Array.isArray(ownership.sightings) ||
    !strings(row.limitations) ||
    !strings(row.acquisition_descriptions) ||
    !Array.isArray(wear.unmet)
  )
    throw new Error("Invalid item facts");
  for (const sighting of ownership.sightings)
    requireFields(sighting, {
      container: "string",
      quantity: "number",
      observed_at: "string",
      source: "string",
    });
  return {
    id: row.item_id as number,
    name: row.name as string,
    slot: uiSlot(row.slot) as Slot,
    owned: ownership.status === "unknown" ? null : ownership.status === "owned",
    price: price.amount_gp as number | null,
    requirement: `${row.support_status === "community_assumed" ? "Community-assumed � " : row.support_status === "verified" ? "Verified � " : ""}Eligibility: ${wear.status}${wear.requirements_complete ? "" : " · metadata incomplete"}`,
    facts: value as PhysicalItem,
  };
}
export function parseContext(value: unknown): GearContext {
  const row = requireFields(value, {
    api_version: "string",
    evaluated_at: "string",
    catalog_version: "string",
    model_version: "string",
    price_revision: "string",
  });
  if (row.api_version !== "gear-ui-v1" || !Array.isArray(row.items))
    throw new Error("Unsupported Gear API response");
  if (row.data_source !== undefined && row.data_source !== null) {
    const source = requireFields(row.data_source, {
      label: "string",
      fetched_at: "string",
    });
    if (!Number.isFinite(Date.parse(source.fetched_at as string)))
      throw new Error("Invalid data retrieval timestamp");
  }
  const projection = requireFields(row.current_equipment, { status: "string" });
  if (!["observed", "partial", "unknown"].includes(projection.status as string))
    throw new Error("Invalid equipment status");
  const observations = object(projection.slots),
    equipment = object(projection.equipment);
  for (const slot of slots) {
    const key = apiSlot(slot);
    const fact = object(observations[key]);
    if (
      !["observed", "empty", "unknown", "ambiguous"].includes(
        fact.status as string,
      ) ||
      !Array.isArray(fact.candidate_item_ids) ||
      fact.candidate_item_ids.some(
        (id) => !Number.isSafeInteger(id) || id <= 0,
      ) ||
      (fact.item_id !== null && !Number.isSafeInteger(fact.item_id))
    )
      throw new Error("Invalid slot observation");
    if (
      equipment[key] !== undefined &&
      (!Number.isSafeInteger(equipment[key]) ||
        fact.status !== "observed" ||
        fact.item_id !== equipment[key])
    )
      throw new Error("Invalid equipment assignment");
  }
  if (
    !strings(projection.warnings) ||
    !Array.isArray(projection.unmapped_item_ids)
  )
    throw new Error("Invalid equipment coverage");
  scans(row.container_scans);
  object(row.capabilities);
  if (row.account !== null) {
    const account = requireFields(row.account, {
      player_id: "number",
      username: "string",
      snapshot_id: "string",
    });
    for (const skill of Object.values(object(account.skills)))
      requireFields(skill, {
        level: "number",
        source: "string",
        observed_at: "string",
      });
    if (
      account.last_sync_at !== null &&
      typeof account.last_sync_at !== "string"
    )
      throw new Error("Invalid account synchronization timestamp");
  }
  const dto = structuredClone(value) as ContextDTO;
  dto.current_equipment.slots.ammo = dto.current_equipment.slots.ammunition;
  if (dto.current_equipment.equipment.ammunition !== undefined)
    dto.current_equipment.equipment.ammo =
      dto.current_equipment.equipment.ammunition;
  delete dto.current_equipment.equipment.ammunition;

  return {
    playerId: dto.account ? `live:${dto.account.player_id}` : "live:no-account",
    displayName: dto.account?.username ?? "No synchronized account",
    snapshotId: dto.account?.snapshot_id ?? "",
    observedAt: dto.account?.last_sync_at ?? "Never synchronized",
    equipment: {
      ...emptyEquipment(),
      ...dto.current_equipment.equipment,
    } as Equipment,
    items: row.items.map(parseItem),
    equipmentStatus: dto.current_equipment.status,
    source: "live",
    live: dto,
  };
}
export class HttpGearClient implements GearClient {
  constructor(
    private base = "/ui-api/gear",
    private transport: typeof fetch = fetch.bind(globalThis),
  ) {}
  private async request(path: string): Promise<unknown> {
    const response = await this.transport(`${this.base}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(
        response.status === 404
          ? "Physical item metadata unavailable"
          : `Gear request failed (${response.status})`,
      );
    return response.json();
  }
  async potionTimeline(
    result: OptimizationReply,
    solution: JointSolutionDTO,
    signal: AbortSignal,
  ): Promise<PotionTimeline> {
    if (result.source !== "live" || !result.live)
      throw new Error(
        "Potion timelines require an accepted live configuration",
      );
    const roles = result.scenario.request.roles.filter((role) => !role.utility);
    const loadouts = Object.fromEntries(
      roles.map((role) => {
        const loadout = solution.loadouts[role.id];
        const option =
          loadout?.combat_option ?? loadout?.performance.combat_option;
        if (!loadout || !option)
          throw new Error(
            "Selected combat option is unavailable; rerun optimization",
          );
        return [
          role.id,
          {
            equipment: loadout.equipment,
            combat_option: option,
            selected_prayer_ids: loadout.selected_prayer_ids ?? [],
          },
        ];
      }),
    );
    const runId = result.live.run_id ?? result.live.result?.run_id;
    const storedPoint = result.live.result?.objective_frontiers
      ?.flatMap((group) => group.points)
      .find((point) => sameValue(point.solution, solution));
    const parsedPoint = result.solutions?.find(
      (point) => point.live === solution || sameValue(point.live, solution),
    );
    const manifest =
      result.live.objective_run ?? result.live.result?.objective_run;
    const selectedId = sameValue(
      result.live.result?.selected_solution,
      solution,
    )
      ? manifest?.selected_solution_id
      : undefined;
    const configurationAlias =
      parsedPoint?.id ??
      (sameValue(result.unrestricted?.live, solution) ||
      sameValue(result.live.result?.unrestricted, solution)
        ? "unrestricted"
        : undefined);
    const storedId =
      storedPoint?.solution_id ??
      storedPoint?.id ??
      (configurationAlias &&
        manifest?.solution_references?.[configurationAlias]) ??
      selectedId ??
      parsedPoint?.id.replace(/^discipline-(melee|ranged|magic)-/, "");
    if (
      result.scenario.request.objectives !== undefined &&
      (!runId ||
        !storedId ||
        storedId === "best-found" ||
        storedId.startsWith("curve-") ||
        storedId === "unrestricted")
    )
      throw new Error(
        "Select an archived objective configuration before requesting its timeline.",
      );
    const response = await this.transport(`${this.base}/potion-timelines`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        result.scenario.request.objectives !== undefined
          ? { run_id: runId, solution_id: storedId }
          : {
              scenario: result.live.scenario,
              selected_potion_ids: solution.potions?.selected_ids ?? [],
              loadouts,
              expected_catalog_version: result.catalogVersion,
              expected_model_version: result.modelVersion,
            },
      ),
    });
    const body = await response.json();
    if (!response.ok) {
      const error = object(object(body).error);
      throw new GearApiError(
        typeof error.message === "string"
          ? error.message
          : `Potion timeline failed (${response.status})`,
        String(error.code ?? "potion_timeline_failed"),
      );
    }
    return parsePotionTimeline(
      body,
      result,
      solution,
      roles.map((role) => role.id),
    );
  }
  async getContext() {
    return parseContext(await this.request("/context"));
  }
  async getItem(id: number, supportPolicy: SupportPolicy = "verified_only") {
    const item = parseItem(
      await this.request(`/items/${id}?support_policy=${supportPolicy}`),
    );
    if (item.id !== id)
      throw new Error("Item response identity does not match request");
    return item;
  }
  async browseItems(
    slot: Slot,
    query: string,
    offset = 0,
    supportPolicy: SupportPolicy = "verified_only",
  ): Promise<ItemPage> {
    const row = object(
      await this.request(
        `/items?${new URLSearchParams({ slot: apiSlot(slot), q: query, offset: String(offset), limit: "20", support_policy: supportPolicy })}`,
      ),
    );
    if (
      !Array.isArray(row.items) ||
      typeof row.total !== "number" ||
      !(row.next_offset === null || Number.isSafeInteger(row.next_offset))
    )
      throw new Error("Invalid item page");
    return {
      items: row.items.map(parseItem),
      total: row.total,
      nextOffset: row.next_offset as number | null,
    };
  }
  async alternatives(slot: Slot, _scenario: Scenario) {
    return (
      await this.browseItems(slot, "", 0, _scenario.request.support_policy)
    ).items;
  }
  async optimize(
    scenario: Scenario,
    signal: AbortSignal,
    onProgress?: (progress: OptimizationProgress) => void,
    progressId: string | null = onProgress ? createProgressId() : null,
  ): Promise<OptimizationReply> {
    const submitted = structuredClone(scenario);
    const stop =
      progressId && onProgress
        ? pollOptimizationProgress(
            this.base,
            progressId,
            signal,
            this.transport,
            onProgress,
          )
        : () => {};
    try {
      const response = await this.transport(
        `${this.base}/optimizations${progressId ? `?progress_id=${progressId}` : ""}`,
        {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(optimizationRequest(submitted)),
        },
      );
      const body = await response.json();
      if (!response.ok) {
        const error = object(object(body).error);
        const fields = Array.isArray(error.fields)
          ? error.fields
              .map((f) => {
                const row = object(f);
                return `${row.field ?? row.path ?? "scenario"}: ${row.message}`;
              })
              .join("; ")
          : "";
        throw new GearApiError(
          `${typeof error.message === "string" ? error.message : `Optimization failed (${response.status})`}${fields ? ` · ${fields}` : ""}`,
          String(error.code ?? "optimization_failed"),
          response.status,
          typeof error.phase === "string" ? error.phase : undefined,
        );
      }
      return parseOptimization(body, submitted);
    } finally {
      stop();
    }
  }
  async evaluate(
    result: OptimizationReply,
    solution: string,
    role: string,
    equipment: Equipment,
    signal?: AbortSignal,
  ): Promise<Trial> {
    if (result.scenario.request.roles.length !== 1)
      throw new Error(
        "Exact multi-role manual evaluation is unavailable. Edit constraints and reoptimize the joint scenario.",
      );
    const baseline = result.solutions
      .find((s) => s.id === solution)
      ?.loadouts.find((l) => l.roleId === role)?.equipment;
    if (result.source !== "live" || !result.live || !baseline)
      throw new Error(
        "Live evaluation requires an accepted live configuration",
      );
    const combatOption = result.solutions
      .find((s) => s.id === solution)
      ?.loadouts.find((l) => l.roleId === role)?.combatOption;
    const proposal = structuredClone(equipment);
    const response = await this.transport(`${this.base}/evaluations`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scenario: result.live.scenario,
        ...((result.scenario.request.potions?.mode ?? "disabled") !== "disabled"
          ? {
              selected_potion_ids:
                result.solutions.find((s) => s.id === solution)?.live?.potions
                  ?.selected_ids ?? [],
            }
          : {}),
        ...((result.scenario.request.roles.find((r) => r.id === role)?.prayers
          ?.mode ?? "disabled") !== "disabled"
          ? {
              selected_prayer_ids: {
                [role]:
                  result.solutions.find((s) => s.id === solution)?.live
                    ?.loadouts[role]?.selected_prayer_ids ??
                  result.solutions
                    .find((s) => s.id === solution)
                    ?.loadouts.find((l) => l.roleId === role)
                    ?.selectedPrayerIds ??
                  [],
              },
            }
          : {}),
        baseline_loadouts: { [role]: concreteEquipment(baseline) },
        proposed_loadouts: { [role]: concreteEquipment(proposal) },
        ...(combatOption
          ? {
              baseline_combat_options: { [role]: combatOption },
              ...(!result.scenario.request.roles[0].autoDiscipline
                ? { proposed_combat_options: { [role]: combatOption } }
                : {}),
            }
          : {}),
      }),
    });
    const body = await response.json();
    if (!response.ok) {
      const error = object(object(body).error),
        fields = Array.isArray(error.fields)
          ? error.fields
              .map((f) => {
                const row = object(f);
                return `${row.path ?? row.field ?? "scenario"}: ${row.message}`;
              })
              .join("; ")
          : "";
      throw new GearApiError(
        `${typeof error.message === "string" ? error.message : `Evaluation failed (${response.status})`}${fields ? ` · ${fields}` : ""}`,
        String(error.code ?? "evaluation_failed"),
      );
    }
    return parseEvaluation(body, result, solution, role, proposal);
  }
}
