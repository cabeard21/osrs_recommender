import { emptyEquipment, slots } from "./contracts";
import type {
  ContextDTO,
  Equipment,
  GearClient,
  GearContext,
  Item,
  ItemPage,
  OptimizationReply,
  OptimizationDTO,
  CombatPerformance,
  Metrics,
  PhysicalItem,
  Scenario,
  Slot,
  Trial,
} from "./contracts";

const apiSlot = (slot: Slot) => (slot === "ammo" ? "ammunition" : slot);
const uiSlot = (slot: unknown) => (slot === "ammunition" ? "ammo" : slot);
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid Gear API response");
  return value as Record<string, unknown>;
}
function requireFields(value: unknown, fields: Record<string, string>) {
  const row = object(value);
  for (const [key, type] of Object.entries(fields)) {
    if (typeof row[key] !== type)
      throw new Error(`Invalid Gear API field: ${key}`);
  }
  return row;
}
function strings(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((entry) => typeof entry === "string")
  );
}
function scans(value: unknown) {
  for (const scan of Object.values(object(value))) {
    if (scan !== null)
      requireFields(scan, { scanned_at: "string", source: "string" });
  }
}
export function performanceMetrics(value: CombatPerformance): Metrics {
  if (
    value.supported !== true ||
    [value.dps, value.max_hit, value.accuracy, value.attack_interval].some(
      (n) => typeof n !== "number" || !Number.isFinite(n),
    )
  )
    throw new Error("Unsupported or invalid combat performance");
  if (
    value.dps! < 0 ||
    !Number.isSafeInteger(value.max_hit) ||
    value.max_hit! < 0 ||
    value.accuracy! < 0 ||
    value.accuracy! > 1 ||
    value.attack_interval! <= 0 ||
    !strings(value.limitations) ||
    Object.values(object(value.bonuses)).some(
      (bonus) => typeof bonus !== "number" || !Number.isFinite(bonus),
    )
  )
    throw new Error("Invalid combat performance metadata");
  return {
    dps: value.dps!,
    maxHit: value.max_hit!,
    accuracy: value.accuracy!,
    seconds: value.attack_interval!,
  };
}
function equipmentMap(value: unknown): Equipment {
  const equipment = emptyEquipment();
  for (const [key, id] of Object.entries(object(value))) {
    const slot = uiSlot(key) as Slot;
    if (!slots.includes(slot) || !Number.isSafeInteger(id) || Number(id) <= 0)
      throw new Error("Invalid result equipment assignment");
    equipment[slot] = id as number;
  }
  return equipment;
}
export function parseOptimization(
  value: unknown,
  scenario: Scenario,
): OptimizationReply {
  const envelope = requireFields(value, {
    api_version: "string",
    evaluated_at: "string",
    price_revision: "string",
    scenario_fingerprint: "string",
  });
  if (envelope.api_version !== "gear-ui-v1" || !Array.isArray(envelope.items))
    throw new Error("Unsupported optimization response");
  const submitted = optimizationRequest(scenario);
  function matches(expected: unknown, actual: unknown): boolean {
    if (Array.isArray(expected))
      return (
        Array.isArray(actual) &&
        expected.length === actual.length &&
        expected.every((entry, index) => matches(entry, actual[index]))
      );
    if (expected && typeof expected === "object")
      return (
        !!actual &&
        typeof actual === "object" &&
        Object.entries(expected).every(([key, entry]) =>
          matches(entry, (actual as Record<string, unknown>)[key]),
        )
      );
    return expected === actual;
  }
  if (!matches(submitted, object(envelope.scenario)))
    throw new Error(
      "Optimization scenario does not match the submitted constraints",
    );
  const serverScenario = object(envelope.scenario);
  if (
    Object.keys(object(serverScenario.locks ?? {})).length ||
    (serverScenario.transitions as unknown[] | undefined)?.length ||
    (serverScenario.ordered_roles as unknown[] | undefined)?.length
  )
    throw new Error("Optimization scenario contains unsubmitted constraints");
  const serverRole = object((serverScenario.roles as unknown[])[0]);
  const serverTarget = object(serverRole.target);
  const expectedBonuses = submitted.roles[0].target.bonuses;
  if (
    Object.entries(object(serverTarget.bonuses)).some(
      ([key, bonus]) => bonus !== (expectedBonuses[key] ?? 0),
    )
  )
    throw new Error(
      "Optimization target bonuses do not match the submitted target",
    );
  const result = requireFields(envelope.result, {
    snapshot_id: "string",
    catalog_version: "string",
    model_version: "string",
    assumptions_fingerprint: "string",
  });
  object(result.search);
  if (!strings(result.limitations))
    throw new Error("Invalid result limitations");
  const baseline = requireFields(envelope.baseline, { status: "string" });
  if (
    !["available", "unavailable"].includes(baseline.status as string) ||
    !strings(baseline.reasons)
  )
    throw new Error("Invalid current equipment baseline");
  equipmentMap(baseline.equipment);
  if (baseline.status === "available")
    performanceMetrics(baseline.performance as CombatPerformance);
  else if (baseline.performance !== null)
    throw new Error("Unavailable baseline must withhold combat metrics");
  const items = envelope.items.map(parseItem);
  const solutions = [];
  if (result.selected_solution !== null) {
    const selected = requireFields(result.selected_solution, {
      score: "number",
      purchase_cost_gp: "number",
    });
    if (
      !Number.isFinite(selected.score) ||
      !Number.isSafeInteger(selected.purchase_cost_gp) ||
      Number(selected.purchase_cost_gp) < 0 ||
      !Array.isArray(selected.purchases)
    )
      throw new Error("Invalid acquisition result");
    const role = scenario.request.roles[0];
    const loadout = object(object(selected.loadouts)[role.id]);
    const equipment = equipmentMap(loadout.equipment);
    for (const id of Object.values(equipment))
      if (id !== null && !items.some((i) => i.id === id))
        throw new Error("Missing physical result item metadata");
    const purchases = selected.purchases.map((p) => {
      const row = requireFields(p, {
        item_id: "number",
        conditional: "boolean",
      });
      if (
        !Number.isSafeInteger(row.item_id) ||
        Number(row.item_id) <= 0 ||
        (row.cost_gp !== null &&
          (!Number.isSafeInteger(row.cost_gp) || Number(row.cost_gp) < 0))
      )
        throw new Error("Invalid purchase fact");
      return row.item_id as number;
    });
    solutions.push({
      id: "best-found",
      actionLimit: scenario.request.max_swaps,
      loadouts: [
        {
          roleId: role.id,
          name: "Best configuration found",
          equipment,
          metrics: performanceMetrics(loadout.performance as CombatPerformance),
        },
      ],
      weightedDps: selected.score as number,
      purchases,
      cost: selected.purchase_cost_gp as number,
      shared: [],
      transitions: [],
    });
  }
  if (result.snapshot_id !== scenario.request.expected_snapshot_id)
    throw new Error("Account changed during optimization. Refresh and rerun.");
  const dto = structuredClone(value) as OptimizationDTO;
  return {
    source: "live",
    scenario: structuredClone(scenario),
    fingerprint: envelope.scenario_fingerprint as string,
    snapshotId: result.snapshot_id as string,
    evaluatedAt: envelope.evaluated_at as string,
    catalogVersion: result.catalog_version as string,
    modelVersion: result.model_version as string,
    priceRevision: envelope.price_revision as string,
    solutions,
    warnings: dto.result.limitations,
    items,
    live: dto,
  };
}
export function optimizationRequest(scenario: Scenario) {
  const r = scenario.request;
  if (r.roles.length !== 1 || r.excluded_item_ids.length)
    throw new Error(
      "Live optimization supports one style without item exclusions.",
    );
  const role = r.roles[0];
  return {
    roles: [
      {
        id: role.id,
        style: role.style === "melee" ? role.attackType : role.style,
        stance: role.stance,
        spell: role.spell,
        weight: role.weight,
        locks: Object.fromEntries(
          Object.entries(role.locks).map(([slot, id]) => [
            apiSlot(slot as Slot),
            id,
          ]),
        ),
        target: r.target.definition ?? {
          name: r.target.name,
          defence_level: r.target.defence,
          magic_level: 1,
          bonuses: {},
        },
      },
    ],
    mode: r.mode,
    budget_gp: r.budget_gp,
    reserved_supply_slots: r.reserved_supply_slots,
    max_swaps: r.max_swaps,
    skill_overrides: r.skill_overrides,
    quest_overrides: r.quest_overrides,
    assumed_item_ids: r.assumed_item_ids,
    expected_snapshot_id: r.expected_snapshot_id,
  };
}
export class GearApiError extends Error {
  constructor(
    message: string,
    public code: string,
  ) {
    super(message);
  }
}
export function parseItem(value: unknown): Item {
  const row = requireFields(value, {
    item_id: "number",
    numeric_item_id: "number",
    name: "string",
    slot: "string",
    catalog_version: "string",
  });
  if (
    !Number.isSafeInteger(row.item_id) ||
    Number(row.item_id) <= 0 ||
    row.item_id !== row.numeric_item_id ||
    !slots.includes(uiSlot(row.slot) as Slot)
  )
    throw new Error("Invalid physical item identity");
  const ownership = requireFields(row.ownership, {
    status: "string",
    meaning: "string",
    quantity: "number",
  });
  const price = requireFields(row.price, {
    layer: "string",
    selection_reason: "string",
  });
  if (
    price.amount_gp !== null &&
    (typeof price.amount_gp !== "number" ||
      !Number.isSafeInteger(price.amount_gp) ||
      price.amount_gp < 0)
  )
    throw new Error("Invalid item price");
  const wear = requireFields(row.wear, {
    status: "string",
    requirements_complete: "boolean",
  });
  const equipment = requireFields(row.equipment, {
    id: "number",
    attack_speed: "number",
    two_handed: "boolean",
  });
  if (
    equipment.id !== row.item_id ||
    !strings(equipment.attack_styles) ||
    Object.values(object(equipment.bonuses)).some(
      (bonus) => typeof bonus !== "number" || !Number.isFinite(bonus),
    )
  )
    throw new Error("Invalid equipment metadata");
  if (
    !["owned", "unowned", "unknown"].includes(ownership.status as string) ||
    !["satisfied", "unsatisfied", "unknown"].includes(wear.status as string) ||
    typeof row.acquisition !== "string"
  )
    throw new Error("Invalid item observation status");
  scans(ownership.container_scans);
  for (const key of [
    "selected_trade_at",
    "fetched_at",
    "provider",
    "source",
    "confidence",
    "policy",
  ]) {
    if (price[key] !== null && typeof price[key] !== "string")
      throw new Error(`Invalid price provenance: ${key}`);
  }
  if (
    !Array.isArray(ownership.sightings) ||
    !strings(row.limitations) ||
    !strings(row.acquisition_descriptions) ||
    !Array.isArray(wear.unmet)
  )
    throw new Error("Invalid item facts");
  for (const sighting of ownership.sightings)
    requireFields(sighting, {
      container: "string",
      quantity: "number",
      observed_at: "string",
      source: "string",
    });
  return {
    id: row.item_id as number,
    name: row.name as string,
    slot: uiSlot(row.slot) as Slot,
    owned: ownership.status === "unknown" ? null : ownership.status === "owned",
    price: price.amount_gp as number | null,
    requirement: `Eligibility: ${wear.status}${wear.requirements_complete ? "" : " · metadata incomplete"}`,
    facts: value as PhysicalItem,
  };
}
export function parseContext(value: unknown): GearContext {
  const row = requireFields(value, {
    api_version: "string",
    evaluated_at: "string",
    catalog_version: "string",
    model_version: "string",
    price_revision: "string",
  });
  if (row.api_version !== "gear-ui-v1" || !Array.isArray(row.items))
    throw new Error("Unsupported Gear API response");
  const projection = requireFields(row.current_equipment, { status: "string" });
  if (!["observed", "partial", "unknown"].includes(projection.status as string))
    throw new Error("Invalid equipment status");
  const observations = object(projection.slots),
    equipment = object(projection.equipment);
  for (const slot of slots) {
    const key = apiSlot(slot);
    const fact = object(observations[key]);
    if (
      !["observed", "empty", "unknown", "ambiguous"].includes(
        fact.status as string,
      ) ||
      !Array.isArray(fact.candidate_item_ids) ||
      fact.candidate_item_ids.some(
        (id) => !Number.isSafeInteger(id) || id <= 0,
      ) ||
      (fact.item_id !== null && !Number.isSafeInteger(fact.item_id))
    )
      throw new Error("Invalid slot observation");
    if (
      equipment[key] !== undefined &&
      (!Number.isSafeInteger(equipment[key]) ||
        fact.status !== "observed" ||
        fact.item_id !== equipment[key])
    )
      throw new Error("Invalid equipment assignment");
  }
  if (
    !strings(projection.warnings) ||
    !Array.isArray(projection.unmapped_item_ids)
  )
    throw new Error("Invalid equipment coverage");
  scans(row.container_scans);
  object(row.capabilities);
  if (row.account !== null) {
    const account = requireFields(row.account, {
      player_id: "number",
      username: "string",
      snapshot_id: "string",
    });
    for (const skill of Object.values(object(account.skills)))
      requireFields(skill, {
        level: "number",
        source: "string",
        observed_at: "string",
      });
    if (
      account.last_sync_at !== null &&
      typeof account.last_sync_at !== "string"
    )
      throw new Error("Invalid account synchronization timestamp");
  }
  const dto = structuredClone(value) as ContextDTO;
  dto.current_equipment.slots.ammo = dto.current_equipment.slots.ammunition;
  if (dto.current_equipment.equipment.ammunition !== undefined)
    dto.current_equipment.equipment.ammo =
      dto.current_equipment.equipment.ammunition;
  delete dto.current_equipment.equipment.ammunition;

  return {
    playerId: dto.account ? `live:${dto.account.player_id}` : "live:no-account",
    displayName: dto.account?.username ?? "No synchronized account",
    snapshotId: dto.account?.snapshot_id ?? "",
    observedAt: dto.account?.last_sync_at ?? "Never synchronized",
    equipment: {
      ...emptyEquipment(),
      ...dto.current_equipment.equipment,
    } as Equipment,
    items: row.items.map(parseItem),
    equipmentStatus: dto.current_equipment.status,
    source: "live",
    live: dto,
  };
}
export class HttpGearClient implements GearClient {
  constructor(
    private base = "/ui-api/gear",
    private transport: typeof fetch = fetch.bind(globalThis),
  ) {}
  private async request(path: string): Promise<unknown> {
    const response = await this.transport(`${this.base}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(
        response.status === 404
          ? "Physical item metadata unavailable"
          : `Gear request failed (${response.status})`,
      );
    return response.json();
  }
  async getContext() {
    return parseContext(await this.request("/context"));
  }
  async getItem(id: number) {
    const item = parseItem(await this.request(`/items/${id}`));
    if (item.id !== id)
      throw new Error("Item response identity does not match request");
    return item;
  }
  async browseItems(slot: Slot, query: string, offset = 0): Promise<ItemPage> {
    const row = object(
      await this.request(
        `/items?${new URLSearchParams({ slot: apiSlot(slot), q: query, offset: String(offset), limit: "20" })}`,
      ),
    );
    if (
      !Array.isArray(row.items) ||
      typeof row.total !== "number" ||
      !(row.next_offset === null || Number.isSafeInteger(row.next_offset))
    )
      throw new Error("Invalid item page");
    return {
      items: row.items.map(parseItem),
      total: row.total,
      nextOffset: row.next_offset as number | null,
    };
  }
  async alternatives(slot: Slot, _scenario: Scenario) {
    return (await this.browseItems(slot, "")).items;
  }
  async optimize(
    scenario: Scenario,
    signal: AbortSignal,
  ): Promise<OptimizationReply> {
    const submitted = structuredClone(scenario);
    const response = await this.transport(`${this.base}/optimizations`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(optimizationRequest(submitted)),
    });
    const body = await response.json();
    if (!response.ok) {
      const error = object(object(body).error);
      const fields = Array.isArray(error.fields)
        ? error.fields
            .map((f) => {
              const row = object(f);
              return `${row.field ?? row.path ?? "scenario"}: ${row.message}`;
            })
            .join("; ")
        : "";
      throw new GearApiError(
        `${typeof error.message === "string" ? error.message : `Optimization failed (${response.status})`}${fields ? ` · ${fields}` : ""}`,
        String(error.code ?? "optimization_failed"),
      );
    }
    return parseOptimization(body, submitted);
  }
  async evaluate(
    _result: OptimizationReply,
    _solution: string,
    _role: string,
    _equipment: Equipment,
  ): Promise<Trial> {
    throw new Error("Live equipment evaluation is unavailable.");
  }
}
