import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LiveMultiResultWorkspace } from "../components/LiveMultiResultWorkspace";
import { useGear } from "../state/GearProvider";
import { emptyEquipment } from "../api/contracts";
import { parseContext } from "../api/httpClient";
import context from "./live-context.json";

vi.mock("../state/GearProvider", () => ({ useGear: vi.fn() }));

const performance = (dps: number) => ({
  supported: true,
  dps,
  max_hit: 10,
  accuracy: 0.75,
  attack_interval: 2.4,
  bonuses: {},
  limitations: [],
});
function jointSolution(limit: number) {
  const equipment = limit ? { weapon: 3, neck: 9 } : { weapon: 1, neck: 9 };
  return {
    score: limit ? 4.5 : 2.5,
    loadouts: {
      a: {
        equipment: { weapon: 1, shield: 2, neck: 9 },
        performance: performance(limit ? 4 : 2),
      },
      b: { equipment, performance: performance(limit ? 5 : 3) },
      c: { equipment: { weapon: 4, neck: 9 }, performance: performance(1) },
      d: { equipment: { weapon: 1, neck: 9 }, performance: performance(2) },
    },
    purchases: limit ? [{ item_id: 3, cost_gp: 250, conditional: true }] : [],
    purchase_cost_gp: limit ? 250 : 0,
    carried_item_ids: limit ? [1, 2, 3, 4, 9] : [1, 2, 4, 9],
    distinct_items: limit ? 5 : 4,
    gear_inventory_slots: limit ? 2 : 1,
    max_gear_inventory_slots: limit ? 3 : 2,
    remaining_supply_slots: limit ? 25 : 26,
    remaining_inventory_slots: limit ? 13 : 14,
    reserved_supply_slots: 12,
    maximum_actions: limit ? 1 : 0,
    transitions: [
      {
        from_role: "a",
        to_role: "b",
        action_count: limit ? 1 : 0,
        changed_slots: limit ? 2 : 1,
        max_gear_inventory_slots: limit ? 3 : 2,
        actions: limit
          ? [
              {
                operation: "equip",
                slot: "weapon",
                item_id: 3,
                automatically_removed: [1, 2],
                gear_inventory_slots: 3,
              },
            ]
          : [],
      },
    ],
  };
}
function setup({
  roles = 3,
  selected = "curve-1",
  missing = false,
  outdated = false,
  utility = false,
} = {}) {
  const submittedRoles = ["a", "b", "c", "d"].slice(0, roles).map((id, i) => ({
    id,
    name: ["Blade", "Bow", "Spell", "Second blade"][i],
    style: i === 0 ? "melee" : i === 1 ? "ranged" : "magic",
    attackType: "slash",
    stance: "accurate",
    spell: "fire_strike",
    weight: 1,
    locks: {},
  }));
  const selectedSolution = jointSolution(1);
  if (utility)
    Object.assign(selectedSolution.loadouts.c.performance, {
      dps: null,
      max_hit: null,
      accuracy: null,
      attack_interval: null,
      limitations: [
        "Special role is unscored; no damage or utility benefit assumed.",
      ],
    });
  const result = {
    source: "live",
    fingerprint: "joint-1",
    snapshotId: "account-1",
    catalogVersion: "catalog-1",
    modelVersion: "normal-attacks-v1",
    priceRevision: "prices-1",
    evaluatedAt: "2026-10-27T00:00:00Z",
    scenario: {
      request: {
        roles: submittedRoles,
        budget_gp: 1000,
        mode: "usable",
        max_swaps: 1,
        reserved_supply_slots: 12,
      },
    },
    live: {
      scenario: { roles: submittedRoles },
      result: {
        selected_solution: missing ? null : selectedSolution,
        unrestricted: selectedSolution,
        active_time_shares: { a: 0.5, b: 0.5 },
        assumptions_fingerprint: "assumptions-1",
        curve: [
          {
            swap_limit: 0,
            solution: jointSolution(0),
            status: "best_found",
            relative_performance: 0.55,
          },
          {
            swap_limit: 1,
            solution: missing ? null : selectedSolution,
            status: missing ? "no_feasible_solution_found" : "best_found",
            relative_performance: missing ? null : 1,
          },
        ],
        search: {
          quality: "best_found",
          candidate_truncation: true,
          explored_nodes: 120,
        },
        limitations: ["Bounded search; no global optimum is proven."],
      },
    },
    solutions: [],
  };
  const current = {
    result,
    previous: null,
    solutionId: selected,
    activeRole: "a",
    selectedTransition: "a:b",
    slot: null,
    outdated,
    draft: { roles: [] },
  };
  const dispatch = vi.fn((action) => {
    Object.assign(current, action.patch);
  });
  const names: Record<number, string> = {
    1: "One handed blade",
    2: "Shield",
    3: "Two handed bow",
    4: "Staff",
    9: "Shared necklace",
  };
  vi.mocked(useGear).mockReturnValue({
    liveMode: true,
    state: { mode: "multi", context: null },
    current,
    dispatch,
    itemById: (id: number | null) =>
      id ? { id, name: names[id], equipment: emptyEquipment() } : undefined,
  } as unknown as ReturnType<typeof useGear>);
  const rendered = render(<LiveMultiResultWorkspace />);
  return { ...rendered, dispatch, result, current };
}

