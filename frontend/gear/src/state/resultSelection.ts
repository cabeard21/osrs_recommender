import type {
  ObjectiveFrontierGroup,
  OptimizationReply,
} from "../api/contracts";

export function archiveRunId(result: OptimizationReply | null | undefined) {
  return result?.live?.run_id ?? result?.live?.result?.run_id;
}

export function isDisciplineSolution(id: string, discipline: string) {
  return (
    id.startsWith(`discipline-${discipline}-`) ||
    id.startsWith(`frontier-discipline-${discipline}-`)
  );
}

export function selectedObjectiveGroup(
  groups: readonly ObjectiveFrontierGroup[],
  id: string,
) {
  return groups.find((group) => {
    const groupId = group.id ?? group.group_id;
    return (
      group.points.some((point) => point.id === id) ||
      (!!groupId && id.startsWith(`${groupId}-`))
    );
  });
}

export function archiveGroups(result: OptimizationReply) {
  const raw = result.live?.result;
  return [
    ...(raw?.objective_frontiers ?? []),
    ...(raw?.discipline_results ?? []).flatMap(
      (branch) => branch.objective_frontiers ?? [],
    ),
  ];
}

export function resolveResultSelection(
  result: OptimizationReply,
  id: string,
  archiveGroupId?: string,
  archiveCap?: number | null,
) {
  const raw = result.live?.result;
  const group = archiveGroupId
    ? archiveGroups(result).find(
        (row) => (row.id ?? row.group_id) === archiveGroupId,
      )
    : undefined;
  const branch = raw?.discipline_results?.find(
    (row) =>
      isDisciplineSolution(id, row.discipline) ||
      (!!group && row.objective_frontiers?.includes(group)),
  );
  const scope = branch ?? raw;
  const curve = raw?.curve?.find((point) => id === `curve-${point.swap_limit}`);
  const parsed = result.solutions.find((solution) => solution.id === id);
  const defaultId = branch
    ? `discipline-${branch.discipline}-best-found`
    : "best-found";
  let selected = parsed?.live;
  if (curve) selected = curve.solution ?? undefined;
  else if (id === "unrestricted")
    selected = raw?.unrestricted ?? result.unrestricted?.live;
  else if (!selected && id === defaultId)
    selected = scope?.selected_solution ?? undefined;
  const selectedGroup =
    [
      ...(scope?.secondary_frontiers ?? []),
      ...(scope?.running_cost_frontiers ?? []),
    ].find((row) => row.points.some((point) => point.id === id)) ??
    selectedObjectiveGroup(scope?.objective_frontiers ?? [], id);
  const legacyCap = id.match(/(?:^|-)objective-(None|\d+)-/);
  let cap: number | null =
    curve?.swap_limit ?? result.scenario.request.max_swaps;
  if (group) cap = group.swap_limit;
  else if (archiveGroupId === undefined && archiveCap !== undefined)
    cap = archiveCap;
  else if (id === "unrestricted") cap = null;
  else if (selectedGroup) cap = selectedGroup.swap_limit;
  else if (legacyCap)
    cap = legacyCap[1] === "None" ? null : Number(legacyCap[1]);

  return { branch, cap, curve, parsed, selected };
}
