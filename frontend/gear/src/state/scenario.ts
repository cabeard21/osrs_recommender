import type {
  Draft,
  GearContext,
  OptimizationReply,
  Scenario,
  Slot,
  Trial,
  Equipment,
  Workspace,
} from "../api/contracts";
import { secondaryPriorities } from "../api/secondaryPriorities";
export const newRole = (index: number) => ({
  id: `role-${index}`,
  name: `Configuration ${index}`,
  style: (index === 2 ? "ranged" : "melee") as "melee" | "ranged" | "magic",
  attackType: "slash" as const,
  stance: "accurate",
  spell: "fire_strike",
  weight: "1",
  locks: {},
});
export const newDraft = (): Draft => ({
  secondaryPriority: "default",
  target: "Custom ordinary-attack target",
  defence: "1",
  budget: "0",
  mode: "usable",
  roles: [newRole(1)],
  maxActions: "8",
  supplies: "12",
  topology: "base",
  baseRole: "role-1",
  exclusions: [],
  assumptions: { attack: "", quest: false, acquired: "" },
});
export function normalize(
  draft: Draft,
  snapshotId: string,
  live = false,
): Scenario {
  if (
    !secondaryPriorities.some(
      ([priority]) => priority === (draft.secondaryPriority ?? "default"),
    )
  )
    throw new Error("Choose a valid secondary priority.");
  const integer = (value: string, name: string, min: number, max: number) => {
    const n = Number(value);
    if (!value.trim() || !Number.isSafeInteger(n) || n < min || n > max)
      throw new Error(`${name} must be a whole number from ${min} to ${max}.`);
    return n;
  };
  const roles = draft.roles.map((r) => {
    const role = { ...structuredClone(r), weight: Number(r.weight) };
    if (role.combatTarget) {
      for (const [key, value] of Object.entries(role.targetInputs ?? {})) {
        const optional = [
          "ranged_light",
          "ranged_standard",
          "ranged_heavy",
          "damage_cap",
        ].includes(key);
        if (optional && !value.trim()) {
          delete role.combatTarget[key];
          continue;
        }
        const n = Number(value);
        const min =
          key.startsWith("bonuses.") || key.startsWith("ranged_")
            ? -64
            : key === "damage_cap"
              ? 1
              : 0;
        if (
          !value.trim() ||
          !Number.isSafeInteger(n) ||
          n < min ||
          n >
            (key === "weakness_percent"
              ? 1000
              : key === "damage_cap"
                ? Number.MAX_SAFE_INTEGER
                : 10000)
        )
          throw new Error(
            `${role.name} target ${key} requires a valid whole number.`,
          );
        if (key.startsWith("bonuses."))
          role.combatTarget.bonuses[key.slice(8)] = n;
        else role.combatTarget[key] = n;
      }
      if (
        !role.combatTarget.name.trim() ||
        !Number.isSafeInteger(role.combatTarget.defence_level) ||
        !Number.isSafeInteger(role.combatTarget.magic_level)
      )
        throw new Error(`${role.name} target is incomplete.`);
    }
    return role;
  });
  if (
    roles.length < 1 ||
    roles.length > 4 ||
    new Set(roles.map((r) => r.id)).size !== roles.length
  )
    throw new Error("Configure one through four roles with unique IDs.");
  if (
    draft.roles.some((r) => !r.weight.trim()) ||
    roles.some(
      (r) => !Number.isFinite(r.weight) || r.weight < 0 || r.weight > 1000000,
    ) ||
    !roles.some((r) => !r.utility && r.weight > 0)
  )
    throw new Error(
      "Active-time weights must be finite numbers from 0 to 1000000, with a positive scored role.",
    );
  const ids = new Set(roles.map((r) => r.id));
  if (!ids.has(draft.baseRole))
    throw new Error("Base configuration must reference a configured role.");
  for (const role of roles) {
    const stances =
      role.style === "melee"
        ? ["accurate", "aggressive", "controlled", "defensive"]
        : role.style === "ranged"
          ? ["accurate", "rapid", "longrange"]
          : ["accurate", "defensive"];
    if (!role.utility && !stances.includes(role.stance))
      throw new Error(
        `${role.name} attack stance is unsupported for its discipline.`,
      );
    if (
      role.combatTarget &&
      ([role.combatTarget.defence_level, role.combatTarget.magic_level].some(
        (n) => !Number.isSafeInteger(n) || n < 0 || n > 10000,
      ) ||
        Object.values(role.combatTarget.bonuses).some(
          (n) => !Number.isSafeInteger(n),
        ))
    )
      throw new Error(`${role.name} target configuration is invalid.`);
    if (
      role.utility &&
      (!role.parentRole ||
        !roles.some(
          (r) => r.id === role.parentRole && !r.utility && r.id !== role.id,
        ) ||
        !role.locks.weapon)
    )
      throw new Error(
        "Utility configuration requires an ordinary parent role and a weapon lock.",
      );
    if (
      Object.entries(role.locks).some(
        ([slot, id]) =>
          slot in (draft.globalLocks ?? {}) &&
          draft.globalLocks?.[slot as Slot] !== id,
      )
    )
      throw new Error("Conflicting global and role locks.");
  }
  if (!draft.target.trim() || roles.some((r) => !r.name.trim()))
    throw new Error("Target and configuration names are required.");
  if (
    roles.some((r) =>
      Object.values(r.locks).some(
        (id) => id !== null && draft.exclusions.includes(id),
      ),
    )
  )
    throw new Error(
      "A locked item is excluded. Unlock it or remove the exclusion.",
    );
  if (
    Object.values(draft.globalLocks ?? {}).some(
      (id) => id !== null && id !== undefined && draft.exclusions.includes(id),
    )
  )
    throw new Error("A globally locked item is excluded.");
  const hypothetical =
    draft.assumptions.attack !== "" ||
    draft.assumptions.quest ||
    draft.assumptions.acquired !== "";
  if (hypothetical && draft.mode !== "future")
    throw new Error("Select hypothetical access to submit assumptions.");
  const assumed = draft.assumptions.acquired.trim()
    ? draft.assumptions.acquired
        .split(",")
        .map((v) => integer(v.trim(), "Assumed item ID", 1, 100000))
    : [];
  const skills: Record<string, number> = {};
  for (const entry of (draft.assumptions.skillLevels ?? "")
    .split(",")
    .filter((v) => v.trim())) {
    const [skill, level, extra] = entry.trim().split("=");
    if (!skill || !level || extra)
      throw new Error("Assumed skills use skill=level, separated by commas.");
    skills[skill.trim()] = integer(level.trim(), "Assumed skill", 1, 99);
  }
  const quests = (draft.assumptions.completedQuests ?? "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  if ((Object.keys(skills).length || quests.length) && draft.mode !== "future")
    throw new Error("Select hypothetical access to submit assumptions.");
  if (
    draft.exclusions.length > 500 ||
    draft.exclusions.some((id) => !Number.isSafeInteger(id) || id <= 0)
  )
    throw new Error(
      "Exclusions require at most 500 positive physical item IDs.",
    );
  if (live && draft.assumptions.quest)
    throw new Error(
      "Replace the restored demo quest assumption with explicit quest IDs.",
    );
  const edges: [string, string][] =
    draft.topology === "base"
      ? roles
          .filter((r) => r.id !== draft.baseRole && !r.utility)
          .flatMap(
            (r) =>
              [
                [draft.baseRole, r.id],
                [r.id, draft.baseRole],
              ] as [string, string][],
          )
      : draft.topology === "explicit"
        ? structuredClone(draft.transitions ?? [])
        : [];
  const ordered =
    draft.topology === "ordered"
      ? [...(draft.orderedRoles ?? roles.map((r) => r.id))]
      : [];
  if (
    edges.length > 16 ||
    edges.some(([a, b]) => !ids.has(a) || !ids.has(b) || a === b)
  )
    throw new Error(
      "Directed transitions must reference different configured roles (maximum 16).",
    );
  if (draft.topology === "explicit" && !edges.length)
    throw new Error("Choose at least one directed transition.");
  if (
    ordered.length > 100 ||
    (draft.topology === "ordered" && ordered.length < 2) ||
    ordered.some((id) => !ids.has(id))
  )
    throw new Error(
      "Ordered phases must reference configured roles, with two through 100 phases.",
    );
  return {
    objective: "weighted_dps",
    request: {
      secondary_priority: draft.secondaryPriority ?? "default",
      roles,
      target: {
        name: draft.target,
        defence: integer(draft.defence, "Target defence", 0, 1000),
        ...(draft.combatTarget
          ? { definition: structuredClone(draft.combatTarget) }
          : {}),
      },
      budget_gp: integer(draft.budget, "Budget", 0, 2147483647),
      mode: draft.mode,
      max_swaps: integer(draft.maxActions, "Equipment actions", 0, 12),
      reserved_supply_slots: integer(draft.supplies, "Supply slots", 0, 28),
      transitions: edges,
      base_role: draft.baseRole,
      locks: structuredClone(draft.globalLocks ?? {}),
      ...(ordered.length ? { ordered_roles: ordered, loop: !!draft.loop } : {}),
      excluded_item_ids: [...draft.exclusions],
      skill_overrides: draft.assumptions.attack
        ? {
            ...skills,
            attack: integer(draft.assumptions.attack, "Assumed Attack", 1, 99),
          }
        : skills,
      quest_overrides: {
        ...Object.fromEntries(quests.map((id) => [id, "complete"])),
        ...(draft.assumptions.quest ? { "fixture-quest": "complete" } : {}),
      },
      assumed_item_ids: assumed,
      expected_snapshot_id: snapshotId,
    },
  };
}
export interface WorkspaceState {
  draft: Draft;
  revision: number;
  submitted: Scenario | null;
  result: OptimizationReply | null;
  previous: OptimizationReply | null;
  trial: Trial | null;
  trialGeneration: number;
  trialPending: boolean;
  trialError: string | null;
  trialRequest: {
    equipment: Equipment;
    resultFingerprint: string;
    solutionId: string;
    roleId: string;
    slot: Slot | null;
    revision: number;
  } | null;
  generation: number;
  pending: boolean;
  error: string | null;
  outdated: boolean;
  activeRole: string;
  slot: Slot | null;
  solutionId: string;
  view: "side" | "interactive";
  comparisonRoles: [string, string];
  selectedTransition: string;
}
const workspace = (): WorkspaceState => ({
  draft: newDraft(),
  revision: 0,
  submitted: null,
  result: null,
  previous: null,
  trial: null,
  trialGeneration: 0,
  trialPending: false,
  trialError: null,
  trialRequest: null,
  generation: 0,
  pending: false,
  error: null,
  outdated: false,
  activeRole: "role-1",
  slot: null,
  solutionId: "best-found",
  view: "side",
  comparisonRoles: ["role-1", "role-2"],
  selectedTransition: "",
});
export interface State {
  context: GearContext | null;
  mode: Workspace;
  multiSeeded: boolean;
  single: WorkspaceState;
  multi: WorkspaceState;
}
export const initialState = (): State => ({
  context: null,
  mode: "single",
  multiSeeded: false,
  single: workspace(),
  multi: workspace(),
});
export type Action =
  | { type: "context"; context: GearContext }
  | { type: "navigate"; mode: Workspace }
  | { type: "use-single-in-multi" }
  | {
      type: "restore";
      drafts: { single: Draft; multi: Draft; multiSeeded: boolean };
    }
  | { type: "edit"; mode: Workspace; draft: Draft }
  | { type: "start"; mode: Workspace; scenario: Scenario; generation: number }
  | {
      type: "success";
      mode: Workspace;
      generation: number;
      result: OptimizationReply;
    }
  | { type: "error"; mode: Workspace; generation: number; error: string }
  | { type: "cancel"; mode: Workspace }
  | {
      type: "ui";
      mode: Workspace;
      patch: Partial<
        Pick<
          WorkspaceState,
          | "activeRole"
          | "slot"
          | "view"
          | "solutionId"
          | "comparisonRoles"
          | "selectedTransition"
        >
      >;
    }
  | { type: "trial"; mode: Workspace; trial: Trial | null }
  | {
      type: "trial-start";
      mode: Workspace;
      generation: number;
      equipment: Equipment;
    }
  | { type: "trial-success"; mode: Workspace; generation: number; trial: Trial }
  | { type: "trial-error"; mode: Workspace; generation: number; error: string }
  | { type: "trial-cancel"; mode: Workspace };
export function contextIdentity(context: GearContext | null) {
  return JSON.stringify([
    context?.snapshotId,
    context?.live?.catalog_version,
    context?.live?.model_version,
    context?.live?.price_revision,
  ]);
}
function clearedTrial(current: WorkspaceState) {
  return {
    trial: null,
    trialPending: false,
    trialError: null,
    trialRequest: null,
    trialGeneration: current.trialGeneration + 1,
  };
}
export function reducer(state: State, action: Action): State {
  if (action.type === "context")
    return {
      ...state,
      context: action.context,
      ...Object.fromEntries(
        (["single", "multi"] as const).map((mode) => [
          mode,
          {
            ...state[mode],
            ...(state.context &&
            contextIdentity(state.context) !== contextIdentity(action.context)
              ? clearedTrial(state[mode])
              : {}),
            ...(state.context &&
            contextIdentity(state.context) !== contextIdentity(action.context)
              ? {
                  generation: state[mode].generation + 1,
                  pending: false,
                  error: state[mode].pending
                    ? "Account changed during optimization. Refresh and rerun."
                    : state[mode].error,
                }
              : {}),
            outdated:
              state[mode].outdated ||
              (!!state[mode].result &&
                (state[mode].result.snapshotId !== action.context.snapshotId ||
                  (!!action.context.live &&
                    (state[mode].result.catalogVersion !==
                      action.context.live.catalog_version ||
                      state[mode].result.modelVersion !==
                        action.context.live.model_version ||
                      state[mode].result.priceRevision !==
                        action.context.live.price_revision)))),
          },
        ]),
      ),
    };
  if (action.type === "use-single-in-multi") {
    const loadout = state.single.result?.solutions.find(
      (s) => s.id === state.single.solutionId,
    )?.loadouts[0];
    if (!loadout) return state;
    const draft = structuredClone(
      state.multiSeeded ? state.multi.draft : state.single.draft,
    );
    const sourceScenario = state.single.result!.scenario.request;
    const sourceRole = sourceScenario.roles[0];
    draft.roles[0] = {
      ...sourceRole,
      weight: String(state.single.result!.scenario.request.roles[0].weight),
      id: "role-1",
      name: "Single result (locked)",
      locks: structuredClone(loadout.equipment),
      combatTarget: structuredClone(
        sourceRole.combatTarget ??
          sourceScenario.target.definition ?? {
            name: sourceScenario.target.name,
            defence_level: sourceScenario.target.defence,
            magic_level: 1,
            bonuses: {},
          },
      ),
      targetInputs: {},
    };
    if (draft.roles.length === 1) draft.roles.push(newRole(2));
    return {
      ...state,
      mode: "multi",
      multiSeeded: true,
      single: { ...state.single, ...clearedTrial(state.single) },
      multi: {
        ...state.multi,
        draft,
        revision: state.multi.revision + 1,
        generation: state.multi.generation + 1,
        pending: false,
        outdated: !!state.multi.result,
        ...clearedTrial(state.multi),
      },
    };
  }
  if (action.type === "restore")
    return {
      ...state,
      single: { ...state.single, draft: action.drafts.single },
      multi: { ...state.multi, draft: action.drafts.multi },
      multiSeeded: action.drafts.multiSeeded,
    };
  if (action.type === "navigate") {
    if (action.mode === "multi" && !state.multiSeeded) {
      const draft = structuredClone(state.single.draft);
      draft.roles.push(newRole(2));
      return {
        ...state,
        mode: "multi",
        multiSeeded: true,
        single: { ...state.single, ...clearedTrial(state.single) },
        multi: { ...state.multi, draft },
      };
    }
    return {
      ...state,
      mode: action.mode,
      [state.mode]: {
        ...state[state.mode],
        ...clearedTrial(state[state.mode]),
      },
    };
  }
  const current = state[action.mode];
  let next = current;
  switch (action.type) {
    case "edit":
      next = {
        ...current,
        draft: structuredClone(action.draft),
        revision: current.revision + 1,
        generation: current.generation + 1,
        pending: false,
        error: null,
        outdated: !!current.result,
        ...clearedTrial(current),
      };
      break;
    case "start":
      next = {
        ...current,
        submitted: structuredClone(action.scenario),
        generation: action.generation,
        pending: true,
        error: null,
        ...clearedTrial(current),
      };
      break;
    case "success":
      if (current.generation !== action.generation || !current.pending)
        return state;
      if (
        (current.submitted?.request.secondary_priority ?? "default") !==
        (action.result.scenario.request.secondary_priority ?? "default")
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error: "Secondary priority changed; rerun the selected priority.",
          },
        };
      if (
        state.context &&
        state.context.snapshotId !== action.result.snapshotId
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            outdated: !!current.result,
            error:
              "Account context changed during the run. Re-run with the current context.",
          },
        };
      next = {
        ...current,
        pending: false,
        previous: current.result,
        result: structuredClone(action.result),
        submitted: structuredClone(action.result.scenario),
        outdated:
          !!state.context?.live &&
          (action.result.catalogVersion !==
            state.context.live.catalog_version ||
            action.result.modelVersion !== state.context.live.model_version ||
            action.result.priceRevision !== state.context.live.price_revision),
        ...clearedTrial(current),
        solutionId:
          action.result.selectedSolutionId ??
          action.result.solutions[0]?.id ??
          "best-found",
        activeRole: action.result.scenario.request.roles[0].id,
        comparisonRoles: [
          action.result.scenario.request.roles[0].id,
          action.result.scenario.request.roles[1]?.id ??
            action.result.scenario.request.roles[0].id,
        ],
        selectedTransition: "",
      };
      break;
    case "error":
      if (current.generation !== action.generation) return state;
      next = { ...current, pending: false, error: action.error };
      break;
    case "cancel":
      next = {
        ...current,
        pending: false,
        generation: current.generation + 1,
        ...clearedTrial(current),
      };
      break;
    case "ui":
      next = {
        ...current,
        ...action.patch,
        ...((action.patch.solutionId !== undefined &&
          action.patch.solutionId !== current.solutionId) ||
        (action.patch.activeRole !== undefined &&
          action.patch.activeRole !== current.activeRole) ||
        (action.patch.slot !== undefined && action.patch.slot !== current.slot)
          ? clearedTrial(current)
          : {}),
      };
      break;
    case "trial":
      if (
        action.trial &&
        (current.pending ||
          current.outdated ||
          action.trial.resultFingerprint !== current.result?.fingerprint ||
          action.trial.source !== current.result?.source ||
          action.trial.solutionId !== current.solutionId ||
          action.trial.roleId !== current.activeRole)
      )
        return state;
      next = { ...current, ...clearedTrial(current), trial: action.trial };
      break;
    case "trial-start":
      if (
        !current.result ||
        current.outdated ||
        current.pending ||
        current.slot === null ||
        action.generation <= current.trialGeneration
      )
        return state;
      next = {
        ...current,
        trial: null,
        trialError: null,
        trialPending: true,
        trialGeneration: action.generation,
        trialRequest: {
          equipment: structuredClone(action.equipment),
          resultFingerprint: current.result.fingerprint,
          solutionId: current.solutionId,
          roleId: current.activeRole,
          slot: current.slot,
          revision: current.revision,
        },
      };
      break;
    case "trial-success": {
      const request = current.trialRequest;
      if (
        !current.trialPending ||
        current.trialGeneration !== action.generation ||
        !request ||
        current.outdated ||
        current.pending ||
        request.resultFingerprint !== current.result?.fingerprint ||
        request.solutionId !== current.solutionId ||
        request.roleId !== current.activeRole ||
        request.slot !== current.slot ||
        request.revision !== current.revision ||
        action.trial.resultFingerprint !== request.resultFingerprint ||
        action.trial.solutionId !== request.solutionId ||
        action.trial.roleId !== request.roleId ||
        Object.entries(request.equipment).some(
          ([slot, id]) => action.trial.equipment[slot as Slot] !== id,
        ) ||
        action.trial.source !== current.result?.source
      )
        return state;
      next = {
        ...current,
        trialPending: false,
        trialRequest: null,
        trial: structuredClone(action.trial),
      };
      break;
    }
    case "trial-error":
      if (
        !current.trialPending ||
        current.trialGeneration !== action.generation
      )
        return state;
      next = {
        ...current,
        trialPending: false,
        trialRequest: null,
        trialError: action.error,
      };
      break;
    case "trial-cancel":
      next = { ...current, ...clearedTrial(current) };
      break;
  }
  return { ...state, [action.mode]: next };
}
const version = 2;
export const storageKey = (player: string) =>
  `gear-drafts-v${version}:${player}`;