it.each(["archived", "live", "pending", "edited"])(
  "displays the %s potion timeline after a price-only refresh",
  (kind) => {
    const { result, rerender } = setup({ outdated: true });
    const gear = useGear();
    const captured = parseContext(context);
    const updated = {
      ...captured,
      snapshotId: result.snapshotId,
      live: {
        ...captured.live!,
        price_revision: "new-prices",
        catalog_version: result.catalogVersion,
        model_version: result.modelVersion,
      },
    };
    Object.assign(result.scenario.request, { objectives: [] });
    if (kind !== "live") Object.assign(result.live, { run_id: "archived-run" });
    Object.assign(result.live.result.selected_solution!, {
      potions: {
        selected_ids: ["ranging"],
        boosted_levels: { ranged: 86 },
        base_levels: { ranged: 75 },
      },
    });
    const timeline = vi.fn(() => new Promise<never>(() => {}));
    vi.mocked(useGear).mockReturnValue({
      ...gear,
      current: {
        ...gear.current,
        contextStale: true,
        pending: kind === "pending",
        draftChanged: kind === "edited",
      },
      client: { ...gear.client, potionTimeline: timeline },
      state: { ...gear.state, context: updated },
    });
    rerender(<LiveMultiResultWorkspace />);
    if (kind === "archived") {
      expect(timeline).toHaveBeenCalledOnce();
      expect(timeline.mock.calls[0]).toEqual([
        result,
        result.live.result.selected_solution,
        expect.any(AbortSignal),
      ]);
    } else {
      expect(timeline).not.toHaveBeenCalled();
      expect(
        screen.getByText(/Rerun optimization to show potion decay/),
      ).toBeVisible();
    }
  },
);

it("renders every joint configuration at once with shared items and distinct inventory counts", () => {
  setup();
  expect(
    screen.getAllByRole("heading", { level: 2, name: /^(Blade|Bow|Spell)$/ }),
  ).toHaveLength(3);
  expect(screen.getAllByLabelText(/equipment slots$/)).toHaveLength(3);
  expect(
    screen.queryByLabelText("Compare first configuration"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Interactive switching" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Active combat configuration"),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Weighted aggregate DPS")).toHaveTextContent(
    "4.50",
  );
  expect(
    screen.getByLabelText("Gear inventory requirements"),
  ).toHaveTextContent("Unique required items5");
  expect(
    screen.getByLabelText("Gear inventory requirements"),
  ).toHaveTextContent("Base gear inventory slots2");
  expect(
    screen.getByLabelText("Gear inventory requirements"),
  ).toHaveTextContent("Transient peak gear inventory slots3");
  expect(
    screen.getAllByRole("button", {
      name: /neck \S+ · Shared Shared necklace/,
    }),
  ).toHaveLength(3);
  expect(
    screen.getByRole("button", {
      name: /^Blade weapon \S+ · Different One handed blade$/,
    }),
  ).toBeVisible();
  expect(screen.getByText(/250 GP additional purchases/)).toBeVisible();
  expect(
    screen.getByText(/Best found without the swap-action limit/),
  ).toBeVisible();
});

