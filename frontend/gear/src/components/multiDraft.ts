import type { Draft, Role, Style } from "../api/contracts";
import { sameValue } from "../api/runtime";
import { newRole } from "../state/scenario";
import { effectiveRoleTarget } from "./RoleTargetEditor";

interface TemplateRole {
  style: Style;
  isUtility?: boolean;
}

export interface MultiTemplate {
  label: string;
  roles: TemplateRole[];
}

export const MULTI_TEMPLATES: MultiTemplate[] = [
  { label: "Melee + Mage", roles: [{ style: "melee" }, { style: "magic" }] },
  { label: "Range + Mage", roles: [{ style: "ranged" }, { style: "magic" }] },
  { label: "Melee + Range", roles: [{ style: "melee" }, { style: "ranged" }] },
  {
    label: "Tribrid",
    roles: [{ style: "melee" }, { style: "ranged" }, { style: "magic" }],
  },
  {
    label: "Main + spec weapon",
    roles: [{ style: "melee" }, { style: "melee", isUtility: true }],
  },
];

const STYLE_NAMES: Record<Style, string> = {
  melee: "Melee",
  ranged: "Ranged",
  magic: "Magic",
};

/**
 * Replaces the configurations with the template's, keeping the current
 * target so a template can be applied after choosing the encounter.
 */
export function applyMultiTemplate(
  draft: Draft,
  template: MultiTemplate,
): Draft {
  const source = draft.roles.find((role) => !role.utility) ?? draft.roles[0];
  const combatTarget = effectiveRoleTarget(source, draft);
  const roles: Role[] = template.roles.map((spec, index) => ({
    ...newRole(index + 1),
    name: spec.isUtility ? "Spec weapon" : STYLE_NAMES[spec.style],
    style: spec.style,
    stance: spec.style === "ranged" ? "rapid" : "accurate",
    combatTarget: structuredClone(combatTarget),
    targetSelection: source.targetSelection
      ? { ...source.targetSelection }
      : undefined,
    targetInputs: { ...source.targetInputs },
    ...(spec.isUtility ? { utility: true, parentRole: "role-1" } : {}),
  }));
  return {
    ...draft,
    roles,
    baseRole: roles[0].id,
    topology: "base",
    transitions: undefined,
    orderedRoles: undefined,
  };
}

const targetOf = (role: Role, draft: Draft) => ({
  target: effectiveRoleTarget(role, draft),
  selection: role.targetSelection?.key ?? null,
});

const scored = (draft: Draft) => draft.roles.filter((role) => !role.utility);

/** True when every scored configuration already uses `roleId`'s target. */
export function isTargetSharedByAll(draft: Draft, roleId: string): boolean {
  const source = draft.roles.find((role) => role.id === roleId);
  if (!source) return true;
  const expected = targetOf(source, draft);
  return scored(draft).every((role) =>
    sameValue(expected, targetOf(role, draft)),
  );
}

/** Copies `roleId`'s target, NPC selection and stat edits to every scored configuration. */
export function applyTargetToAll(draft: Draft, roleId: string): Draft {
  const source = draft.roles.find((role) => role.id === roleId);
  if (!source) return draft;
  const combatTarget = effectiveRoleTarget(source, draft);
  return {
    ...draft,
    roles: draft.roles.map((role) =>
      role.utility || role.id === roleId
        ? role
        : {
            ...role,
            combatTarget: structuredClone(combatTarget),
            targetSelection: source.targetSelection
              ? { ...source.targetSelection }
              : undefined,
            targetInputs: { ...source.targetInputs },
          },
    ),
  };
}

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
