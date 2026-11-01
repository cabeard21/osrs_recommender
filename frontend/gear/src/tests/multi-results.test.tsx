import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LiveMultiResultWorkspace } from "../components/LiveMultiResultWorkspace";
import { useGear } from "../state/GearProvider";
import { emptyEquipment } from "../api/contracts";

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
  view = "side",
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
    comparisonRoles: ["a", utility ? "c" : "b"],
    activeRole: "a",
    selectedTransition: "a:b",
    slot: null,
    view,
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

it("renders exactly two selected joint configurations with shared items and distinct inventory counts", () => {
  setup();
  expect(
    screen.getAllByRole("heading", { level: 2, name: /^(Blade|Bow)$/ }),
  ).toHaveLength(2);
  expect(
    screen.queryByRole("heading", { name: "Spell" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Compare first configuration")).toHaveValue("a");
  expect(screen.getByLabelText("Compare second configuration")).toHaveValue(
    "b",
  );
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
  ).toHaveLength(2);
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

it("changes curve and comparison selections only through visualization actions", async () => {
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
  await user.selectOptions(
    screen.getByLabelText("Compare second configuration"),
    "c",
  );
  expect(dispatch).toHaveBeenLastCalledWith({
    type: "ui",
    mode: "multi",
    patch: { comparisonRoles: ["a", "c"] },
  });
  await user.click(
    screen.getByRole("button", { name: "Interactive switching" }),
  );
  expect(dispatch).toHaveBeenLastCalledWith({
    type: "ui",
    mode: "multi",
    patch: { view: "interactive" },
  });
  expect(dispatch.mock.calls.every(([action]) => action.type === "ui")).toBe(
    true,
  );
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
  setup({ view: "interactive" });
  expect(screen.getAllByLabelText(/equipment slots$/)).toHaveLength(1);
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

it("compares a chosen fourth configuration while preserving at most two grids", async () => {
  const user = userEvent.setup();
  const { current, rerender } = setup({ roles: 4 });
  await user.selectOptions(
    screen.getByLabelText("Compare first configuration"),
    "d",
  );
  rerender(<LiveMultiResultWorkspace />);
  expect(current.comparisonRoles).toEqual(["d", "b"]);
  expect(screen.getByRole("heading", { name: "Second blade" })).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: "Blade" }),
  ).not.toBeInTheDocument();
  expect(screen.getAllByLabelText(/equipment slots$/)).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: /Second blade weapon/ }));
  expect(current.activeRole).toBe("d");
  expect(current.slot).toBe("weapon");
});

it("switches the active role independently and uses its actual comparison counterpart", async () => {
  const user = userEvent.setup();
  const { dispatch, rerender } = setup({ view: "interactive", roles: 4 });
  await user.selectOptions(
    screen.getByLabelText("Active combat configuration"),
    "d",
  );
  expect(dispatch).toHaveBeenLastCalledWith({
    type: "ui",
    mode: "multi",
    patch: { activeRole: "d", slot: null },
  });
  rerender(<LiveMultiResultWorkspace />);
  expect(
    screen.getByText(/Equipment differences from Blade:/),
  ).toHaveTextContent("shield");
  expect(
    screen.getByText(/Shared by Second blade and Blade:/),
  ).toHaveTextContent("One handed blade");
});

it("can select an asymmetric reverse backend sequence and displays explicit unequips", async () => {
  const user = userEvent.setup();
  const { current, dispatch, rerender } = setup({ view: "interactive" });
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
  expect(screen.getByText(/Shared by Blade and Bow: None/)).toBeVisible();
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
  expect(screen.getByText("Unsupported equipment effect")).toBeVisible();
  expect(screen.getByText(/Hypothetical submitted result/)).toBeVisible();
  expect(screen.getByText(/Previous accepted scenario:/)).toHaveTextContent(
    "old-joint",
  );
});
