import type {
  Draft,
  GearContext,
  OptimizationReply,
  Scenario,
  Slot,
  Trial,
  Equipment,
  Workspace,
  CombatTarget,
} from "../api/contracts";
import { secondaryPriorities } from "../api/secondaryPriorities";
import {
  emptyCombatOptionGroups,
  selectedCombatOptions,
  potionCombatContext,
} from "../api/combatOptions";
import type { SavedResult, SavedResults } from "./resultStorage";
const EMPTY_GROUP_NOUNS = {
  attack_types: "attack type",
  stances: "stance",
  spells: "spell",
} as const;
export const newRole = (index: number) => ({
  onSlayerTask: false,
  safeSpotting: false,
  fightDurationSeconds: "60",
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
  fireTomePages: "burnt",
  includeUntradeables: false,
  supportPolicy: "community_best_effort",
  secondaryPriority: "default",
  optimizationMode: "fast",
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
const GP_MULTIPLIERS: Record<string, number> = {
  k: 1_000,
  m: 1_000_000,
  b: 1_000_000_000,
};
/** Expands `10m`, `500k`, `1.5b` and `1,000`; anything else is returned as typed. */
export function parseGp(value: string): string {
  const match = /^\s*([\d,]*\.?\d+)\s*([kmb])?\s*$/i.exec(value);
  if (!match) return value;
  const amount = Number(match[1].replaceAll(",", ""));
  const suffix = match[2]?.toLowerCase();
  if (!suffix) return Number.isInteger(amount) ? String(amount) : value;
  return String(Math.round(amount * GP_MULTIPLIERS[suffix]));
}
function integer(value: string, name: string, min: number, max: number) {
  const n = Number(value);
  if (!value.trim() || !Number.isSafeInteger(n) || n < min || n > max)
    throw new Error(`${name} must be a whole number from ${min} to ${max}.`);
  return n;
}
function parseAcquiredIds(acquired: string) {
  return acquired.trim()
    ? acquired
        .split(",")
        .map((v) => integer(v.trim(), "Assumed item ID", 1, 100000))
    : [];
}
function parseSkillLevels(skillLevels: string | undefined) {
  const skills: Record<string, number> = {};
  for (const entry of (skillLevels ?? "").split(",").filter((v) => v.trim())) {
    const [skill, level, extra] = entry.trim().split("=");
    if (!skill || !level || extra)
      throw new Error("Assumed skills use skill=level, separated by commas.");
    skills[skill.trim()] = integer(level.trim(), "Assumed skill", 1, 99);
  }
  return skills;
}
export type DraftFieldErrors = Partial<
  Record<
    "budget" | "defence" | "supplies" | "attack" | "skillLevels" | "acquired",
    string
  >
>;
function errorOf(check: () => unknown): string | undefined {
  try {
    check();
    return undefined;
  } catch (error) {
    return (error as Error).message;
  }
}
/** Per-field messages for inline display. `normalize` still blocks submission. */
export function draftFieldErrors(draft: Draft): DraftFieldErrors {
  const checks: Record<keyof DraftFieldErrors, () => unknown> = {
    budget: () => integer(parseGp(draft.budget), "Budget", 0, 2147483647),
    defence: () => integer(draft.defence, "Target defence", 0, 10000),
    supplies: () => integer(draft.supplies, "Supply slots", 0, 28),
    attack: () =>
      draft.assumptions.attack &&
      integer(draft.assumptions.attack, "Assumed Attack", 1, 99),
    skillLevels: () => parseSkillLevels(draft.assumptions.skillLevels),
    acquired: () => parseAcquiredIds(draft.assumptions.acquired),
  };
  return Object.fromEntries(
    Object.entries(checks).flatMap(([field, check]) => {
      const message = errorOf(check);
      return message ? [[field, message]] : [];
    }),
  );
}
function normalizeHitpoints(
  target: CombatTarget | undefined,
  inputs: Record<string, string> = {},
): CombatTarget | undefined {
  if (!target) return target;
  const result = { ...target };
  for (const key of ["hitpoints", "current_hitpoints"] as const) {
    const raw = inputs[key];
    if (raw !== undefined) result[key] = raw.trim() ? Number(raw) : null;
    const value = result[key];
    if (
      value != null &&
      (!Number.isSafeInteger(value) || value < 1 || value > 1000000)
    )
      throw new Error(
        `Target ${key} requires a positive whole number up to 1000000.`,
      );
  }
  if (
    result.hitpoints != null &&
    result.current_hitpoints != null &&
    result.current_hitpoints > result.hitpoints
  )
    throw new Error("Target current_hitpoints cannot exceed base hitpoints.");
  return result;
}
export function normalize(
  draft: Draft,
  snapshotId: string,
  live = false,
  context: GearContext | null = null,
): Scenario {
  if (!["burnt", "searing"].includes(draft.fireTomePages ?? "burnt"))
    throw new Error("Choose valid Tome of Fire pages.");
  if (
    !["verified_only", "community_best_effort"].includes(
      draft.supportPolicy ?? "community_best_effort",
    )
  )
    throw new Error("Choose a valid equipment support policy.");
  if (
    !secondaryPriorities.some(
      ([priority]) => priority === (draft.secondaryPriority ?? "default"),
    )
  )
    throw new Error("Choose a valid tradeoff metric.");
  if (!["fast", "thorough"].includes(draft.optimizationMode ?? "fast"))
    throw new Error("Choose Fast or Thorough optimization.");
  const charging = draft.crystalHalberdCharging;
  if (
    charging &&
    (!["auto", "coins", "shards"].includes(charging.method) ||
      ![750000, 600000, 450000, 300000, 150000].includes(
        charging.coin_recharge_cost_gp,
      ) ||
      (charging.shard_value_gp !== null &&
        (!Number.isFinite(charging.shard_value_gp) ||
          charging.shard_value_gp < 0)))
  )
    throw new Error("Choose valid crystal halberd charging settings.");
  const validateSusceptibility = (
    target: import("../api/contracts").CombatTarget | undefined,
  ) => {
    for (const key of [
      "poison_susceptibility",
      "venom_susceptibility",
    ] as const)
      if (
        target?.[key] !== undefined &&
        !["susceptible", "immune", "unknown"].includes(target[key]!)
      )
        throw new Error("Choose valid target poison and venom susceptibility.");
  };
  validateSusceptibility(draft.combatTarget);
  for (const role of draft.roles) {
    validateSusceptibility(role.combatTarget);
    if (
      role.safeSpotting !== undefined &&
      typeof role.safeSpotting !== "boolean"
    )
      throw new Error("Choose a valid safe spotting setting.");
    integer(role.fightDurationSeconds ?? "60", "Fight duration", 1, 3600);
    if (role.utility && role.safeSpotting)
      throw new Error("Safe spotting requires a scored combat configuration.");
    if (
      role.onSlayerTask !== undefined &&
      typeof role.onSlayerTask !== "boolean"
    )
      throw new Error("Choose a valid Slayer task setting.");
    if (!role.autoDiscipline) continue;
    if (role.utility)
      throw new Error("Auto requires an ordinary combat configuration.");
    const disciplines = role.allowedDisciplines ?? ["melee", "ranged", "magic"];
    if (
      !disciplines.length ||
      new Set(disciplines).size !== disciplines.length ||
      disciplines.some((d) => !["melee", "ranged", "magic"].includes(d))
    )
      throw new Error("Choose at least one valid combat discipline.");
    if (role.combatOptionOptimization === false)
      throw new Error("Auto requires combat option optimization.");
  }
  const globalTarget = normalizeHitpoints(
    draft.combatTarget,
    draft.targetInputs,
  );
  const globalArmour = draft.combatTarget?.flat_armour ?? 0;
  if (
    (draft.targetInputs?.flat_armour !== undefined &&
      !draft.targetInputs.flat_armour.trim()) ||
    !Number.isSafeInteger(globalArmour) ||
    Math.abs(globalArmour) > 10000
  )
    throw new Error(
      "Target flat armour requires a whole number between -10000 and 10000.",
    );
  const roles = draft.roles.map((r) => {
    const role = {
      ...structuredClone(r),
      onSlayerTask: r.onSlayerTask ?? false,
      safeSpotting: r.safeSpotting ?? false,
      fightDurationSeconds: r.fightDurationSeconds ?? "60",
      weight: Number(r.weight),
    };
    if (draft.roles.length === 1 && draft.targetSelection && !r.combatTarget) {
      role.combatTarget = draft.combatTarget
        ? structuredClone(draft.combatTarget)
        : undefined;
      role.targetSelection = draft.targetSelection;
      role.targetInputs = draft.targetInputs;
    }
    const target = role.combatTarget ?? draft.combatTarget;
    const restrictions = target?.unsupported_mechanics;
    if (Array.isArray(restrictions) && restrictions.length)
      throw new Error(
        `Cannot optimize against ${target!.name}: ${restrictions.join(" ")} Choose a supported NPC target.`,
      );
    if (
      live &&
      context &&
      !role.utility &&
      role.combatOptionOptimization !== false
    ) {
      const options = selectedCombatOptions(
        role,
        potionCombatContext(context, draft.potions),
      );
      if (!options)
        throw new Error(
          "Synced combat options are unavailable. Refresh account context.",
        );
      const [empty] = emptyCombatOptionGroups(
        role,
        potionCombatContext(context, draft.potions),
      );
      if (empty)
        throw new Error(
          `${role.name}: choose at least one ${EMPTY_GROUP_NOUNS[empty]} in Combat Options.`,
        );
      role.combatOptions = options;
    } else {
      delete role.combatOptions;
    }
    if (role.combatTarget) {
      role.combatTarget = normalizeHitpoints(
        role.combatTarget,
        role.targetInputs,
      )!;
      for (const [key, value] of Object.entries(role.targetInputs ?? {})) {
        if (key === "hitpoints" || key === "current_hitpoints") continue;
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
          key === "flat_armour"
            ? -10000
            : key.startsWith("bonuses.") || key.startsWith("ranged_")
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
    if (!role.utility && !role.autoDiscipline && !stances.includes(role.stance))
      throw new Error(
        `${role.name} attack stance is unsupported for its discipline.`,
      );
    if (
      role.combatTarget &&
      (!Number.isSafeInteger(role.combatTarget.flat_armour ?? 0) ||
        Math.abs(role.combatTarget.flat_armour ?? 0) > 10000 ||
        [role.combatTarget.defence_level, role.combatTarget.magic_level].some(
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
  const assumed = parseAcquiredIds(draft.assumptions.acquired);
  const skills = parseSkillLevels(draft.assumptions.skillLevels);
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
      crystal_halberd_charging: draft.crystalHalberdCharging,
      fire_tome_pages: draft.fireTomePages ?? "burnt",
      support_policy: draft.supportPolicy ?? "community_best_effort",
      potions: draft.potions ?? {
        mode: "disabled",
        allowed_ids: [],
        selected_ids: [],
      },
      secondary_priority: draft.secondaryPriority ?? "default",
      max_dps_loss_pct: 100,
      optimization_mode: draft.optimizationMode ?? "fast",
      roles,
      target: {
        name: draft.target,
        selection: draft.targetSelection,
        defence: integer(draft.defence, "Target defence", 0, 10000),
        ...(draft.combatTarget
          ? { definition: structuredClone(globalTarget!) }
          : {}),
      },
      budget_gp: integer(parseGp(draft.budget), "Budget", 0, 2147483647),
      mode: draft.mode,
      include_untradeables: draft.includeUntradeables ?? false,
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
  errorIsValidation: boolean;
  runNotice: string | null;
  outdated: boolean;
  activeRole: string;
  slot: Slot | null;
  solutionId: string;
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
  errorIsValidation: false,
  runNotice: null,
  outdated: false,
  activeRole: "role-1",
  slot: null,
  solutionId: "best-found",
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
  | { type: "restore-results"; results: SavedResults }
  | { type: "edit"; mode: Workspace; draft: Draft }
  | { type: "start"; mode: Workspace; scenario: Scenario; generation: number }
  | {
      type: "success";
      mode: Workspace;
      generation: number;
      result: OptimizationReply;
    }
  | {
      type: "error";
      mode: Workspace;
      generation: number;
      error: string;
      validation?: boolean;
    }
  | { type: "cancel"; mode: Workspace }
  | {
      type: "ui";
      mode: Workspace;
      patch: Partial<
        Pick<
          WorkspaceState,
          "activeRole" | "slot" | "solutionId" | "selectedTransition"
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
function resultIsStale(
  result: OptimizationReply,
  context: GearContext | null,
): boolean {
  if (!context) return true;
  return (
    (!!result.live &&
      result.live.scenario.include_untradeables === undefined) ||
    result.snapshotId !== context.snapshotId ||
    (!!context.live &&
      (result.catalogVersion !== context.live.catalog_version ||
        result.modelVersion !== context.live.model_version ||
        result.priceRevision !== context.live.price_revision))
  );
}
export function reducer(state: State, action: Action): State {
  if (action.type === "restore-results")
    return {
      ...state,
      ...Object.fromEntries(
        (Object.entries(action.results) as [Workspace, SavedResult][])
          .filter(
            ([mode, saved]) =>
              !state[mode].result &&
              saved.result.snapshotId === state.context?.snapshotId,
          )
          .map(([mode, saved]) => [
            mode,
            {
              ...state[mode],
              result: saved.result,
              submitted: saved.result.scenario,
              solutionId: saved.solutionId,
              activeRole: saved.result.scenario.request.roles[0].id,
              outdated:
                saved.outdated || resultIsStale(saved.result, state.context),
            },
          ]),
      ),
    };
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
                resultIsStale(state[mode].result, action.context)),
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
      autoDiscipline: false,
      allowedDisciplines: undefined,
      style: loadout.discipline ?? sourceRole.style,
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
      targetSelection:
        sourceRole.targetSelection ?? sourceScenario.target.selection,
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
      draft.roles = draft.roles.map((role) => ({
        ...role,
        combatTarget: structuredClone(
          role.combatTarget ??
            draft.combatTarget ?? {
              name: draft.target,
              defence_level: Number(draft.defence),
              magic_level: 1,
              bonuses: {},
            },
        ),
        targetSelection: structuredClone(
          role.targetSelection ?? draft.targetSelection,
        ),
        targetInputs: structuredClone(
          role.targetInputs ??
            draft.targetInputs ?? { defence_level: draft.defence },
        ),
      }));
      delete draft.targetSelection;
      delete draft.targetInputs;
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
        errorIsValidation: false,
        runNotice: current.pending
          ? "Run cancelled because settings changed. Run again when you're ready."
          : current.runNotice,
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
        errorIsValidation: false,
        runNotice: null,
        ...clearedTrial(current),
      };
      break;
    case "success":
      if (current.generation !== action.generation || !current.pending)
        return state;
      if (
        (current.submitted?.request.fire_tome_pages ?? "burnt") !==
        (action.result.scenario.request.fire_tome_pages ?? "burnt")
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error: "Tome of Fire pages changed; rerun the selected page mode.",
          },
        };
      if (
        JSON.stringify(
          current.submitted?.request.roles.map((role) => [
            role.id,
            role.onSlayerTask ?? false,
          ]),
        ) !==
        JSON.stringify(
          action.result.scenario.request.roles.map((role) => [
            role.id,
            role.onSlayerTask ?? false,
          ]),
        )
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error: "Slayer task settings changed; rerun optimization.",
          },
        };
      if (
        JSON.stringify(
          current.submitted?.request.roles.map((role) => [
            role.id,
            role.safeSpotting ?? false,
            role.fightDurationSeconds ?? "60",
          ]),
        ) !==
        JSON.stringify(
          action.result.scenario.request.roles.map((role) => [
            role.id,
            role.safeSpotting ?? false,
            role.fightDurationSeconds ?? "60",
          ]),
        )
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error:
              "Safe spotting or status duration changed; rerun optimization.",
          },
        };
      if (
        JSON.stringify(
          current.submitted?.request.crystal_halberd_charging ?? null,
        ) !==
        JSON.stringify(
          action.result.scenario.request.crystal_halberd_charging ?? null,
        )
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error:
              "Crystal halberd charging settings changed; rerun optimization.",
          },
        };
      if (
        (current.submitted?.request.support_policy ?? "verified_only") !==
        (action.result.scenario.request.support_policy ?? "verified_only")
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error:
              "Equipment support policy changed; rerun the selected policy.",
          },
        };
      if (
        (current.submitted?.request.secondary_priority ?? "default") !==
        (action.result.scenario.request.secondary_priority ?? "default")
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error: "Tradeoff metric changed; rerun the selected priority.",
          },
        };
      if (
        (current.submitted?.request.max_dps_loss_pct ?? 10) !==
        (action.result.scenario.request.max_dps_loss_pct ?? 10)
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error: "DPS loss range changed; rerun optimization.",
          },
        };
      if (
        (current.submitted?.request.optimization_mode ?? "fast") !==
        (action.result.scenario.request.optimization_mode ?? "fast")
      )
        return {
          ...state,
          [action.mode]: {
            ...current,
            pending: false,
            error: "Optimization mode changed; rerun the selected mode.",
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
        selectedTransition: "",
      };
      break;
    case "error":
      if (current.generation !== action.generation) return state;
      next = {
        ...current,
        pending: false,
        error: action.error,
        errorIsValidation: !!action.validation,
      };
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
const version = 3;
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
        storage.getItem(`gear-drafts-v2:${player}`) ??
        storage.getItem(`gear-drafts-v1:${player}`) ??
        "null",
    );
    if (![1, 2, version].includes(data?.version)) return null;
    const single = upgradeStoredDraft(data.single);
    const multi = upgradeStoredDraft(data.multi);
    if (!single || !multi) return null;
    if (data.version === 1) {
      const roles = multi.roles.map((role: import("../api/contracts").Role) =>
        role.combatTarget
          ? role
          : {
              ...role,
              combatTarget: structuredClone(
                multi.combatTarget ?? {
                  name: multi.target,
                  defence_level: Number(multi.defence) || 1,
                  magic_level: 1,
                  bonuses: {},
                },
              ),
              targetInputs: multi.combatTarget
                ? {}
                : { defence_level: multi.defence },
            },
      );
      return { ...data, single, multi: { ...multi, roles } };
    }
    return { ...data, single, multi };
  } catch {
    return null;
  }
}
/**
 * Checks a draft parsed from storage and fills in settings added since it was
 * written. Returns null when the value is not a usable draft.
 */
export function upgradeStoredDraft(value: unknown): Draft | null {
  if (!value || typeof value !== "object") return null;
  // Preserve the caller's top-level draft while applying stored-setting defaults.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const draft = { ...(value as any) };
  if (draft.fireTomePages === undefined) draft.fireTomePages = "burnt";
  if (draft.includeUntradeables === undefined)
    draft.includeUntradeables = false;
  if (draft.supportPolicy === undefined)
    draft.supportPolicy = "community_best_effort";
  if (draft.optimizationMode === undefined) draft.optimizationMode = "fast";
  if (draft.secondaryPriority === undefined)
    draft.secondaryPriority = "default";
  const isValid = !(
    !["burnt", "searing"].includes(draft.fireTomePages) ||
    typeof draft.includeUntradeables !== "boolean" ||
    !secondaryPriorities.some(
      ([priority]) => priority === draft.secondaryPriority,
    ) ||
    !["fast", "thorough"].includes(draft.optimizationMode) ||
    !["verified_only", "community_best_effort"].includes(draft.supportPolicy) ||
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
        onSlayerTask?: unknown;
        safeSpotting?: unknown;
        fightDurationSeconds?: unknown;
        id: unknown;
        name: unknown;
        style: string;
        weight: unknown;
        locks: unknown;
      }) =>
        typeof r.id === "string" &&
        typeof r.name === "string" &&
        (r.onSlayerTask === undefined || typeof r.onSlayerTask === "boolean") &&
        (r.safeSpotting === undefined || typeof r.safeSpotting === "boolean") &&
        (r.fightDurationSeconds === undefined ||
          (typeof r.fightDurationSeconds === "string" &&
            !errorOf(() =>
              integer(
                r.fightDurationSeconds as string,
                "Fight duration",
                1,
                3600,
              ),
            ))) &&
        ["melee", "ranged", "magic"].includes(r.style) &&
        typeof r.weight === "string" &&
        typeof r.locks === "object" &&
        r.locks !== null,
    )
  );
  return isValid
    ? ({
        ...draft,
        roles: draft.roles.map((role: Draft["roles"][number]) => ({
          ...role,
          onSlayerTask: role.onSlayerTask ?? false,
          safeSpotting: role.safeSpotting ?? false,
          fightDurationSeconds: role.fightDurationSeconds ?? "60",
        })),
      } as Draft)
    : null;
}
