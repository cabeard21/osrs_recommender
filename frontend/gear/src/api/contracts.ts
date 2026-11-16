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
  | "magic_ranged_defence"
  | "stab_defence"
  | "slash_defence"
  | "crush_defence"
  | "ranged_defence"
  | "magic_defence"
  | "melee_defence_roll"
  | "melee_magic_defence_roll"
  | "melee_ranged_defence_roll"
  | "balanced_defence_roll"
  | "magic_ranged_defence_roll"
  | "stab_defence_roll"
  | "slash_defence_roll"
  | "crush_defence_roll"
  | "ranged_defence_roll"
  | "magic_defence_roll"
  | "prayer_bonus"
  | "melee_strength_bonus"
  | "ranged_strength_bonus"
  | "magic_damage_bonus"
  | "accuracy";
export interface WorkBudgetPolicy {
  budget_scope?: "per_discipline" | "per_discipline_assignment";
  discipline_count?: number;
  discipline_assignment_count?: number;
  policy: "baseline-v1" | "local-refinement-v1";
  complete_assignment_limit: 0 | 10000;
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
  name?: string | null;
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
export interface CrystalHalberdCharging {
  method: "auto" | "coins" | "shards";
  coin_recharge_cost_gp: 750000 | 600000 | 450000 | 300000 | 150000;
  shard_value_gp: number | null;
}
export interface Role {
  safeSpotting?: boolean;
  fightDurationSeconds?: string;
  onSlayerTask?: boolean;
  markOfDarkness?: boolean;
  prayers?: PrayerPolicy;
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
  poison_susceptibility?: "susceptible" | "immune" | "unknown";
  venom_susceptibility?: "susceptible" | "immune" | "unknown";
  demonbane_vulnerability_percent?: number;
  hitpoints?: number | null;
  current_hitpoints?: number | null;
  traits?: string[];
  flat_armour?: number;
  name: string;
  defence_level: number;
  magic_level: number;
  bonuses: Record<string, number>;
  [key: string]: unknown;
}
export interface PotionPolicy {
  mode: "disabled" | "optimize" | "fixed";
  allowed_ids: string[];
  selected_ids: string[];
}
export interface PrayerPolicy {
  mode: "disabled" | "optimize" | "fixed";
  allowed_ids: string[];
  selected_ids: string[];
}
export interface PrayerModifiers {
  attack: number;
  strength: number;
  ranged_accuracy: number;
  ranged_strength: number;
  magic_accuracy: number;
  defence: number;
  magic_defence: number;
  magic_damage: number;
}
export interface PrayerDefinition {
  id: string;
  name: string;
  group?: string;
  modifiers?: PrayerModifiers;
  availability?: "satisfied" | "unsatisfied" | "unknown";
  reasons?: string[];
  conflicts?: string[];
  level?: number;
  defence_level?: number;
  attack_level?: number;
  strength_level?: number;
  access_availability?: "satisfied" | "unsatisfied" | "unknown";
  access_reasons?: string[];
}
export interface PotionSummary {
  base_levels?: Record<string, number>;
  resources?: { name: string; cost_per_dose_gp: number | null }[];
  hp_cost?: number;
  selected_ids: string[];
  boosted_levels: Record<string, number>;
  cost_per_application_gp: number | null;
  model_version: string;
}
export interface PotionDefinition {
  id: string;
  name: string;
}
export type FireTomePages = "burnt" | "searing";
export interface Draft {
  crystalHalberdCharging?: CrystalHalberdCharging;
  fireTomePages?: FireTomePages;
  includeUntradeables?: boolean;
  potions?: PotionPolicy;
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
    crystal_halberd_charging?: CrystalHalberdCharging;
    fire_tome_pages?: FireTomePages;
    include_untradeables?: boolean;
    potions?: PotionPolicy;
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
  selectedPrayerIds?: string[];
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
export interface Preparation {
  source_item_id: number | null;
  usable_item_id: number;
  market_item_id: number | null;
  charging_required: boolean;
  charges: "unknown";
  activation_reserve: { item_id: number; quantity: number }[];
  message: string;
}
export interface RunningCost {
  charging_assumption?: string | null;
  charging_alternatives?: {
    resources: RunningCost["resources"];
    gp_per_attack: number | null;
  }[];
  status: "known" | "unavailable";
  gp_per_attack: number | null;
  gp_per_hour: number | null;
  gp_per_damage: number | null;
  resources: {
    item_id: number;
    name: string;
    required_quantity: number;
    consumed_quantity: number;
    supplied_quantity: number;
    supplied_by: string | null;
    unit_price_gp: number | null;
    price_layer: string;
  }[];
  reasons: string[];
}
export interface RunningCostFrontierGroup {
  swap_limit: number | null;
  baseline_dps: number | null;
  baseline_solution?: JointSolutionDTO | null;
  sampled: boolean;
  points: {
    id: string;
    solution: JointSolutionDTO;
    dps_loss: number;
    dps_loss_pct: number | null;
  }[];
}
export interface JointSolutionDTO {
  unowned_untradeable_item_ids?: number[];
  potions?: PotionSummary;
  running_cost?: RunningCost;
  secondary_priority?: SecondaryPriority;
  secondary_value?: number | null;
  score: number;
  loadouts: Record<
    string,
    {
      preparations?: Preparation[];
      equipment: Record<string, number>;
      performance: CombatPerformance;
      selected_prayer_ids?: string[];
      combat_option?: CombatOption;
      running_cost?: RunningCost;
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
  running_cost_frontiers?: RunningCostFrontierGroup[];
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
export interface PlayerDefenceRolls {
  stab: number | null;
  slash: number | null;
  crush: number | null;
  ranged: number | null;
  magic: number | null;
  limitations: string[];
}
export interface BoltPerformance {
  family: string;
  proc_chance: number;
  activation_probability: number;
  expected_damage_per_attack: number;
  total_max_hit: number;
  normal_max_hit: number;
  target_hitpoints: number | null;
  diary_boosted: boolean;
  expected_damage_delta: number;
}
export interface CombatPerformance {
  direct_dps?: number | null;
  status_damage?: {
    kind: "venom" | "poison" | "unknown";
    duration_seconds: number;
    expected_damage: number;
    dps: number;
    application_chance: number;
    limitations: string[];
  } | null;
  demonbane_bonus?: {
    item_id: number | null;
    spell: string | null;
    accuracy_percent: number;
    damage_percent: number;
    vulnerability_percent: number;
    mark_of_darkness: boolean;
  } | null;
  leafy_bonus?: {
    item_id: number;
    damage_numerator: number;
    denominator: number;
  } | null;
  seeking_arrow_bonus?: {
    item_id: number;
    minimum_hit: number;
  } | null;
  slayer_effects?: {
    item_id: number;
    kind: "mask" | "magic_dart";
    accuracy_numerator: number;
    damage_numerator: number;
    denominator: number;
    base_max_hit: number | null;
  }[];
  tome_bonus?: {
    item_id: number;
    element: "fire" | "water" | "earth";
    damage_percent: number;
    accuracy_percent: number;
    fire_pages: FireTomePages | null;
    minimum_hit: number;
  } | null;
  aquanite_hopper?: {
    proc_chance: number;
    secondary_accuracy: number;
    secondary_max_hit: number;
    expected_damage_delta: number;
    expected_ammunition_per_attack: number;
    approximate: boolean;
    assumptions: string[];
  } | null;
  elemental_amulet_bonus?: {
    item_id: number;
    element: "air" | "water" | "earth" | "fire";
    base_max_hit_bonus: number;
  } | null;
  bolt_effect?: BoltPerformance | null;
  player_defence_rolls?: PlayerDefenceRolls | null;
  hitsplats?: { accuracy: number; max_hit: number }[];
  elemental_weakness?: {
    element: "air" | "water" | "earth" | "fire" | null;
    percent: number;
    applied: boolean;
    reason: string | null;
    max_hit_bonus: number;
    attack_roll_bonus: number;
  } | null;
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
    running_cost_frontiers?: RunningCostFrontierGroup[];
    running_cost_policy?: Record<string, unknown>;
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
  preparations?: Preparation[];
  unowned_untradeable_item_ids?: number[];
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
export interface ProgressStage {
  id: string;
  label: string;
  status: "complete" | "active" | "pending";
  fraction: number;
}
export interface ProgressLane {
  label: string;
  status: "complete" | "running" | "pending";
  stage: string | null;
  stage_label?: string | null;
  fraction: number;
}
export interface ProgressLaneCounts {
  complete: number;
  running: number;
  pending: number;
}
export interface OptimizationProgress {
  phase: string;
  completed: number;
  total: number;
  elapsed_seconds: number;
  /** Human stage label; absent from older servers. */
  label?: string;
  /** Overall 0–1 completion that never decreases during one attempt. */
  fraction?: number;
  /** Estimated seconds remaining, or null while no estimate is credible. */
  eta_seconds?: number | null;
  stages?: ProgressStage[];
  /** Independent discipline assignments × potion profiles: all when few, else running. */
  lanes?: ProgressLane[];
  lane_counts?: ProgressLaneCounts;
}
export interface GearClient {
  potionTimeline?(
    result: OptimizationReply,
    solution: JointSolutionDTO,
    signal: AbortSignal,
  ): Promise<PotionTimeline>;
  getContext(): Promise<GearContext>;
  getItem(id: number, supportPolicy?: SupportPolicy): Promise<Item>;
  browseItems?(
    slot: Slot,
    query: string,
    offset?: number,
    supportPolicy?: SupportPolicy,
  ): Promise<ItemPage>;
  alternatives(slot: Slot, scenario: Scenario): Promise<Item[]>;
  optimize(
    scenario: Scenario,
    signal: AbortSignal,
    onProgress?: (progress: OptimizationProgress) => void,
  ): Promise<OptimizationReply>;
  evaluate(
    result: OptimizationReply,
    solutionId: string,
    roleId: string,
    equipment: Equipment,
    signal?: AbortSignal,
  ): Promise<Trial>;
}

export interface PotionTimelineRole {
  dps: number | null;
  secondary_value: number | null;
  reasons: string[];
}
export interface PotionTimelineMeasurement {
  time_seconds: number;
  levels: Record<string, number>;
  dps: number | null;
  secondary_value: number | null;
  roles: Record<string, PotionTimelineRole>;
}
export interface PotionTimeline {
  snapshot_id: string;
  catalog_version: string;
  model_version: string;
  decay_model_version: "potion-decay-v1";
  configuration_fingerprint: string;
  secondary_priority: SecondaryPriority;
  baseline: PotionTimelineMeasurement;
  samples: PotionTimelineMeasurement[];
}

export const emptyEquipment = (): Equipment =>
  Object.fromEntries(slots.map((slot) => [slot, null])) as Equipment;

export interface PhysicalItem {
  support_status?: "verified" | "community_assumed" | "unreviewed";
  support_assumptions?: string[];
  budget_exempt?: boolean;
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
    tome_effect?: {
      element: "fire" | "water" | "earth";
      rune_id: number;
    } | null;
    elemental_spell_bonus?: {
      elements: ("air" | "water" | "earth" | "fire")[];
      base_max_hit_bonus: number;
    } | null;
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
  preparation?: Preparation | null;
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
  potion_catalog?: PotionDefinition[];
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