it("shows the Wilderness risk of the unrestricted joint configuration", () => {
  const { result, rerender } = setup({ selected: "unrestricted" });
  Object.assign(result.scenario.request, {
    wilderness: { depth: "level_21_plus", skulled: false, protect_item: false },
  });
  Object.assign(result.live.result.unrestricted, {
    wilderness_risk: {
      loss_gp: 750,
      without_protect_item_gp: null,
      items: [{ item_id: 9, quantity: 1, outcome: "dropped", loss_gp: 750 }],
      quantities: [],
      rules_revision: "reviewed-fixture",
    },
  });
  rerender(<LiveMultiResultWorkspace />);
  expect(
    screen.getByRole("region", { name: "Wilderness risk" }),
  ).toHaveTextContent("750 GP estimated loss if PK’d");
  expect(screen.getByText(/1,000 GP max gear loss if PK’d/)).toBeVisible();
});

it("changes the curve selection only through visualization actions", async () => {
  const user = userEvent.setup();
  const { dispatch } = setup();
  await user.selectOptions(
    screen.getByLabelText("Swap-efficiency curve point"),
    "curve-0",
  );
  expect(dispatch).toHaveBeenLastCalledWith({
    type: "ui",
    mode: "multi",
    patch: { solutionId: "curve-0" },
  });
  expect(dispatch.mock.calls.every(([action]) => action.type === "ui")).toBe(
    true,
  );
});

it("exports each configuration and follows the selected curve without combining gear", async () => {
  const user = userEvent.setup();
  const { current, rerender } = setup({ roles: 2 });
  const exportRole = async (name: string, code: string) => {
    const card = screen.getByRole("group", { name: `Bank tag for ${name}` });
    await user.click(
      within(card).getByRole("button", { name: "Export mobile bank tag" }),
    );
    expect(screen.getByRole("textbox", { name: "Bank tag code" })).toHaveValue(
      code,
    );
    await user.click(
      screen.getByRole("button", { name: "Close Export mobile bank tag" }),
    );
  };
  await exportRole("Blade", "1,3,9,1,1,1,0,2,2,2,2");
  await exportRole("Bow", "1,2,9,1,1,3,0,2");
  current.solutionId = "curve-0";
  rerender(<LiveMultiResultWorkspace />);
  await exportRole("Bow", "1,2,9,1,1,1,0,2");
});

it("keeps both tradeoff panels on the selected action limit when crossing frontiers", async () => {
  const user = userEvent.setup();
  const { current, result, rerender } = setup({ roles: 2 });
  Object.assign(result.scenario.request, {
    max_swaps: 8,
    secondary_priority: "prayer_bonus",
  });
  const cost = {
    status: "known",
    gp_per_damage: 2,
    gp_per_attack: 3,
    gp_per_hour: 4500,
    resources: [],
    reasons: [],
  };
  const lowSolution = {
    ...jointSolution(1),
    score: 3.25,
    secondary_value: 20,
    running_cost: cost,
  };
  const point = (id: string, solution = lowSolution) => ({
    id,
    solution,
    dps_loss: 0,
    dps_loss_pct: 0,
    secondary_gain: 0,
  });
  const groups = (prefix: string) => [
    {
      swap_limit: 1,
      baseline_dps: 4.5,
      sampled: false,
      points: [point(`${prefix}-1`), point(`${prefix}-1-other`)],
    },
    {
      swap_limit: 8,
      baseline_dps: 9,
      sampled: false,
      points: [point(`${prefix}-8`)],
    },
    {
      swap_limit: null,
      baseline_dps: 9,
      sampled: false,
      points: [point(`${prefix}-unrestricted`)],
    },
  ];
  Object.assign(result.live.result, {
    secondary_frontiers: groups("secondary"),
    running_cost_frontiers: groups("cost"),
  });
  result.live.result.curve.push({
    swap_limit: 8,
    solution: jointSolution(1),
    status: "best_found",
    relative_performance: 1,
  });
  Object.assign(result, {
    solutions: [
      ...groups("secondary").flatMap((group) => group.points),
      ...groups("cost").flatMap((group) => group.points),
    ].map((entry) => ({ id: entry.id, live: entry.solution })),
  });
  rerender(<LiveMultiResultWorkspace />);
  const secondary = () => within(screen.getByLabelText("Metric tradeoffs"));
  const running = () => within(screen.getByLabelText("Running cost tradeoffs"));
  const expectLowLimit = () => {
    expect(screen.getByLabelText("Swap-efficiency curve point")).toHaveValue(
      "curve-1",
    );
    expect(
      secondary().getByRole("button", { name: "Select tradeoff 2" }),
    ).toBeVisible();
    expect(
      running().getByRole("button", { name: /^Select cost tradeoff 2:/ }),
    ).toBeVisible();
  };
  expectLowLimit();
  await user.click(
    running().getByRole("button", { name: /^Select cost tradeoff 1:/ }),
  );
  rerender(<LiveMultiResultWorkspace />);
  expect(current.solutionId).toBe("cost-1");
  expectLowLimit();
  expect(screen.getByLabelText("Weighted aggregate DPS")).toHaveTextContent(
    "3.25",
  );
  expect(
    screen.getByLabelText("Directed equipment transition"),
  ).toHaveTextContent("Equip Two handed bow");
  await user.click(
    secondary().getByRole("button", { name: "Select tradeoff 2" }),
  );
  rerender(<LiveMultiResultWorkspace />);
  expect(current.solutionId).toBe("secondary-1-other");
  expectLowLimit();
  expect(screen.getByLabelText("Weighted aggregate DPS")).toHaveTextContent(
    "3.25",
  );
  for (const id of ["cost-unrestricted", "secondary-unrestricted"]) {
    current.solutionId = id;
    rerender(<LiveMultiResultWorkspace />);
    expect(screen.getByLabelText("Swap-efficiency curve point")).toHaveValue(
      "unrestricted",
    );
    expect(
      secondary().queryByRole("button", { name: "Select tradeoff 2" }),
    ).not.toBeInTheDocument();
    expect(
      running().queryByRole("button", { name: /^Select cost tradeoff 2:/ }),
    ).not.toBeInTheDocument();
  }
});

