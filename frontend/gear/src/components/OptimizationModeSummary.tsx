import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";

interface Refinement {
  triggered: boolean;
  assignment_attempts: number;
  work_budget_exhausted: boolean;
  objective_improvements: number;
  tie_improvements: number;
  baseline: {
    curve_solutions: (JointSolutionDTO | null)[];
    unrestricted: JointSolutionDTO | null;
  };
}
const signed = (n: number, digits = 0) =>
  `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;

export function OptimizationModeSummary({
  result,
  solution,
  actionLimit,
  unrestricted = false,
}: {
  result: OptimizationReply;
  solution?: JointSolutionDTO | null;
  actionLimit?: number;
  unrestricted?: boolean;
}) {
  const mode = result.scenario.request.optimization_mode ?? "fast";
  const refinement = result.live?.result.search.local_refinement as
    Refinement | undefined;
  const baseline = unrestricted
    ? refinement?.baseline?.unrestricted
    : refinement?.baseline?.curve_solutions[
        actionLimit ?? result.scenario.request.max_swaps
      ];
  const gain = solution && baseline ? solution.score - baseline.score : null;
  return (
    <section className="panel" aria-label="Optimization mode and refinement">
      <h2>{mode === "thorough" ? "Thorough" : "Fast"} optimization</h2>
      {result.source === "fixture" ? (
        <p>Authored fixture example; no additional search performed.</p>
      ) : mode === "fast" ? (
        <p>
          Existing bounded search · best configuration found. Global optimality
          is not guaranteed.
        </p>
      ) : (
        <>
          <p>
            {refinement && refinement.assignment_attempts > 0
              ? "Additional refinement performed."
              : refinement?.triggered
                ? "No additional complete assignments required for the valid incumbents."
                : "No valid incumbent available for additional refinement."}
          </p>
          <p>
            {refinement?.assignment_attempts ?? 0} extra complete assignments
            evaluated.
          </p>
          <p>
            {refinement?.work_budget_exhausted
              ? "Refinement cap reached; best valid configuration retained."
              : "Refinement cap not reached."}
          </p>
          {gain !== null && solution && baseline ? (
            <>
              <p>
                Weighted DPS improvement over preserved baseline:{" "}
                {signed(gain, 6)} ({baseline.score.toFixed(6)} →{" "}
                {solution.score.toFixed(6)}).
              </p>
              {gain === 0 && (
                <p>
                  No weighted-DPS improvement. Equal-DPS tie changes:{" "}
                  {refinement?.tie_improvements ?? 0} curve/unrestricted
                  replacements under the existing final ordering.
                </p>
              )}
              <p>
                Additional acquisition GP:{" "}
                {signed(solution.purchase_cost_gp - baseline.purchase_cost_gp)}{" "}
                GP · maximum actions:{" "}
                {signed(solution.maximum_actions - baseline.maximum_actions)} ·
                peak gear inventory:{" "}
                {signed(
                  solution.max_gear_inventory_slots -
                    baseline.max_gear_inventory_slots,
                )}{" "}
                slots.
              </p>
              <p>
                Selected requirements:{" "}
                {solution.purchase_cost_gp.toLocaleString()} GP additional
                acquisition · {solution.maximum_actions} maximum actions ·{" "}
                {solution.max_gear_inventory_slots} peak gear inventory slots.
              </p>
            </>
          ) : (
            <p>No feasible baseline/selected pair for objective comparison.</p>
          )}
          <p>
            Best configuration found within bounded search; global optimality is
            not guaranteed.
          </p>
        </>
      )}
    </section>
  );
}
