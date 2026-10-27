import type {
  Equipment,
  FixtureFailure,
  GearClient,
  GearContext,
  Item,
  Metrics,
  Scenario,
  Slot,
  Solution,
  Style,
} from "../api/contracts";
import { slots } from "../api/contracts";
const rows: [number, string, Slot, boolean, number | null][] = [
  [10828, "Helm of neitiznot", "head", true, 50000],
  [6585, "Amulet of fury", "neck", true, 1500000],
  [6570, "Fire cape", "cape", true, null],
  [892, "Rune arrow", "ammo", true, 100],
  [4151, "Abyssal whip", "weapon", true, 1300000],
  [9185, "Rune crossbow", "weapon", true, 10000],
  [12002, "Occult necklace", "neck", true, 500000],
  [861, "Magic shortbow", "weapon", true, 1000],
  [2415, "Guthix staff", "weapon", true, 80000],
  [10551, "Fighter torso", "body", true, null],
  [2503, "Black dragonhide body", "body", true, 8000],
  [11924, "Malediction ward", "shield", true, 900000],
  [12954, "Dragon defender", "shield", true, null],
  [1079, "Rune platelegs", "legs", true, 38000],
  [2497, "Black dragonhide chaps", "legs", true, 4000],
  [7462, "Barrows gloves", "hands", true, 130000],
  [11840, "Dragon boots", "feet", true, 140000],
  [6737, "Berserker ring", "ring", true, 2000000],
  [11785, "Armadyl crossbow", "weapon", false, 18000000],
  [11832, "Bandos chestplate", "body", false, 28000000],
  [10499, "Ava's accumulator", "cape", true, null],
];
export const items: Item[] = rows.map(([id, name, slot, owned, price]) => ({
  id,
  name,
  slot,
  owned,
  price,
  requirement:
    "Illustrative eligibility only · no account requirements verified",
}));
export const itemById = (id: number | null) =>
  items.find((item) => item.id === id);
export const baseline: Equipment = {
  head: 10828,
  cape: 6570,
  neck: 6585,
  ammo: null,
  weapon: 4151,
  body: 10551,
  shield: 12954,
  legs: 1079,
  hands: 7462,
  feet: 11840,
  ring: 6737,
};
export const contextFixture: GearContext = {
  playerId: "fixture-player-v1",
  displayName: "Demo adventurer",
  snapshotId: "fixture-snapshot-01",
  observedAt: "2026-10-22T12:00:00Z",
  items,
  equipment: baseline,
  equipmentStatus: "observed",
  source: "fixture",
};
const performance = (style: Style): Metrics =>
  style === "melee"
    ? { dps: 5.66, maxHit: 36, accuracy: 0.558, ticks: 4 }
    : style === "ranged"
      ? { dps: 5.12, maxHit: 32, accuracy: 0.61, ticks: 5 }
      : { dps: 4.38, maxHit: 20, accuracy: 0.72, ticks: 5 };