it("uses the selected curve solution for all dependent panels", () => {
  setup({ selected: "curve-0" });
  expect(screen.getByLabelText("Weighted aggregate DPS")).toHaveTextContent(
    "2.50",
  );
  expect(
    screen.getByLabelText("Gear inventory requirements"),
  ).toHaveTextContent("Unique required items4");
  expect(screen.getByText(/0 GP additional purchases/)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Two handed bow/ }),
  ).not.toBeInTheDocument();
});

it("shows the selected Auto discipline and options when changing curve or frontier points", () => {
  const { current, result, rerender } = setup({ roles: 2 });
  Object.assign(result.scenario.request.roles[1], {
    style: "melee",
    autoDiscipline: true,
    allowedDisciplines: ["ranged", "magic"],
  });
  Object.assign(result.live.result.curve[1].solution!.loadouts.b, {
    discipline: "ranged",
    combat_option: {
      attack_type: "heavy",
      stance: "rapid",
      spell: null,
      powered_attack: null,
    },
  });
  Object.assign(result.live.result.curve[0].solution!.loadouts.b, {
    discipline: "magic",
    combat_option: {
      attack_type: "magic",
      stance: "accurate",
      spell: "fire_strike",
      powered_attack: null,
    },
  });
  const panel = () =>
    within(screen.getByRole("heading", { name: "Bow" }).closest("section")!);
  rerender(<LiveMultiResultWorkspace />);
  expect(
    panel().getByLabelText("Resolved combat discipline"),
  ).toHaveTextContent("Auto selected ranged");
  expect(
    panel().getByLabelText("Selected combat configuration"),
  ).toHaveTextContent("heavy · rapid");
  current.solutionId = "curve-0";
  rerender(<LiveMultiResultWorkspace />);
  expect(
    panel().getByLabelText("Resolved combat discipline"),
  ).toHaveTextContent("Auto selected magic");
  expect(
    panel().getByLabelText("Selected combat configuration"),
  ).toHaveTextContent("magic · accurate · fire strike");
  Object.assign(result, {
    solutions: [
      { id: "frontier-auto", live: result.live.result.curve[1].solution },
    ],
  });
  current.solutionId = "frontier-auto";
  rerender(<LiveMultiResultWorkspace />);
  expect(
    panel().getByLabelText("Resolved combat discipline"),
  ).toHaveTextContent("Auto selected ranged");
});

it("shows returned running-cost frontiers when no retained manual style is magic", () => {
  const { result, rerender } = setup({ roles: 2 });
  Object.assign(result.scenario.request.roles[1], {
    autoDiscipline: true,
    allowedDisciplines: ["ranged", "magic"],
  });
  Object.assign(result.live.result, {
    running_cost_frontiers: [
      { swap_limit: 1, baseline_dps: 4.5, sampled: false, points: [] },
    ],
  });
  rerender(<LiveMultiResultWorkspace />);
  expect(screen.getByLabelText("Running cost tradeoffs")).toBeVisible();
});

