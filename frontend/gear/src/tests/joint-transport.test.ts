import { expect, it, vi } from "vitest";
import {
  HttpGearClient,
  optimizationRequest,
  parseOptimization,
} from "../api/httpClient";
import { newDraft, newRole, normalize } from "../state/scenario";
import context from "./live-context.json";
import { parseJointSolution } from "../api/jointResults";
import { parseItem } from "../api/httpClient";
import type { JointSolutionDTO } from "../api/contracts";
const performance = {
  supported: true,
  dps: 2,
  max_hit: 10,
  accuracy: 0.5,
  attack_interval: 2.4,
  bonuses: {},
  limitations: [],
};
function example(count = 2) {
  const draft = newDraft();
  draft.roles = Array.from({ length: count }, (_, i) => newRole(i + 1));
  draft.maxActions = "1";
  const scenario = normalize(draft, context.account.snapshot_id, true);
  const solution = {
    score: 2,
    loadouts: Object.fromEntries(
      scenario.request.roles.map((r) => [
        r.id,
        {
          equipment: { weapon: 4151 },
          performance: structuredClone(performance),
        },
      ]),
    ),
    purchases: [],
    purchase_cost_gp: 0,
    transitions: scenario.request.transitions.map(([from_role, to_role]) => ({
      from_role,
      to_role,
      actions: [],
      action_count: 0,
      changed_slots: 0,
      max_gear_inventory_slots: 0,
    })),
    carried_item_ids: [4151],
    distinct_items: 1,
    gear_inventory_slots: 0,
    max_gear_inventory_slots: 0,
    remaining_supply_slots: 28,
    remaining_inventory_slots: 16,
    reserved_supply_slots: 12,
    maximum_actions: 0,
  };
  const reply = {
    api_version: "gear-ui-v1",
    evaluated_at: context.evaluated_at,
    scenario: optimizationRequest(scenario),
    scenario_fingerprint: "joint",
    price_revision: context.price_revision,
    items: context.items,
    baseline: {
      status: "unavailable",
      equipment: {},
      performance: null,
      reasons: ["Joint baseline unavailable"],
    },
    result: {
      snapshot_id: scenario.request.expected_snapshot_id,
      catalog_version: context.catalog_version,
      model_version: context.model_version,
      assumptions_fingerprint: "assumptions",
      search: { quality: "best_found" },
      limitations: [],
      active_time_shares: Object.fromEntries(
        scenario.request.roles.map((r) => [r.id, 1 / count]),
      ),
      curve: [0, 1].map((swap_limit) => ({
        swap_limit,
        status: "best_found",
        solution,
        relative_performance: 1,
      })),
      unrestricted: solution,
      selected_solution: solution,
    },
  };
  return { scenario, reply };
}
it.each([2, 3, 4])(
  "validates %i-role secondary priority provenance and values",
  (count) => {
    const { scenario, reply } = example(count);
    scenario.request.secondary_priority = "prayer_bonus";
    reply.scenario = optimizationRequest(scenario);
    Object.assign(reply, { secondary_priority: "prayer_bonus" });
    Object.assign(reply.result, { secondary_priority: "prayer_bonus" });
    Object.assign(reply.result.selected_solution, {
      secondary_priority: "prayer_bonus",
      secondary_value: 12.5,
    });
    expect(
      parseOptimization(reply, scenario).solutions[0].live?.secondary_value,
    ).toBe(12.5);
    for (const row of [reply, reply.result, reply.result.selected_solution]) {
      Object.assign(row, { secondary_priority: "accuracy" });
      expect(() => parseOptimization(reply, scenario)).toThrow(/priority/);
      Object.assign(row, { secondary_priority: "prayer_bonus" });
    }
    Object.assign(reply.result.selected_solution, { secondary_value: null });
    expect(() => parseOptimization(reply, scenario)).toThrow(/value/);
  },
);
it.each([2, 3, 4])(
  "retains all %i joint roles, curve points and unrestricted reference",
  (count) => {
    const { scenario, reply } = example(count);
    const result = parseOptimization(reply, scenario);
    expect(result.solutions.map((s) => s.id)).toEqual(["curve-0", "curve-1"]);
    expect(result.selectedSolutionId).toBe("curve-1");
    expect(result.solutions[0].loadouts).toHaveLength(count);
    expect(result.solutions[0].shared).toEqual([4151]);
    expect(result.unrestricted?.live).toEqual(reply.result.unrestricted);
  },
);
it("rejects malformed joint identity and inventory facts", () => {
  const { scenario, reply } = example();
  reply.result.selected_solution.remaining_inventory_slots = 17;
  expect(() => parseOptimization(reply, scenario)).toThrow(/inventory/);
});
it("keeps unsupported utility metrics unavailable and refuses joint manual evaluation", async () => {
  const { scenario, reply } = example();
  scenario.request.roles[1].utility = true;
  reply.scenario = optimizationRequest(scenario);
  reply.result.active_time_shares = { "role-1": 1 };
  Object.assign(reply.result.selected_solution.loadouts["role-2"].performance, {
    supported: true,
    dps: null,
    max_hit: null,
    accuracy: null,
    attack_interval: null,
    limitations: ["Utility is unscored"],
  });
  const result = parseOptimization(reply, scenario);
  expect(result.solutions[0].loadouts[1].metrics).toBeNull();
  const transport = vi.fn();
  const client = new HttpGearClient("/ui-api/gear", transport);
  await expect(
    client.evaluate(
      result,
      "curve-1",
      "role-1",
      result.solutions[0].loadouts[0].equipment,
    ),
  ).rejects.toThrow(/multi-role/);
  expect(transport).not.toHaveBeenCalled();
});

