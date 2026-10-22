import { emptyEquipment, slots } from "./contracts";
import type {
  ContextDTO,
  Equipment,
  GearClient,
  GearContext,
  Item,
  ItemPage,
  OptimizationReply,
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
    _scenario: Scenario,
    _signal: AbortSignal,
  ): Promise<OptimizationReply> {
    throw new Error(
      "Live optimization is unavailable until Milestone 3. Open fixture mode for demonstrations.",
    );
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
