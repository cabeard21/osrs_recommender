import type {
  Draft,
  GearContext,
  OptimizationReply,
  Scenario,
  Slot,
  Trial,
  Workspace,
} from "../api/contracts";
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
  const integer = (value: string, name: string, min: number, max: number) => {
    const n = Number(value);
    if (!value.trim() || !Number.isSafeInteger(n) || n < min || n > max)
      throw new Error(`${name} must be a whole number from ${min} to ${max}.`);
    return n;
  };
  const roles = draft.roles.map((r) => ({
    ...structuredClone(r),
    weight: integer(r.weight, "Active-time weight", 1, 100),
  }));
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
  if (live && draft.exclusions.length)
    throw new Error(
      "Live item exclusions are unavailable until Milestone 4. Remove restored exclusions before optimizing.",
    );
  if (live && draft.assumptions.quest)
    throw new Error(
      "Replace the restored demo quest assumption with explicit quest IDs.",
    );
  const edges: [string, string][] =
    draft.topology === "base"
      ? roles
          .filter((r) => r.id !== draft.baseRole)
          .flatMap(
            (r) =>
              [
                [draft.baseRole, r.id],
                [r.id, draft.baseRole],
              ] as [string, string][],
          )
      : roles.slice(1).map((r, i) => [roles[i].id, r.id]);
  return {
    objective: "weighted_dps",
    request: {
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
  generation: number;
  pending: boolean;
  error: string | null;
  outdated: boolean;
  activeRole: string;
  slot: Slot | null;
  solutionId: string;
  view: "side" | "interactive";
}
const workspace = (): WorkspaceState => ({
  draft: newDraft(),
  revision: 0,
  submitted: null,
  result: null,
  previous: null,
  trial: null,
  generation: 0,
  pending: false,
  error: null,
  outdated: false,
  activeRole: "role-1",
  slot: null,
  solutionId: "best-found",
  view: "side",
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
        Pick<WorkspaceState, "activeRole" | "slot" | "view" | "solutionId">
      >;
    }
  | { type: "trial"; mode: Workspace; trial: Trial | null };
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
            state.context.snapshotId !== action.context.snapshotId
              ? {
                  generation: state[mode].generation + 1,
                  pending: false,
                  trial: null,
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
    draft.roles[0] = {
      ...state.single.result!.scenario.request.roles[0],
      weight: String(state.single.result!.scenario.request.roles[0].weight),
      id: "role-1",
      name: "Single result (locked)",
      locks: structuredClone(loadout.equipment),
    };
    if (draft.roles.length === 1) draft.roles.push(newRole(2));
    return {
      ...state,
      mode: "multi",
      multiSeeded: true,
      multi: {
        ...state.multi,
        draft,
        revision: state.multi.revision + 1,
        generation: state.multi.generation + 1,
        pending: false,
        outdated: !!state.multi.result,
        trial: null,
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
        multi: { ...state.multi, draft },
      };
    }
    return { ...state, mode: action.mode };
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
        trial: null,
      };
      break;
    case "start":
      next = {
        ...current,
        submitted: structuredClone(action.scenario),
        generation: action.generation,
        pending: true,
        error: null,
        trial: null,
      };
      break;
    case "success":
      if (current.generation !== action.generation || !current.pending)
        return state;
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
        trial: null,
        solutionId: "best-found",
        activeRole: action.result.scenario.request.roles[0].id,
      };
      break;
    case "error":
      if (current.generation !== action.generation) return state;
      next = { ...current, pending: false, error: action.error };
      break;
    case "cancel":
      next = { ...current, pending: false, generation: current.generation + 1 };
      break;
    case "ui":
      next = {
        ...current,
        ...action.patch,
        trial:
          action.patch.solutionId || action.patch.activeRole
            ? null
            : current.trial,
      };
      break;
    case "trial":
      if (
        action.trial &&
        (current.pending ||
          current.outdated ||
          action.trial.resultFingerprint !== current.result?.fingerprint ||
          action.trial.solutionId !== current.solutionId ||
          action.trial.roleId !== current.activeRole)
      )
        return state;
      next = { ...current, trial: action.trial };
      break;
  }
  return { ...state, [action.mode]: next };
}
const version = 1;
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
    const data = JSON.parse(storage.getItem(storageKey(player)) ?? "null");
    if (data?.version !== version) return null;
    for (const draft of [data.single, data.multi]) {
      if (
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
        !["base", "ordered"].includes(draft.topology) ||
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
    return data;
  } catch {
    return null;
  }
}
