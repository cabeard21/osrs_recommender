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
}
export interface Scenario {
  objective: "weighted_dps";
  request: {
    roles: (Omit<Role, "weight"> & { weight: number })[];
    target: { name: string; defence: number };
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
  owned: boolean;
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
  source: "fixture";
}
export interface Metrics {
  dps: number;
  maxHit: number;
  accuracy: number;
  ticks: number;
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
  source: "fixture";
  scenario: Scenario;
  fingerprint: string;
  snapshotId: string;
  evaluatedAt: string;
  catalogVersion: string;
  modelVersion: string;
  priceRevision: string;
  solutions: Solution[];
  warnings: string[];
}
export interface Trial {
  resultFingerprint: string;
  solutionId: string;
  roleId: string;
  equipment: Equipment;
  baseline: Metrics;
  proposed: Metrics;
  source: "fixture";
}
export type FixtureFailure = "none" | "busy" | "no-solution" | "error";
export interface GearClient {
  getContext(): Promise<GearContext>;
  getItem(id: number): Promise<Item>;
  alternatives(slot: Slot, scenario: Scenario): Promise<Item[]>;
  optimize(scenario: Scenario, signal: AbortSignal): Promise<OptimizationReply>;
  evaluate(
    result: OptimizationReply,
    solutionId: string,
    roleId: string,
    equipment: Equipment,
  ): Promise<Trial>;
}

export const emptyEquipment = (): Equipment =>
  Object.fromEntries(slots.map((slot) => [slot, null])) as Equipment;