it("labels only an actual backend suggested curve point without changing selection", () => {
  const { current, rerender, dispatch } = setup();
  Object.assign(current.result.live.result, { suggested_swap_limit: 0 });
  rerender(<LiveMultiResultWorkspace />);
  expect(screen.getByText(/^Suggested:/)).toHaveTextContent(
    "0 equipment actions",
  );
  expect(screen.getByLabelText("Swap-efficiency curve point")).toHaveValue(
    "curve-1",
  );
  expect(dispatch).not.toHaveBeenCalled();
});

it("shows the backend directed sequence including automatic removals without inferring slot actions", () => {
  setup();
  const panel = screen.getByLabelText("Directed equipment transition");
  expect(panel).toHaveTextContent("Changed equipment slots2");
  expect(panel).toHaveTextContent("Equipment actions1");
  expect(panel).toHaveTextContent("Equip Two handed bow");
  expect(panel).toHaveTextContent(
    "Automatically removed: One handed blade, Shield",
  );
  expect(within(panel).getAllByRole("listitem")).toHaveLength(1);
  expect(screen.getByText(/Carried outside Blade/)).toHaveTextContent(
    "Two handed bow",
  );
});

it("keeps provenance and stale interpretation while showing unavailable points honestly", () => {
  setup({ missing: true, outdated: true });
  expect(
    screen.getByRole("heading", { name: /No feasible solution found/ }),
  ).toBeVisible();
  expect(screen.getByText(/Result outdated/)).toBeVisible();
  expect(screen.getByText(/account-1/)).toBeInTheDocument();
  expect(screen.getByText(/catalog-1/)).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Weighted aggregate DPS"),
  ).not.toBeInTheDocument();
});

it("does not invent damage metrics for an unscored utility configuration", () => {
  setup({ utility: true });
  const panel = screen
    .getByRole("heading", { name: "Spell" })
    .closest("section")!;
  expect(panel).toHaveTextContent("Unscored configuration");
  expect(panel).toHaveTextContent("no damage or utility benefit assumed");
  expect(
    within(panel).queryByLabelText(/combat performance/),
  ).not.toBeInTheDocument();
});

it("shows all four configurations and inspects a slot in any of them", async () => {
  const user = userEvent.setup();
  const { current } = setup({ roles: 4 });
  for (const name of ["Blade", "Bow", "Spell", "Second blade"])
    expect(screen.getByRole("heading", { name })).toBeVisible();
  expect(screen.getAllByLabelText(/equipment slots$/)).toHaveLength(4);
  await user.click(screen.getByRole("button", { name: /Second blade weapon/ }));
  expect(current.activeRole).toBe("d");
  expect(current.slot).toBe("weapon");
});

it("measures differences and shared items across every configuration", () => {
  setup({ roles: 4 });
  const blade = screen
    .getByRole("heading", { name: "Blade" })
    .closest("section")!;
  expect(
    within(blade).getByText(/Differs from another configuration:/),
  ).toHaveTextContent("Differs from another configuration: weapon, shield.");
  expect(
    screen.getByRole("button", {
      name: /^Second blade weapon \S+ · Shared · Different One handed blade$/,
    }),
  ).toBeVisible();
  expect(
    screen.getByText(/Reused across the joint configuration:/),
  ).toHaveTextContent("One handed blade · Shared necklace");
});

it("lists gear carried outside each configuration", () => {
  setup({ roles: 4 });
  const panel = screen.getByLabelText("Gear inventory requirements");
  expect(within(panel).getByText(/Carried outside Bow/)).toHaveTextContent(
    "One handed blade · Shield · Staff",
  );
  for (const name of ["Blade", "Spell", "Second blade"])
    expect(
      within(panel).getByText(new RegExp(`Carried outside ${name}:`)),
    ).toBeVisible();
});