function withActions() {
  const { scenario, reply } = example();
  const raw = structuredClone(
    reply.result.selected_solution,
  ) as JointSolutionDTO;
  raw.loadouts["role-2"].equipment = {};
  raw.transitions = [
    {
      from_role: "role-1",
      to_role: "role-2",
      actions: [
        {
          operation: "unequip",
          slot: "weapon",
          item_id: 4151,
          automatically_removed: [],
          gear_inventory_slots: 1,
        },
      ],
      action_count: 1,
      changed_slots: 1,
      max_gear_inventory_slots: 1,
    },
  ];
  Object.assign(raw, {
    maximum_actions: 1,
    max_gear_inventory_slots: 1,
    remaining_supply_slots: 27,
    remaining_inventory_slots: 15,
    purchases: [{ item_id: 4151, cost_gp: 1000, conditional: true }],
    purchase_cost_gp: 1000,
  });
  return { scenario, raw, items: context.items.map(parseItem) };
}
it("retains authoritative equipment actions and counts separately from gear inventory", () => {
  const { scenario, raw, items } = withActions();
  const parsed = parseJointSolution(raw, scenario, items, "curve-1", 1);
  expect(parsed.transitions[0].actions).toEqual([
    "unequip Abyssal whip (weapon)",
  ]);
  expect(parsed.live?.transitions[0].actions).toEqual(
    raw.transitions[0].actions,
  );
  expect(parsed.purchases).toEqual([4151]);
  expect(parsed.shared).toEqual([]);
});
const invalidSolutions: [string, (raw: JointSolutionDTO) => void][] = [
  [
    "negative occupancy",
    (r) => {
      r.gear_inventory_slots = -1;
    },
  ],
  [
    "invalid score",
    (r) => {
      r.score = NaN;
    },
  ],
  [
    "missing role",
    (r) => {
      delete r.loadouts["role-2"];
    },
  ],
  [
    "missing metadata",
    (r) => {
      r.loadouts["role-1"].equipment.weapon = 99999;
    },
  ],
  [
    "invalid role metrics",
    (r) => {
      Object.assign(r.loadouts["role-1"].performance, { supported: false });
    },
  ],
  [
    "invalid limitations",
    (r) => {
      Object.assign(r.loadouts["role-1"].performance, { limitations: null });
    },
  ],
  [
    "incorrect required union",
    (r) => {
      r.carried_item_ids = [];
    },
  ],
  [
    "unknown purchase",
    (r) => {
      r.purchases[0].item_id = 99999;
    },
  ],
  [
    "duplicate purchase",
    (r) => {
      r.purchases.push({ ...r.purchases[0] });
    },
  ],
  [
    "invalid price",
    (r) => {
      r.purchases[0].cost_gp = -1;
    },
  ],
  [
    "unknown transition role",
    (r) => {
      r.transitions[0].to_role = "missing";
    },
  ],
  [
    "incorrect action count",
    (r) => {
      r.transitions[0].action_count = 2;
    },
  ],
  [
    "invalid action operation",
    (r) => {
      Object.assign(r.transitions[0].actions[0], { operation: "invent" });
    },
  ],
  [
    "invalid action slot",
    (r) => {
      r.transitions[0].actions[0].slot = "invent";
    },
  ],
  [
    "invalid removed identity",
    (r) => {
      r.transitions[0].actions[0].automatically_removed = [99999];
    },
  ],
  [
    "invalid action inventory",
    (r) => {
      r.transitions[0].actions[0].gear_inventory_slots = -1;
    },
  ],
  [
    "invalid action limit",
    (r) => {
      r.maximum_actions = 2;
    },
  ],
];
it.each(invalidSolutions)("rejects %s", (_name, mutate) => {
  const { scenario, raw, items } = withActions();
  mutate(raw);
  expect(() =>
    parseJointSolution(raw, scenario, items, "curve-1", 1),
  ).toThrow();
});
it("accepts unscored unsupported ordinary metrics without inventing zero performance", () => {
  const { scenario, raw, items } = withActions();
  Object.assign(raw.loadouts["role-2"].performance, {
    supported: false,
    dps: null,
    max_hit: null,
    accuracy: null,
    attack_interval: null,
  });
  expect(
    parseJointSolution(raw, scenario, items, "curve-1", 1).loadouts[1].metrics,
  ).toBeNull();
});
