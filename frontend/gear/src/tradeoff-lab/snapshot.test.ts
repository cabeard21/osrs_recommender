import { afterEach, describe, expect, it, vi } from "vitest";
import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";
import {
  createLabSnapshot,
  loadLabSnapshot,
  selectedLabSolution,
  storeLabSnapshot,
} from "./snapshot";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

function solution(score = 4): JointSolutionDTO {
  return {
    score,
    objective_values: {
      accuracy: 0.75,
      prayer_bonus: 12,
      magic_damage_bonus: 3.5,
    },
    loadouts: {
      melee: {
        equipment: { weapon: 1333, cape: 20050 },
        performance: {
          supported: true,
          dps: score,
          max_hit: 20,
          accuracy: 0.75,
          attack_interval: 2.4,
          bonuses: {},
          limitations: [],
        },
        combat_option: {
          attack_type: "slash",
          stance: "accurate",
          spell: null,
          powered_attack: null,
        },
      },
    },
    purchases: [],
    purchase_cost_gp: 123,
    transitions: [],
    carried_item_ids: [1333, 20050],
    distinct_items: 2,
    gear_inventory_slots: 0,
    max_gear_inventory_slots: 0,
    remaining_supply_slots: 28,
    remaining_inventory_slots: 16,
    reserved_supply_slots: 12,
    maximum_actions: 0,
    potions: {
      selected_ids: ["combat"],
      resources: [{ name: "Combat potion", cost_per_dose_gp: 19 }],
      boosted_levels: {},
      cost_per_application_gp: 19,
      model_version: "fresh",
    },
  };
}

function setup() {
  const group = {
    id: "global-eight",
    swap_limit: 8,
    baseline_dps: 4,
    total_count: 50,
    sampled: true,
    points: [
      {
        id: "cap8-sample",
        solution: solution(3.6),
        dps_loss: 0.4,
        dps_loss_pct: 10,
      },
    ],
  };
  const result = {
    evaluatedAt: "2026-11-16T16:48:56Z",
    solutions: [{ id: "best-found", live: solution() }],
    scenario: {
      request: {
        budget_gp: 10_000_000,
        target: { name: "Animated Black Armour" },
        roles: [{ id: "melee", name: "Melee" }],
      },
    },
    live: {
      items: [
        { numeric_item_id: 1333, name: "Rune scimitar" },
        { numeric_item_id: 20050, name: "Obsidian cape (r)" },
      ],
      result: {
        objective_definitions: [
          { id: "accuracy", label: "Accuracy", unit: "probability" },
          { id: "prayer_bonus", label: "Prayer bonus", unit: "bonus" },
          { id: "magic_damage_bonus", label: "Magic damage", unit: "percent" },
        ],
        objective_frontiers: [
          group,
          {
            ...group,
            id: "global-zero",
            swap_limit: 0,
            points: [{ id: "wrong-cap", solution: solution(999) }],
          },
        ],
      },
    },
  } as unknown as OptimizationReply;
  return { result, group };
}

