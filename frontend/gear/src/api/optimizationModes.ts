import type {
  OptimizationMode,
  OptimizationReply,
  WorkBudgetPolicy,
} from "./contracts";
import { sameValue, object, requireFields } from "./runtime";

export function workBudgetPolicy(
  mode: OptimizationMode = "fast",
): WorkBudgetPolicy {
  return {
    policy: mode === "thorough" ? "local-refinement-v1" : "baseline-v1",
    complete_assignment_limit: mode === "thorough" ? 2000 : 0,
    targeted_head_refinement: false,
  };
}

export function matchesOptimizationPolicy(
  a: OptimizationReply,
  b: OptimizationReply,
) {
  return (
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
) {
  const expected = workBudgetPolicy(mode);
  for (const row of [envelope, result]) {
    // Historical Fast-only transports are compatible; Thorough must identify itself.
    if (
      (row.optimization_mode !== undefined || mode === "thorough") &&
      row.optimization_mode !== mode
    )
      throw new Error("Optimization mode does not match the submitted request");
    if (
      (row.work_budget_policy !== undefined || mode === "thorough") &&
      !sameValue(row.work_budget_policy, expected)
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
  if (Number(row.assignment_attempts) > 2000)
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
