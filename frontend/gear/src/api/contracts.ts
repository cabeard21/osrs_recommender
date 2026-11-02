export const slots = [
  "head",
  "cape",
  "neck",
  "ammo",
  "weapon",
  "body",
  "shield",
  "legs",
  "hands",
  "feet",
  "ring",
] as const;
export type Slot = (typeof slots)[number];
export type Workspace = "single" | "multi";
export type SupportPolicy = "verified_only" | "community_best_effort";
export type OptimizationMode = "fast" | "thorough";
export type SecondaryPriority =
  | "default"
  | "balanced_defence"
  | "stab_defence"
  | "slash_defence"
  | "crush_defence"
  | "ranged_defence"
  | "magic_defence"
  | "prayer_bonus"
  | "melee_strength_bonus"
  | "ranged_strength_bonus"
  | "magic_damage_bonus"
  | "accuracy";
export interface WorkBudgetPolicy {
  budget_scope?: "per_discipline";
  discipline_count?: number;
  policy: "baseline-v1" | "local-refinement-v1";
  complete_assignment_limit: 0 | 2000;
  targeted_head_refinement: false;
}
export type Style = "melee" | "ranged" | "magic";
export interface CombatOptionSelection {
  attack_types: string[];
  stances: string[];
  spells: string[];
}
export interface CombatOption {
  attack_type: string;
  stance: string;
  spell: string | null;
  powered_attack: string | null;
}
export interface CombatOptionAvailability {
  id: string;
  category?: Style;
  available: boolean;
  reason?: string;
  level?: number;
}
export interface CombatOptionCapabilities {
  attack_types: CombatOptionAvailability[];
  stances: CombatOptionAvailability[];
  spells: CombatOptionAvailability[];
}
export type Equipment = Record<Slot, number | null>;
export interface TargetSelection {
  key: string;
  catalog_revision: string;
}
export interface Role {
  targetSelection?: TargetSelection;
  id: string;
  name: string;
  style: Style;
  autoDiscipline?: boolean;
  manualCombatOptionOptimization?: boolean;
  allowedDisciplines?: Style[];
  attackType: "stab" | "slash" | "crush";
  stance: string;
  spell: string;
  combatOptionOptimization?: boolean;
  combatOptionDisabled?: CombatOptionSelection;
  combatOptionExplicitlyEmpty?: Partial<
    Record<keyof CombatOptionSelection, boolean>
  >;
  combatOptions?: CombatOptionSelection;
  weight: string;
  locks: Partial<Equipment>;
  combatTarget?: CombatTarget;
  targetInputs?: Record<string, string>;
  utility?: boolean;
  parentRole?: string;
}
export interface Assumptions {
  attack: string;
  quest: boolean;
  acquired: string;
  skillLevels?: string;
  completedQuests?: string;
}
export interface CombatTarget {
  name: string;
  defence_level: number;
  magic_level: number;
  bonuses: Record<string, number>;
  [key: string]: unknown;
}
export interface Draft {
  targetInputs?: Record<string, string>;
  targetSelection?: TargetSelection;
  supportPolicy?: SupportPolicy;
  secondaryPriority?: SecondaryPriority;
  maxDpsLossPct?: string;
  optimizationMode?: OptimizationMode;
  target: string;
  defence: string;
  budget: string;
  mode: "owned" | "usable" | "future";
  roles: Role[];
  maxActions: string;
  supplies: string;
  topology: "base" | "ordered" | "explicit";
  baseRole: string;
  globalLocks?: Partial<Equipment>;
  transitions?: [string, string][];
  orderedRoles?: string[];
  loop?: boolean;
  exclusions: number[];
  assumptions: Assumptions;
  combatTarget?: CombatTarget;
}
export interface Scenario {
  objective: "weighted_dps";
  request: {
    support_policy?: SupportPolicy;
    secondary_priority?: SecondaryPriority;
    max_dps_loss_pct?: number;
    optimization_mode?: OptimizationMode;
    roles: (Omit<Role, "weight"> & { weight: number })[];
    target: {
      name: string;
      defence: number;
      definition?: CombatTarget;
      selection?: TargetSelection;
    };
    budget_gp: number;
    mode: Draft["mode"];
    max_swaps: number;
    reserved_supply_slots: number;
    transitions: [string, string][];
    base_role: string;
    locks?: Partial<Equipment>;
    ordered_roles?: string[];
    loop?: boolean;
    excluded_item_ids: number[];
    skill_overrides: Record<string, number>;
    quest_overrides: Record<string, string>;
    assumed_item_ids: number[];
    expected_snapshot_id: string;
  };
}
export interface Item {
  id: number;
  name: string;
  slot: Slot;
  owned: boolean | null;
  facts?: PhysicalItem;
  price: number | null;
  requirement: string;
}
export interface GearContext {
  playerId: string;
  displayName: string;
  snapshotId: string;
  observedAt: string;
  equipment: Equipment;
  items: Item[];
  equipmentStatus: "observed" | "partial" | "unknown";
  source: "fixture" | "live";
  live?: ContextDTO;
}
export interface Metrics {
  dps: number;
  maxHit: number;
  accuracy: number;
  ticks?: number;
  seconds?: number;
}
export interface Loadout {
  roleId: string;
  name: string;
  equipment: Equipment;
  metrics: Metrics | null;
  performance?: CombatPerformance;
  combatOption?: CombatOption;
  discipline?: Style;
}
export interface Transition {
  from: string;
  to: string;
  actions: string[];
  changedSlots: number;
  peak: number;
}
export interface Solution {
  id: string;
  actionLimit: number;
  loadouts: Loadout[];
  weightedDps: number;
  purchases: number[];
  cost: number;
  shared: number[];
  transitions: Transition[];
  live?: JointSolutionDTO;
}
export interface PurchaseDTO {
  item_id: number;
  cost_gp: number | null;
  conditional: boolean;
}
export interface EquipmentActionDTO {
  operation: "equip" | "unequip";
  slot: string;
  item_id: number;
  automatically_removed: number[];
  gear_inventory_slots: number;
}
export interface JointTransitionDTO {
  from_role: string;
  to_role: string;
  actions: EquipmentActionDTO[];
  action_count: number;
  changed_slots: number;
  max_gear_inventory_slots: number;
}
export interface JointSolutionDTO {
  secondary_priority?: SecondaryPriority;
  secondary_value?: number | null;
  score: number;
  loadouts: Record<
    string,
    {
      equipment: Record<string, number>;
      performance: CombatPerformance;
      combat_option?: CombatOption;
      discipline?: Style;
    }
  >;
  purchases: PurchaseDTO[];
  purchase_cost_gp: number;
  transitions: JointTransitionDTO[];
  carried_item_ids: number[];
  distinct_items: number;
  gear_inventory_slots: number;
  max_gear_inventory_slots: number;
  remaining_supply_slots: number;
  remaining_inventory_slots: number;
  reserved_supply_slots: number;
  maximum_actions: number;
}
export interface SecondaryFrontierGroup {
  swap_limit: number | null;
  baseline_dps: number | null;
  sampled: boolean;
  points: {
    id: string;
    solution: JointSolutionDTO;
    dps_loss: number;
    dps_loss_pct: number | null;
    secondary_gain: number;
  }[];
}
export interface DisciplineResult {
  discipline: Style;
  status: "best_found" | "no_feasible_solution_found";
  reasons: string[];
  score: number | null;
  purchase_cost_gp: number | null;
  selected_solution: JointSolutionDTO | null;
  secondary_frontiers: SecondaryFrontierGroup[];
  search: Record<string, unknown>;
  limitations: string[];
  alternatives: NonNullable<OptimizationDTO["result"]["alternatives"]>;
}
export interface OptimizationReply {
  source: "fixture" | "live";
  scenario: Scenario;
  fingerprint: string;
  snapshotId: string;
  evaluatedAt: string;
  catalogVersion: string;
  modelVersion: string;
  priceRevision: string;
  solutions: Solution[];
  warnings: string[];
  items?: Item[];
  live?: OptimizationDTO;
  unrestricted?: Solution | null;
  selectedSolutionId?: string;
}
export interface CombatPerformance {
  supported: boolean;
  dps: number | null;
  max_hit: number | null;
  accuracy: number | null;
  attack_interval: number | null;
  combat_option?: CombatOption;
  bonuses: Record<string, number>;
  limitations: string[];
}
export interface OptimizationDTO {
  frontier_policy?: Record<string, unknown> | null;
  secondary_priority?: SecondaryPriority;
  optimization_mode?: OptimizationMode;
  work_budget_policy?: WorkBudgetPolicy;
  api_version: "gear-ui-v1";
  evaluated_at: string;
  scenario: Record<string, unknown>;
  scenario_fingerprint: string;
  price_revision: string;
  baseline: {
    status: "available" | "unavailable";
    equipment: Record<string, number>;
    performance: CombatPerformance | null;
    reasons: string[];
  };
  items: PhysicalItem[];
  result: {
    support_policy?: SupportPolicy;
    support_provenance?: string;
    secondary_priority?: SecondaryPriority;
    optimization_mode?: OptimizationMode;
    work_budget_policy?: WorkBudgetPolicy;
    snapshot_id: string;
    catalog_version: string;
    model_version: string;
    assumptions_fingerprint: string;
    search: Record<string, unknown>;
    limitations: string[];
    curve?: {
      swap_limit: number;
      status: string;
      solution: JointSolutionDTO | null;
      relative_performance: number | null;
    }[];
    unrestricted?: JointSolutionDTO | null;
    active_time_shares?: Record<string, number>;
    suggested_swap_limit?: number | null;
    catalog_summary?: {
      total_items: number;
      eligible_items: number;
      [key: string]: unknown;
    };
    alternatives?: Record<
      string,
      {
        item_id: number | null;
        score: number;
        score_delta: number;
        purchase_cost_gp: number;
      }[]
    >;
    frontier_policy?: Record<string, unknown> | null;
    secondary_frontiers?: SecondaryFrontierGroup[];
    discipline_results?: DisciplineResult[];
    discipline_comparison?: {
      discipline: Style;
      status: string;
      score: number | null;
      purchase_cost_gp: number | null;
      reasons: string[];
    }[];
    selected_solution: JointSolutionDTO | null;
  };
}
interface TrialIdentity {
  resultFingerprint: string;
  solutionId: string;
  roleId: string;
  equipment: Equipment;
}
export interface FixedEvaluation {
  status: "valid" | "invalid" | "unsupported";
  equipment: Record<string, number>;
  performance: CombatPerformance | null;
  reasons: { path: string; message: string }[];
  purchase_cost_gp: number | null;
  purchases: {
    item_id: number;
    cost_gp: number | null;
    conditional: boolean;
  }[];
  assumed_item_ids: number[];
}
export interface EvaluationDTO {
  api_version: "gear-ui-v1";
  evaluated_at: string;
  scenario: Record<string, unknown>;
  scenario_fingerprint: string;
  snapshot_id: string;
  catalog_version: string;
  model_version: string;
  assumptions_fingerprint: string;
  price_revision: string;
  items: PhysicalItem[];
  baseline: FixedEvaluation;
  proposed: FixedEvaluation;
  deltas: {
    dps: number;
    max_hit: number;
    accuracy: number;
    attack_interval: number;
    purchase_cost_gp: number;
    equipment_changes: {
      slot: string;
      baseline_item_id: number | null;
      proposed_item_id: number | null;
    }[];
    added_purchase_ids: number[];
    removed_purchase_ids: number[];
  } | null;
}
export type Trial = TrialIdentity &
  (
    | { source: "fixture"; baseline: Metrics; proposed: Metrics }
    | {
        source: "live";
        baseline: Metrics | null;
        proposed: Metrics | null;
        live: EvaluationDTO;
      }
  );
