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
import { workBudgetPolicy } from "../api/optimizationModes";
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

it("accepts one market purchase for a prepared staff shared by both roles", () => {
  const { scenario, reply } = example();
  const raw = structuredClone(
    reply.result.selected_solution,
  ) as JointSolutionDTO;
  const preparation = {
    source_item_id: null,
    usable_item_id: 28585,
    market_item_id: 28583,
    charging_required: true,
    charges: "unknown" as const,
    activation_reserve: [],
    message: "Charging required",
  };
  for (const loadout of Object.values(raw.loadouts)) {
    loadout.equipment = { weapon: 28585 };
    loadout.preparations = [preparation];
  }
  raw.carried_item_ids = [28585];
  raw.purchases = [{ item_id: 28583, cost_gp: 92542, conditional: true }];
  raw.purchase_cost_gp = 92542;
  const original = context.items.map(parseItem).find((i) => i.id === 4151)!;
  const items = [
    {
      ...original,
      id: 28585,
      name: "Warped sceptre",
      facts: {
        ...original.facts!,
        item_id: 28585,
        numeric_item_id: 28585,
        preparation,
      },
    },
  ];
  const parsed = parseJointSolution(raw, scenario, items, "curve-1", 1);
  expect(parsed.purchases).toEqual([28583]);
  expect(parsed.shared).toEqual([28585]);
  expect(parsed.cost).toBe(92542);
  raw.purchases.push(raw.purchases[0]);
  expect(() => parseJointSolution(raw, scenario, items, "curve-1", 1)).toThrow(
    /purchase union/,
  );
  raw.purchases = [{ item_id: 123, cost_gp: 1, conditional: false }];
  expect(() => parseJointSolution(raw, scenario, items, "curve-1", 1)).toThrow(
    /purchase union/,
  );
  raw.purchases = [{ item_id: 28585, cost_gp: 92542, conditional: true }];
  expect(() => parseJointSolution(raw, scenario, items, "curve-1", 1)).toThrow(
    /purchase union/,
  );
  raw.purchases = [{ item_id: 28583, cost_gp: 92542, conditional: true }];
  Object.assign(raw.loadouts["role-1"], { preparations: preparation });
  expect(() => parseJointSolution(raw, scenario, items, "curve-1", 1)).toThrow(
    /preparation/,
  );
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

function autoExample() {
  const { scenario, reply } = example(1);
  scenario.request.roles[0].autoDiscipline = true;
  scenario.request.roles[0].allowedDisciplines = ["melee"];
  reply.scenario = optimizationRequest(scenario);
  Object.assign(reply.result.selected_solution.loadouts["role-1"], {
    discipline: "melee",
  });
  const branch = {
    discipline: "melee",
    status: "best_found",
    reasons: [],
    score: 2,
    purchase_cost_gp: 0,
    selected_solution: structuredClone(reply.result.selected_solution),
    secondary_frontiers: [],
    search: {},
    alternatives: {},
    limitations: [],
  };
  Object.assign(reply.result, {
    discipline_comparison: [
      {
        discipline: "melee",
        status: "best_found",
        reasons: [],
        score: 2,
        purchase_cost_gp: 0,
      },
    ],
    discipline_results: [branch],
  });
  return { scenario, reply, branch };
}

function multiAutoExample(autoIndex = 0) {
  const { scenario, reply } = example();
  scenario.request.roles[autoIndex].autoDiscipline = true;
  scenario.request.roles[autoIndex].allowedDisciplines = ["melee", "ranged"];
  reply.scenario = optimizationRequest(scenario);
  Object.assign(
    reply.result.selected_solution.loadouts[`role-${autoIndex + 1}`],
    {
      discipline: "melee",
    },
  );
  const policy = {
    ...workBudgetPolicy("fast"),
    budget_scope: "per_discipline_assignment",
    discipline_assignment_count: 2,
  };
  const fixed = autoIndex === 0 ? "ranged" : "melee";
  Object.assign(reply, { work_budget_policy: policy });
  Object.assign(reply.result, {
    work_budget_policy: policy,
    discipline_comparison: [],
    discipline_results: [],
    search: {
      discipline_assignment_selection: {
        policy: "full-per-discipline-assignment-v1",
        branch_count: 2,
        branches: Object.fromEntries(
          ["melee", "ranged"].map((discipline) => [
            autoIndex === 0
              ? `role-1=${discipline}/role-2=${fixed}`
              : `role-1=${fixed}/role-2=${discipline}`,
            {},
          ]),
        ),
      },
    },
  });
  return { scenario, reply };
}

it.each([0, 1])(
  "accepts combined Auto results with Auto in role %i",
  (autoIndex) => {
    const { scenario, reply } = multiAutoExample(autoIndex);
    const parsed = parseOptimization(reply, scenario);
    expect(parsed.solutions.map((s) => s.id)).toEqual(["curve-0", "curve-1"]);
    expect(parsed.solutions[0].loadouts[autoIndex].discipline).toBe("melee");
    expect(
      optimizationRequest(scenario).roles[autoIndex].allowed_disciplines,
    ).toEqual(["melee", "ranged"]);
  },
);

it("rejects incomplete Multi Auto assignment diagnostics and changed work counts", () => {
  const { scenario, reply } = multiAutoExample();
  const search = reply.result.search as unknown as {
    discipline_assignment_selection: {
      branch_count: number;
      branches: Record<string, unknown>;
    };
  };
  delete search.discipline_assignment_selection.branches[
    "role-1=ranged/role-2=ranged"
  ];
  expect(() => parseOptimization(reply, scenario)).toThrow(/assignment/i);
  const valid = multiAutoExample();
  Object.assign(valid.reply, {
    work_budget_policy: {
      ...workBudgetPolicy("fast"),
      budget_scope: "per_discipline_assignment",
      discipline_assignment_count: 1,
    },
  });
  expect(() => parseOptimization(valid.reply, valid.scenario)).toThrow(
    /budget/i,
  );
});

it("rejects disallowed resolved disciplines in every combined point", () => {
  const { scenario, reply } = multiAutoExample(1);
  Object.assign(reply.result.selected_solution.loadouts["role-2"], {
    discipline: "magic",
  });
  expect(() => parseOptimization(reply, scenario)).toThrow(/discipline/i);
});

it("validates Thorough work separately for every discipline assignment", () => {
  const { scenario, reply } = multiAutoExample(1);
  scenario.request.optimization_mode = "thorough";
  reply.scenario = optimizationRequest(scenario);
  const policy = {
    ...workBudgetPolicy("thorough"),
    budget_scope: "per_discipline_assignment",
    discipline_assignment_count: 2,
  };
  for (const row of [reply, reply.result])
    Object.assign(row, {
      optimization_mode: "thorough",
      work_budget_policy: policy,
    });
  const diagnostic = {
    triggered: false,
    assignment_attempts: 0,
    work_budget_exhausted: false,
    objective_improvements: 0,
    tie_improvements: 0,
    baseline: { curve_solutions: [null, null], unrestricted: null },
  };
  const branches = {
    "role-1=melee/role-2=melee": {
      local_refinement: structuredClone(diagnostic),
    },
    "role-1=melee/role-2=ranged": {
      local_refinement: structuredClone(diagnostic),
    },
  };
  Object.assign(reply.result.search, {
    discipline_assignment_selection: {
      policy: "full-per-discipline-assignment-v1",
      branch_count: 2,
      branches,
    },
  });
  expect(() => parseOptimization(reply, scenario)).not.toThrow();
  branches["role-1=melee/role-2=ranged"].local_refinement.assignment_attempts =
    10001;
  expect(() => parseOptimization(reply, scenario)).toThrow(/assignment cap/i);
});
it("retains each Auto discipline as an independently selectable solution", () => {
  const { scenario, reply } = autoExample();
  const parsed = parseOptimization(reply, scenario);
  expect(parsed.solutions.map((s) => s.id)).toContain(
    "discipline-melee-best-found",
  );
});
it("rejects duplicate, unsearched, and mismatched Auto discipline results", () => {
  const { scenario, reply, branch } = autoExample();
  Object.assign(reply.result, { discipline_results: [branch, branch] });
  expect(() => parseOptimization(reply, scenario)).toThrow(/discipline/i);
  Object.assign(reply.result, {
    discipline_results: [{ ...branch, discipline: "magic" }],
  });
  expect(() => parseOptimization(reply, scenario)).toThrow(/discipline/i);
  Object.assign(reply.result, { discipline_results: [branch] });
  branch.selected_solution.loadouts["role-1"] = {
    ...branch.selected_solution.loadouts["role-1"],
    discipline: "magic",
  } as (typeof branch.selected_solution.loadouts)[string];
  expect(() => parseOptimization(reply, scenario)).toThrow(/discipline/i);
});
it("retains independently scoped Auto frontiers and validates their identities and measurements", () => {
  const { scenario, reply, branch } = autoExample();
  const point = {
    id: "discipline-melee-frontier-1-test",
    solution: branch.selected_solution,
    dps_loss: 0,
    dps_loss_pct: 0,
    secondary_gain: 0,
  };
  Object.assign(branch, {
    secondary_frontiers: [
      { swap_limit: 1, baseline_dps: 2, sampled: false, points: [point] },
    ],
  });
  expect(
    parseOptimization(reply, scenario).solutions.map((s) => s.id),
  ).toContain(point.id);
  point.id = "unscoped";
  expect(() => parseOptimization(reply, scenario)).toThrow(
    /discipline frontier/,
  );
  point.id = "discipline-melee-frontier-1-test";
  point.dps_loss_pct = 101;
  expect(() => parseOptimization(reply, scenario)).toThrow(/measurement/);
  point.dps_loss_pct = 0;
  Object.assign(point, {
    solution: {
      ...branch.selected_solution,
      loadouts: {
        "role-1": {
          ...branch.selected_solution.loadouts["role-1"],
          discipline: "magic",
        },
      },
    },
  });
  expect(() => parseOptimization(reply, scenario)).toThrow(
    /frontier discipline/,
  );
});
it("accepts the same potion loadout at different caps with distinct point identities", () => {
  const { scenario, reply, branch } = autoExample();
  const groups = [0, 1, null].map((swap_limit) => ({
    swap_limit,
    baseline_dps: 2,
    sampled: false,
    points: [
      {
        id: `discipline-melee-potion-${swap_limit === null ? "None" : swap_limit}-same-loadout`,
        solution: branch.selected_solution,
        dps_loss: 0,
        dps_loss_pct: 0,
        secondary_gain: 0,
      },
    ],
  }));
  Object.assign(branch, { secondary_frontiers: groups });
  const parsed = parseOptimization(reply, scenario);
  for (const group of groups)
    expect(parsed.solutions.map((solution) => solution.id)).toContain(
      group.points[0].id,
    );
  groups[1].points[0].id = groups[0].points[0].id;
  expect(() => parseOptimization(reply, scenario)).toThrow(
    "Invalid frontier measurement",
  );
});
it("retains an infeasible Auto discipline with no selectable setup", () => {
  const { scenario, reply, branch } = autoExample();
  Object.assign(branch, {
    status: "no_feasible_solution_found",
    selected_solution: null,
    score: null,
    purchase_cost_gp: null,
    reasons: ["No legal setup"],
  });
  Object.assign(reply.result, {
    discipline_comparison: [
      {
        discipline: "melee",
        status: "no_feasible_solution_found",
        score: null,
        purchase_cost_gp: null,
        reasons: ["No legal setup"],
      },
    ],
  });
  expect(
    parseOptimization(reply, scenario).solutions.map((s) => s.id),
  ).not.toContain("discipline-melee-best-found");
  Object.assign(branch, { status: "best_found" });
  expect(() => parseOptimization(reply, scenario)).toThrow(/discipline/);
});