// Fixture metrics are authored examples, never combat calculations or predicted account output.
export function makeSolution(scenario: Scenario, compact = false): Solution {
  const loadouts = scenario.request.roles.map((role) => {
    let equipment: Equipment = { ...baseline };
    if (role.style === "ranged")
      equipment = {
        ...equipment,
        cape: 10499,
        weapon: 9185,
        body: 2503,
        legs: 2497,
        ammo: 892,
      };
    if (role.style === "magic")
      equipment = { ...equipment, weapon: 2415, neck: 12002, shield: 11924 };
    if (compact) equipment = { ...baseline, weapon: equipment.weapon };
    for (const slot of slots) {
      if (scenario.request.excluded_item_ids.includes(equipment[slot] ?? -1))
        equipment[slot] = null;
      if (slot in role.locks) equipment[slot] = role.locks[slot] ?? null;
    }
    return {
      roleId: role.id,
      name: role.name,
      equipment,
      metrics: {
        ...performance(role.style),
        dps: performance(role.style).dps - (compact ? 0.3 : 0),
      },
    };
  });
  const transitions = scenario.request.transitions.map(([from, to]) => {
    const a = loadouts.find((l) => l.roleId === from)!,
      b = loadouts.find((l) => l.roleId === to)!;
    const changed = slots.filter((s) => a.equipment[s] !== b.equipment[s]);
    const actions = changed.map((s) =>
      b.equipment[s] === null
        ? `Remove ${itemById(a.equipment[s])?.name ?? s} from ${s}`
        : `Equip ${itemById(b.equipment[s])?.name ?? s} in ${s}`,
    );
    return {
      from,
      to,
      actions,
      changedSlots: changed.length,
      peak: changed.length,
    };
  });
  const allIds = [
    ...new Set(
      loadouts
        .flatMap((l) => Object.values(l.equipment))
        .filter((id): id is number => id !== null),
    ),
  ];
  const purchases = allIds.filter((id) => !itemById(id)?.owned);
  return {
    id: compact ? "compact" : "best-found",
    actionLimit: compact ? 2 : 8,
    loadouts,
    weightedDps:
      loadouts.reduce(
        (sum, l, i) => sum + l.metrics.dps * scenario.request.roles[i].weight,
        0,
      ) / scenario.request.roles.reduce((sum, r) => sum + r.weight, 0),
    purchases,
    cost: purchases.reduce((sum, id) => sum + (itemById(id)?.price ?? 0), 0),
    shared: allIds.filter(
      (id) =>
        loadouts.length > 1 &&
        loadouts.every((l) => Object.values(l.equipment).includes(id)),
    ),
    transitions,
  };
}
export class FixtureGearClient implements GearClient {
  public equipmentStatus: GearContext["equipmentStatus"] = "observed";
  constructor(
    public failure: FixtureFailure = "none",
    private delay = 350,
    private contextError = false,
  ) {}
  async getContext() {
    if (this.contextError)
      throw new Error("Fixture context unavailable. Retry loading the demo.");
    return {
      ...structuredClone(contextFixture),
      equipmentStatus: this.equipmentStatus,
    };
  }
  async getItem(id: number) {
    const item = itemById(id);
    if (!item) throw new Error("Unknown fixture item");
    return structuredClone(item);
  }
  async alternatives(slot: Slot, _scenario: Scenario) {
    return structuredClone(items.filter((i) => i.slot === slot));
  }
  async optimize(scenario: Scenario, signal: AbortSignal) {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, this.delay);
      signal.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          reject(new DOMException("Cancelled", "AbortError"));
        },
        { once: true },
      );
    });
    if (this.failure === "busy")
      throw new Error("Fixture optimizer busy. Retry the simulation.");
    if (this.failure === "error")
      throw new Error("Simulated fixture failure. Your draft is preserved.");
    return {
      source: "fixture" as const,
      scenario: structuredClone(scenario),
      fingerprint: JSON.stringify(scenario),
      snapshotId: contextFixture.snapshotId,
      evaluatedAt: contextFixture.observedAt,
      catalogVersion: "fixture-catalog-v1",
      modelVersion: "illustrative-metrics-v1",
      priceRevision: "fixture-prices-v1",
      solutions:
        this.failure === "no-solution"
          ? []
          : [
              makeSolution(scenario),
              ...(scenario.request.roles.length > 1
                ? [makeSolution(scenario, true)]
                : []),
            ],
      warnings: [
        "Deterministic fixture only. Inputs are recorded but no optimization or combat calculation is performed.",
        "Ordinary-attack interface preview. No prayers, potions, special attacks, or survivability model.",
      ],
    };
  }
  async evaluate(
    result: Awaited<ReturnType<GearClient["optimize"]>>,
    solutionId: string,
    roleId: string,
    equipment: Equipment,
  ) {
    const loadout = result.solutions
      .find((s) => s.id === solutionId)!
      .loadouts.find((l) => l.roleId === roleId)!;
    if (!loadout.metrics)
      throw new Error("Unscored configurations cannot be manually evaluated.");
    return {
      source: "fixture" as const,
      resultFingerprint: result.fingerprint,
      solutionId,
      roleId,
      equipment: structuredClone(equipment),
      baseline: { ...loadout.metrics },
      proposed: { ...loadout.metrics, dps: loadout.metrics.dps + 0.18 },
    };
  }
}
