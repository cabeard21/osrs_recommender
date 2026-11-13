import type {
  OptimizationMode,
  OptimizationReply,
  WorkBudgetPolicy,
  Scenario,
} from "./contracts";
import { sameValue, object, requireFields } from "./runtime";

export function workBudgetPolicy(
  mode: OptimizationMode = "fast",
): WorkBudgetPolicy {
  return {
    policy: mode === "thorough" ? "local-refinement-v1" : "baseline-v1",
    complete_assignment_limit: mode === "thorough" ? 10000 : 0,
    targeted_head_refinement: false,
  };
}

export function validateAssignmentDiagnostics(
  value: unknown,
  scenario: Scenario,
) {
  const selection = object(object(value).discipline_assignment_selection);
  const expected = scenario.request.roles
    .filter((role) => !role.utility)
    .reduce<string[]>(
      (keys, role) => {
        const disciplines = role.autoDiscipline
          ? ["melee", "ranged", "magic"].filter((discipline) =>
              (
                role.allowedDisciplines ?? ["melee", "ranged", "magic"]
              ).includes(discipline as import("./contracts").Style),
            )
          : [role.style];
        return keys.flatMap((key) =>
          disciplines.map(
            (discipline) => `${key}${key ? "/" : ""}${role.id}=${discipline}`,
          ),
        );
      },
      [""],
    );
  const branches = object(selection.branches);
  if (
    selection.policy !== "full-per-discipline-assignment-v1" ||
    selection.branch_count !== expected.length ||
    Object.keys(branches).length !== expected.length ||
    expected.some((key) => !Object.hasOwn(branches, key))
  )
    throw new Error("Incomplete Auto discipline assignment diagnostics");
  if (scenario.request.optimization_mode === "thorough")
    for (const key of expected)
      validateRefinementDiagnostics(
        object(branches[key]).local_refinement,
        scenario.request.max_swaps,
      );
}

export function matchesOptimizationPolicy(
  a: OptimizationReply,
  b: OptimizationReply,
) {
  return (
    sameValue(
      a.scenario.request.roles.map((role) => [
        role.id,
        role.onSlayerTask ?? false,
      ]),
      b.scenario.request.roles.map((role) => [
        role.id,
        role.onSlayerTask ?? false,
      ]),
    ) &&
    (a.scenario.request.fire_tome_pages ?? "burnt") ===
      (b.scenario.request.fire_tome_pages ?? "burnt") &&
    (a.scenario.request.support_policy ?? "verified_only") ===
      (b.scenario.request.support_policy ?? "verified_only") &&
    (a.scenario.request.optimization_mode ?? "fast") ===
      (b.scenario.request.optimization_mode ?? "fast") &&
    sameValue(
      a.live?.work_budget_policy ??
        workBudgetPolicy(a.scenario.request.optimization_mode),
      b.live?.work_budget_policy ??
        workBudgetPolicy(b.scenario.request.optimization_mode),
    )
  );
}

export function validateOptimizationPolicy(
  envelope: Record<string, unknown>,
  result: Record<string, unknown>,
  mode: OptimizationMode,
  disciplineCount = 1,
  assignmentCount?: number,
) {
  const expected = workBudgetPolicy(mode);
  for (const row of [envelope, result]) {
    if (assignmentCount !== undefined && row.work_budget_policy === undefined)
      throw new Error("Missing discipline assignment work budget policy");
    if (row.work_budget_policy !== undefined) {
      const policy = object(row.work_budget_policy);
      if (assignmentCount !== undefined) {
        if (
          policy.budget_scope !== "per_discipline_assignment" ||
          policy.discipline_assignment_count !== assignmentCount ||
          policy.discipline_count !== undefined
        )
          throw new Error("Invalid discipline assignment work budget policy");
      } else if (
        (policy.budget_scope !== undefined &&
          policy.budget_scope !== "per_discipline") ||
        (policy.discipline_count !== undefined &&
          policy.discipline_count !== disciplineCount) ||
        policy.discipline_assignment_count !== undefined ||
        (disciplineCount > 1 &&
          (policy.budget_scope !== "per_discipline" ||
            policy.discipline_count !== disciplineCount))
      )
        throw new Error("Invalid discipline work budget policy");
    }
    // Historical Fast-only transports are compatible; Thorough must identify itself.
    if (
      (row.optimization_mode !== undefined || mode === "thorough") &&
      row.optimization_mode !== mode
    )
      throw new Error("Optimization mode does not match the submitted request");
    if (
      (row.work_budget_policy !== undefined || mode === "thorough") &&
      !sameValue(
        row.work_budget_policy === undefined
          ? undefined
          : Object.fromEntries(
              Object.entries(object(row.work_budget_policy)).filter(
                ([key]) =>
                  ![
                    "budget_scope",
                    "discipline_count",
                    "discipline_assignment_count",
                  ].includes(key),
              ),
            ),
        expected,
      )
    )
      throw new Error(
        "Optimization work budget does not match the submitted mode",
      );
  }
}

export function validateRefinementDiagnostics(
  value: unknown,
  maxActions: number,
) {
  const row = requireFields(value, {
    triggered: "boolean",
    assignment_attempts: "number",
    work_budget_exhausted: "boolean",
    objective_improvements: "number",
    tie_improvements: "number",
  });
  for (const key of [
    "assignment_attempts",
    "objective_improvements",
    "tie_improvements",
  ])
    if (!Number.isSafeInteger(row[key]) || Number(row[key]) < 0)
      throw new Error("Invalid refinement work diagnostics");
  if (Number(row.assignment_attempts) > 10000)
    throw new Error("Invalid refinement assignment cap");
  const baseline = object(row.baseline);
  if (
    !Array.isArray(baseline.curve_solutions) ||
    baseline.curve_solutions.length !== maxActions + 1
  )
    throw new Error("Invalid preserved refinement baseline");
  for (const solution of [...baseline.curve_solutions, baseline.unrestricted]) {
    if (solution === null) continue;
    const before = requireFields(solution, {
      score: "number",
      purchase_cost_gp: "number",
      maximum_actions: "number",
      max_gear_inventory_slots: "number",
    });
    if (
      !Number.isFinite(before.score) ||
      [
        before.purchase_cost_gp,
        before.maximum_actions,
        before.max_gear_inventory_slots,
      ].some((n) => !Number.isSafeInteger(n) || Number(n) < 0)
    )
      throw new Error("Invalid preserved refinement solution");
  }
}