export function saveDrafts(state: State, storage: Storage) {
  if (!state.context) return;
  try {
    storage.setItem(
      storageKey(state.context.playerId),
      JSON.stringify({
        version,
        single: state.single.draft,
        multi: state.multi.draft,
        multiSeeded: state.multiSeeded,
      }),
    );
  } catch {
    /* Storage can be disabled; in-memory navigation still works. */
  }
}
export function readDrafts(
  player: string,
  storage: Storage,
): { single: Draft; multi: Draft; multiSeeded: boolean } | null {
  try {
    const data = JSON.parse(
      storage.getItem(storageKey(player)) ??
        storage.getItem(`gear-drafts-v1:${player}`) ??
        "null",
    );
    if (![1, version].includes(data?.version)) return null;
    for (const draft of [data.single, data.multi]) {
      if (draft.secondaryPriority === undefined)
        draft.secondaryPriority = "default";
      if (
        !secondaryPriorities.some(
          ([priority]) => priority === draft.secondaryPriority,
        ) ||
        typeof draft.target !== "string" ||
        typeof draft.budget !== "string" ||
        typeof draft.defence !== "string" ||
        !["owned", "usable", "future"].includes(draft.mode) ||
        !draft.assumptions ||
        typeof draft.assumptions.attack !== "string" ||
        typeof draft.assumptions.quest !== "boolean" ||
        typeof draft.assumptions.acquired !== "string" ||
        typeof draft.maxActions !== "string" ||
        typeof draft.supplies !== "string" ||
        !["base", "ordered", "explicit"].includes(draft.topology) ||
        !Array.isArray(draft.exclusions) ||
        !draft.exclusions.every((id: unknown) => Number.isSafeInteger(id)) ||
        !Array.isArray(draft.roles) ||
        draft.roles.length < 1 ||
        draft.roles.length > 4 ||
        !draft.roles.every(
          (r: {
            id: unknown;
            name: unknown;
            style: string;
            weight: unknown;
            locks: unknown;
          }) =>
            typeof r.id === "string" &&
            typeof r.name === "string" &&
            ["melee", "ranged", "magic"].includes(r.style) &&
            typeof r.weight === "string" &&
            typeof r.locks === "object" &&
            r.locks !== null,
        )
      )
        return null;
    }
    if (data.version === 1) {
      data.multi.roles = data.multi.roles.map(
        (role: import("../api/contracts").Role) =>
          role.combatTarget
            ? role
            : {
                ...role,
                combatTarget: structuredClone(
                  data.multi.combatTarget ?? {
                    name: data.multi.target,
                    defence_level: Number(data.multi.defence) || 1,
                    magic_level: 1,
                    bonuses: {},
                  },
                ),
                targetInputs: data.multi.combatTarget
                  ? {}
                  : { defence_level: data.multi.defence },
              },
      );
    }
    return data;
  } catch {
    return null;
  }
}