it("can select an asymmetric reverse backend sequence and displays explicit unequips", async () => {
  const user = userEvent.setup();
  const { current, dispatch, rerender } = setup();
  const solution = current.result.live.result.curve[1].solution!;
  solution.transitions.push({
    from_role: "b",
    to_role: "a",
    action_count: 2,
    changed_slots: 2,
    max_gear_inventory_slots: 3,
    actions: [
      {
        operation: "unequip",
        slot: "weapon",
        item_id: 3,
        automatically_removed: [],
        gear_inventory_slots: 3,
      },
      {
        operation: "equip",
        slot: "weapon",
        item_id: 1,
        automatically_removed: [],
        gear_inventory_slots: 2,
      },
    ],
  });
  rerender(<LiveMultiResultWorkspace />);
  await user.selectOptions(screen.getByLabelText("Directed transition"), "b:a");
  expect(dispatch).toHaveBeenLastCalledWith({
    type: "ui",
    mode: "multi",
    patch: { selectedTransition: "b:a" },
  });
  rerender(<LiveMultiResultWorkspace />);
  expect(
    screen.getByLabelText("Directed equipment transition"),
  ).toHaveTextContent("Unequip Two handed bow");
  expect(
    within(screen.getByLabelText("Directed equipment transition")).getAllByRole(
      "listitem",
    ),
  ).toHaveLength(2);
});

it("shows a pre-run joint explanation without an observed loadout masquerading as a joint baseline", () => {
  const { current, rerender } = setup();
  Object.assign(current, { result: null });
  rerender(<LiveMultiResultWorkspace />);
  expect(
    screen.getByRole("heading", { name: "Configure a joint optimization" }),
  ).toBeVisible();
  expect(screen.queryByLabelText(/equipment slots$/)).not.toBeInTheDocument();
});

it("keeps unknown selection unavailable instead of silently displaying the backend default", () => {
  setup({ selected: "missing-point" });
  expect(
    screen.getByRole("heading", { name: /No feasible solution/ }),
  ).toBeVisible();
});

it("shows zero-action and empty-topology results without fabricating action steps", () => {
  const { current, rerender } = setup({ selected: "curve-0" });
  expect(screen.getByText(/No equipment actions required/)).toBeVisible();
  current.result.live.result.curve[0].solution!.transitions = [];
  rerender(<LiveMultiResultWorkspace />);
  expect(
    screen.getByText(/No directed transitions are required/),
  ).toBeVisible();
});

it("handles missing reference, metadata, shared equipment and purchases explicitly", () => {
  const { current, rerender } = setup();
  const raw = current.result.live.result;
  Object.assign(raw, { unrestricted: null, active_time_shares: {} });
  const solution = raw.curve[1].solution!;
  Object.assign(solution.loadouts.a, { equipment: { weapon: 999 } });
  Object.assign(solution.loadouts.b, { equipment: { weapon: 3 } });
  solution.carried_item_ids = [999, 3];
  Object.assign(solution.purchases[0], { cost_gp: null, conditional: false });
  rerender(<LiveMultiResultWorkspace />);
  expect(
    screen.getByText(/Best found without the swap-action limit:/),
  ).toHaveTextContent("Unavailable");
  expect(
    screen.getByRole("button", { name: /Blade weapon.*Item #999/ }),
  ).toBeVisible();
  expect(
    screen.getByText(/Reused across the joint configuration: None/),
  ).toBeVisible();
  expect(
    screen.getByText(/Price unavailable/, { selector: "span" }),
  ).toBeVisible();
});

it("renders unsupported role reasons and the previous accepted context without synthetic deltas", () => {
  const { current, rerender } = setup();
  const raw = current.result.live.result;
  Object.assign(raw.curve[1].solution!.loadouts.a.performance, {
    supported: false,
    limitations: ["Unsupported equipment effect"],
  });
  Object.assign(current.result.scenario.request, { mode: "future" });
  Object.assign(current, {
    previous: {
      fingerprint: "old-joint",
      snapshotId: "old-account",
      catalogVersion: "old-catalog",
      modelVersion: "old-model",
      priceRevision: "old-prices",
      scenario: {},
    },
  });
  rerender(<LiveMultiResultWorkspace />);
  expect(screen.getByText("Combat performance unavailable")).toBeVisible();
  expect(
    screen.getByText("Unsupported equipment effect", { selector: "p.notice" }),
  ).toBeVisible();
  expect(screen.getByText(/Hypothetical submitted result/)).toBeVisible();
  expect(screen.getByText(/Previous accepted scenario:/)).toHaveTextContent(
    "old-joint",
  );
});
