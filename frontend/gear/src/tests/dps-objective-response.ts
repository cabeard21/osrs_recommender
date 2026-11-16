// Extend legacy UI examples with the metadata returned for live DPS-only runs.
// Nonempty objectives need explicit measurements in their own contract fixtures.
export function dpsObjectiveResponse<
  T extends {
    scenario: unknown;
    result: { selected_solution: object | null };
  },
>(body: T): T {
  const scenario = body.scenario as { objectives?: unknown };
  if (scenario.objectives === undefined) return body;
  if (!Array.isArray(scenario.objectives) || scenario.objectives.length)
    throw new Error("This response fixture supports DPS-only objectives.");
  const frontier_policy = {
    policy: "vector-pareto-v1",
    objective_count: 0,
    expansion_limit: 0,
    combat_reserve: 0,
    anchor_expansion_limit: 0,
    shared_assignment_limit: 0,
    complete_assignment_limit: 0,
    finalist_assignment_limit: 0,
    finalist_assignment_scope: "per_seed",
    finalist_total_assignment_limit: 0,
    finalist_seed_limit: 0,
    finalist_per_seed_limit: 0,
    beam_width: 256,
    archive: "exact-raw-complete-configurations",
    retention: "extremes-normalized-farthest-v1",
  };
  return {
    ...body,
    frontier_policy,
    result: {
      ...body.result,
      frontier_policy,
      objective_definitions: [],
      objective_frontiers: [],
      selected_solution: body.result.selected_solution && {
        ...body.result.selected_solution,
        objective_values: {},
      },
    },
  };
}