describe("live tradeoff lab snapshots", () => {
  it("resolves ordinary single-role and discipline selections whose parsed solutions omit live reports", () => {
    const { result, group } = setup();
    const selected = solution(4.5);
    const current = {
      ...result,
      solutions: [{ ...result.solutions[0], live: undefined }],
      live: {
        ...result.live!,
        result: { ...result.live!.result, selected_solution: selected },
      },
    };
    expect(selectedLabSolution(current, "best-found")).toBe(selected);
    expect(
      createLabSnapshot(current, group, "best-found").points.at(-1),
    ).toMatchObject({ id: "best-found", label: "Current selection", dps: 4.5 });
    const discipline = {
      ...current,
      live: {
        ...current.live,
        result: {
          ...current.live.result,
          discipline_results: [
            { discipline: "melee", selected_solution: selected },
          ],
        },
      },
    } as unknown as OptimizationReply;
    expect(selectedLabSolution(discipline, "discipline-melee-best-found")).toBe(
      selected,
    );
    expect(
      selectedLabSolution(discipline, "discipline-ranged-best-found"),
    ).toBeUndefined();
    expect(
      createLabSnapshot(discipline, group, "discipline-melee-best-found")
        .selectedId,
    ).toBe("discipline-melee-best-found");
  });

  it("includes the separately parsed unrestricted selection with its own values and equipment", () => {
    const { result, group } = setup();
    const unrestricted = {
      ...solution(4.8),
      objective_values: {
        accuracy: 0.91,
        prayer_bonus: 22,
        magic_damage_bonus: 8,
      },
      loadouts: {
        melee: { ...solution().loadouts.melee, equipment: { cape: 6568 } },
      },
      maximum_actions: 12,
    };
    const current = {
      ...result,
      unrestricted: {
        ...result.solutions[0],
        id: "unrestricted",
        live: unrestricted,
      },
    };
    const snapshot = createLabSnapshot(
      current,
      { ...group, swap_limit: null },
      "unrestricted",
    );
    expect(snapshot.selectedId).toBe("unrestricted");
    expect(snapshot.points.at(-1)).toMatchObject({
      label: "Current selection",
      values: {
        dps: 4.8,
        accuracy: 0.91,
        prayer_bonus: 22,
        magic_damage_bonus: 8,
      },
      equipment: [{ slot: "cape", itemId: 6568, name: "Item 6568" }],
    });
    expect(selectedLabSolution(current, "unrestricted")).toBe(unrestricted);
    expect(selectedLabSolution(current, "best-found")).toBe(
      result.solutions[0].live,
    );
    expect(selectedLabSolution(current, "missing")).toBeUndefined();
    const rawOnly = {
      ...result,
      live: {
        ...result.live!,
        result: { ...result.live!.result, unrestricted },
      },
    };
    expect(selectedLabSolution(rawOnly, "unrestricted")).toBe(unrestricted);
    expect(createLabSnapshot(current, group, "unrestricted").selectedId).toBe(
      "cap8-sample",
    );
  });

  it("describes effective per-role combat targets, including shared defaults and multiple targets", () => {
    const { result, group } = setup();
    const role = result.scenario.request.roles[0];
    const withRoles = (roles: typeof result.scenario.request.roles) => ({
      ...result,
      scenario: {
        ...result.scenario,
        request: { ...result.scenario.request, roles },
      },
    });
    const overridden = {
      ...role,
      combatTarget: { name: "Black demon" } as NonNullable<
        typeof role.combatTarget
      >,
    };
    expect(
      createLabSnapshot(withRoles([overridden]), group, "best-found").target,
    ).toBe("Black demon");
    expect(
      createLabSnapshot(
        withRoles([overridden, { ...overridden, id: "other" }]),
        group,
        "best-found",
      ).target,
    ).toBe("Black demon");
    expect(
      createLabSnapshot(
        withRoles([overridden, { ...role, id: "other" }]),
        group,
        "best-found",
      ).target,
    ).toBe("Multiple role targets: Black demon, Animated Black Armour");
    expect(createLabSnapshot(withRoles([]), group, "best-found").target).toBe(
      "Animated Black Armour",
    );
    const longTarget = {
      ...overridden,
      combatTarget: { ...overridden.combatTarget!, name: "x".repeat(600) },
    };
    expect(
      createLabSnapshot(withRoles([longTarget]), group, "best-found").target,
    ).toHaveLength(512);
  });

  it("copies the exact requested group, all objective values and current selection", () => {
    const { result, group } = setup();
    const before = JSON.stringify(result);
    const snapshot = createLabSnapshot(result, group, "best-found");
    expect(snapshot.points.map((p) => p.id)).toEqual([
      "cap8-sample",
      "best-found",
    ]);
    expect(snapshot.selectedId).toBe("best-found");
    expect(snapshot.points[1]).toMatchObject({
      label: "Current selection",
      dps: 4,
      costGp: 123,
      values: {
        dps: 4,
        accuracy: 0.75,
        prayer_bonus: 12,
        magic_damage_bonus: 3.5,
      },
      potions: ["Combat potion"],
      attackType: "slash",
      stance: "accurate",
    });
    expect(snapshot.points[1].equipment).toEqual([
      { slot: "cape", itemId: 20050, name: "Obsidian cape (r)" },
      { slot: "weapon", itemId: 1333, name: "Rune scimitar" },
    ]);
    expect(snapshot.metrics).toEqual([
      { key: "dps", label: "DPS", shortLabel: "DPS", unit: "dps" },
      {
        key: "accuracy",
        label: "Accuracy",
        shortLabel: "Accuracy",
        unit: "probability",
      },
      {
        key: "prayer_bonus",
        label: "Prayer bonus",
        shortLabel: "Prayer bonus",
        unit: "bonus",
      },
      {
        key: "magic_damage_bonus",
        label: "Magic damage",
        shortLabel: "Magic damage",
        unit: "percent",
      },
    ]);
    expect(snapshot).toMatchObject({
      target: "Animated Black Armour",
      totalCount: 50,
      sampleCount: 1,
      sampled: true,
      budgetGp: 10_000_000,
    });
    expect(snapshot.scope).toContain("8");
    expect(JSON.stringify(result)).toBe(before);
  });

  it("uses group selections directly and labels equipment slots by role for joint setups", () => {
    const { result, group } = setup();
    const second = {
      ...group.points[0].solution.loadouts.melee,
      equipment: { weapon: 1333 },
    };
    const joint = {
      ...group,
      points: [
        {
          ...group.points[0],
          solution: {
            ...group.points[0].solution,
            loadouts: {
              melee: group.points[0].solution.loadouts.melee,
              ranged: second,
            },
          },
        },
      ],
    };
    const snapshot = createLabSnapshot(result, joint, "cap8-sample");
    expect(snapshot.selectedId).toBe("cap8-sample");
    expect(snapshot.points).toHaveLength(1);
    expect(snapshot.points[0].equipment.map((e) => e.slot)).toEqual([
      "Melee [melee] · cape",
      "Melee [melee] · weapon",
      "ranged [ranged] · weapon",
    ]);
  });

  it("falls back to a saved point without claiming it is the missing selection", () => {
    const { result, group } = setup();
    const snapshot = createLabSnapshot(result, group, "missing");
    expect(snapshot.selectedId).toBe("cap8-sample");
    expect(snapshot.points[0].label).toBe("Loadout 001");
    expect(snapshot.sourceDescription).toMatch(/selection.*unavailable/i);
    expect(() =>
      createLabSnapshot(result, { ...group, points: [] }, "missing"),
    ).toThrow(/no saved configurations/i);
  });

  it("rejects unavailable objective values instead of inventing zero measurements", () => {
    const { result, group } = setup();
    const broken = {
      ...group,
      points: [
        {
          ...group.points[0],
          solution: {
            ...group.points[0].solution,
            objective_values: { accuracy: NaN },
          },
        },
      ],
    };
    expect(() => createLabSnapshot(result, broken, "cap8-sample")).toThrow(
      /objective value/i,
    );
  });

  it("keeps unknown physical item IDs distinct and uses readable potion fallbacks", () => {
    const { result, group } = setup();
    const raw = {
      ...group.points[0].solution,
      potions: { ...group.points[0].solution.potions!, resources: undefined },
      loadouts: {
        melee: {
          ...group.points[0].solution.loadouts.melee,
          equipment: { cape: 6568 },
          combat_option: undefined,
        },
      },
    };
    const snapshot = createLabSnapshot(
      result,
      { ...group, points: [{ ...group.points[0], solution: raw }] },
      "cap8-sample",
    );
    expect(snapshot.points[0].equipment).toEqual([
      { slot: "cape", itemId: 6568, name: "Item 6568" },
    ]);
    expect(snapshot.points[0].potions).toEqual(["combat"]);
    expect(snapshot.points[0].attackType).toBe("Unavailable");
  });

  it("round-trips valid sessions and preserves unrelated browser storage", () => {
    const { result, group } = setup();
    const snapshot = createLabSnapshot(result, group, "best-found");
    localStorage.setItem("unrelated", "keep");
    const token = storeLabSnapshot(snapshot);
    expect(loadLabSnapshot(token)).toEqual(snapshot);
    expect(localStorage.getItem("unrelated")).toBe("keep");
  });

  it("retains only the three newest handoffs and removes expired handoffs", () => {
    const { result, group } = setup();
    const snapshot = createLabSnapshot(result, group, "best-found");
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000_000);
    const oldest = storeLabSnapshot(snapshot);
    const tokens = [1, 2, 3].map((n) => {
      now.mockReturnValue(1_000_000 + n);
      return storeLabSnapshot(snapshot);
    });
    expect(() => loadLabSnapshot(oldest)).toThrow(/unavailable/i);
    for (const token of tokens)
      expect(loadLabSnapshot(token)).toEqual(snapshot);
    now.mockReturnValue(1_000_000 + 2 * 60 * 60 * 1000 + 10);
    expect(() => loadLabSnapshot(tokens[0])).toThrow(/expired/i);
    storeLabSnapshot(snapshot);
    expect(localStorage.length).toBe(1);
  });

  it("shows clear errors for invalid, absent, corrupted and incompatible sessions", () => {
    expect(() => loadLabSnapshot("../elsewhere")).toThrow(/invalid/i);
    const token = "00000000-0000-4000-8000-000000000000";
    expect(() => loadLabSnapshot(token)).toThrow(/unavailable/i);
    localStorage.setItem(`gear-tradeoff-lab:${token}`, "not-json");
    expect(() => loadLabSnapshot(token)).toThrow(/invalid/i);
    localStorage.setItem(
      `gear-tradeoff-lab:${token}`,
      JSON.stringify({ version: 99 }),
    );
    expect(() => loadLabSnapshot(token)).toThrow(/invalid/i);
  });

  it("validates stored metric values and rejects quota failures with an actionable message", () => {
    const { result, group } = setup();
    const snapshot = createLabSnapshot(result, group, "best-found");
    const token = storeLabSnapshot(snapshot);
    const key = `gear-tradeoff-lab:${token}`;
    const envelope = JSON.parse(localStorage.getItem(key)!);
    envelope.snapshot.points[0].values.accuracy = null;
    localStorage.setItem(key, JSON.stringify(envelope));
    expect(() => loadLabSnapshot(token)).toThrow(/invalid/i);
    const blocked = {
      setItem: () => {
        throw new Error("quota");
      },
      getItem: () => null,
      removeItem: () => {},
      clear: () => {},
      key: () => null,
      length: 0,
    } as Storage;
    expect(() => storeLabSnapshot(snapshot, blocked)).toThrow(
      /browser storage/i,
    );
    expect(() =>
      loadLabSnapshot(token, {
        ...blocked,
        getItem: () => {
          throw new Error("blocked");
        },
      }),
    ).toThrow(/browser storage/i);
  });
});
