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
export type Style = "melee" | "ranged" | "magic";
export type Equipment = Record<Slot, number | null>;
export interface Role {
  id: string;
  name: string;
  style: Style;
  attackType: "stab" | "slash" | "crush";
  stance: string;
  spell: string;
  weight: string;
  locks: Partial<Equipment>;
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
  target: string;
  defence: string;
  budget: string;
  mode: "owned" | "usable" | "future";
  roles: Role[];
  maxActions: string;
  supplies: string;
  topology: "base" | "ordered";
  baseRole: string;
  exclusions: number[];
  assumptions: Assumptions;
  combatTarget?: CombatTarget;
}
export interface Scenario {
  objective: "weighted_dps";
  request: {
    roles: (Omit<Role, "weight"> & { weight: number })[];
    target: { name: string; defence: number; definition?: CombatTarget };
    budget_gp: number;
    mode: Draft["mode"];
    max_swaps: number;
    reserved_supply_slots: number;
    transitions: [string, string][];
    base_role: string;
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
  metrics: Metrics;
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
}
export interface CombatPerformance {
  supported: boolean;
  dps: number | null;
  max_hit: number | null;
  accuracy: number | null;
  attack_interval: number | null;
  bonuses: Record<string, number>;
  limitations: string[];
}
export interface OptimizationDTO {
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
    snapshot_id: string;
    catalog_version: string;
    model_version: string;
    assumptions_fingerprint: string;
    search: Record<string, unknown>;
    limitations: string[];
    alternatives?: Record<
      string,
      {
        item_id: number | null;
        score: number;
        score_delta: number;
        purchase_cost_gp: number;
      }[]
    >;
    selected_solution: {
      score: number;
      loadouts: Record<
        string,
        { equipment: Record<string, number>; performance: CombatPerformance }
      >;
      purchases: {
        item_id: number;
        cost_gp: number | null;
        conditional: boolean;
      }[];
      purchase_cost_gp: number;
    } | null;
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
  getItem(id: number): Promise<Item>;
  browseItems?(slot: Slot, query: string, offset?: number): Promise<ItemPage>;
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