export type FixtureFailure = "none" | "busy" | "no-solution" | "error";
export interface GearClient {
  getContext(): Promise<GearContext>;
  getItem(id: number, supportPolicy?: SupportPolicy): Promise<Item>;
  browseItems?(
    slot: Slot,
    query: string,
    offset?: number,
    supportPolicy?: SupportPolicy,
  ): Promise<ItemPage>;
  alternatives(slot: Slot, scenario: Scenario): Promise<Item[]>;
  optimize(scenario: Scenario, signal: AbortSignal): Promise<OptimizationReply>;
  evaluate(
    result: OptimizationReply,
    solutionId: string,
    roleId: string,
    equipment: Equipment,
    signal?: AbortSignal,
  ): Promise<Trial>;
}

export const emptyEquipment = (): Equipment =>
  Object.fromEntries(slots.map((slot) => [slot, null])) as Equipment;

export interface PhysicalItem {
  support_status?: "verified" | "community_assumed" | "unreviewed";
  support_assumptions?: string[];
  effect_status?:
    | "generic_unreviewed"
    | "unsupported_mechanic"
    | "reviewed_ordinary"
    | "community_assumed";
  item_id: number;
  numeric_item_id: number;
  name: string;
  slot: Slot;
  equipment: {
    bonuses: Record<string, number>;
    requires: unknown;
    two_handed: boolean;
    attack_speed: number;
    attack_styles: string[];
  };
  wear: {
    status: string;
    requirements_complete: boolean;
    requirements: unknown;
    unmet: unknown[];
  };
  ownership: {
    status: string;
    meaning: string;
    quantity: number;
    sightings: {
      container: string;
      quantity: number;
      observed_at: string;
      source: string;
    }[];
    container_scans: Record<string, { scanned_at: string; source: string }>;
  };
  acquisition: string;
  acquisition_descriptions: string[];
  price: {
    amount_gp: number | null;
    layer: string;
    selected_trade_at: string | null;
    fetched_at: string | null;
    provider: string | null;
    source: string | null;
    confidence: string | null;
    policy: string | null;
    selection_reason: string;
  };
  limitations: string[];
  catalog_version: string;
}
export interface SlotObservation {
  status: "observed" | "empty" | "unknown" | "ambiguous";
  item_id: number | null;
  candidate_item_ids: number[];
}
export interface ContextDTO {
  data_source?: { label: string; fetched_at: string } | null;
  api_version: "gear-ui-v1";
  evaluated_at: string;
  account: {
    player_id: number;
    username: string;
    snapshot_id: string;
    skills: Record<
      string,
      { level: number; observed_at: string; source: string }
    >;
    last_sync_at: string | null;
  } | null;
  container_scans: Record<
    string,
    { scanned_at: string; source: string; note?: string } | null
  >;
  current_equipment: {
    status: GearContext["equipmentStatus"];
    scanned_at: string | null;
    equipment: Record<string, number>;
    slots: Record<string, SlotObservation>;
    unmapped_item_ids: number[];
    observations?: {
      item_id: number;
      quantity: number;
      observed_at: string;
      source: string;
    }[];
    warnings: string[];
  };
  items: PhysicalItem[];
  capabilities: Record<string, unknown>;
  catalog_version: string;
  model_version: string;
  price_revision: string;
}
export interface ItemPage {
  items: Item[];
  total: number;
  nextOffset: number | null;
}
