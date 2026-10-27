import type { Draft } from "../api/contracts";

export function removeMultiRole(draft: Draft, roleId: string) {
  const role = draft.roles.find((candidate) => candidate.id === roleId);
  if (!role || draft.roles.length <= 2)
    throw new Error("Multi requires at least two configurations.");
  if (
    draft.roles.some(
      (candidate) => candidate.utility && candidate.parentRole === roleId,
    )
  )
    throw new Error(
      "Remove or reparent dependent utility configurations first.",
    );
  const roles = draft.roles.filter((candidate) => candidate.id !== roleId);
  const transitions = (draft.transitions ?? []).filter(
    ([from, to]) => from !== roleId && to !== roleId,
  );
  const orderedRoles = (draft.orderedRoles ?? []).filter((id) => id !== roleId);
  const edgesRemoved = (draft.transitions?.length ?? 0) - transitions.length;
  const phasesRemoved = (draft.orderedRoles?.length ?? 0) - orderedRoles.length;
  const baseChanged = draft.baseRole === roleId;
  return {
    draft: {
      ...draft,
      roles,
      transitions,
      orderedRoles,
      baseRole: baseChanged ? roles[0].id : draft.baseRole,
    },
    notice: `Removed ${role.name}: ${edgesRemoved} directed transition(s) and ${phasesRemoved} ordered phase(s) removed.${baseChanged ? ` Base configuration changed to ${roles[0].name}.` : ""} Review transition settings before running again.`,
  };
}

export function nextRoleIndex(draft: Draft) {
  let index = 1;
  while (draft.roles.some((role) => role.id === `role-${index}`)) index += 1;
  return index;
}
