import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LiveResultWorkspace } from "../components/LiveResultWorkspace";
import { useGear } from "../state/GearProvider";
import { emptyEquipment } from "../api/contracts";
import { newDraft, normalize } from "../state/scenario";

vi.mock("../state/GearProvider", () => ({ useGear: vi.fn() }));
vi.mock("../components/EquipmentGrid", () => ({
  ItemSprite: () => null,
  EquipmentGrid: ({
    equipment,
    onSelect,
  }: {
    equipment: { weapon: number };
    onSelect: (slot: "weapon") => void;
  }) => (
    <button onClick={() => onSelect("weapon")}>
      Equipped weapon {equipment.weapon}
    </button>
  ),
}));
vi.mock("../components/SupportPolicySummary", () => ({
  SupportPolicySummary: () => null,
}));
vi.mock("../components/CombatOptionSummary", () => ({
  CombatOptionSummary: () => null,
}));
vi.mock("../components/EquipmentBonuses", () => ({
  EquipmentBonuses: () => null,
}));
vi.mock("../components/PurchaseListCopy", () => ({
  PurchaseListCopy: () => null,
}));

function setup(
  solutionId = "discipline-ranged-best-found",
  options: {
    previous?: "same" | "different";
    empty?: boolean;
    manual?: boolean;
    future?: boolean;
    outdated?: boolean;
    purchases?: boolean;
    owned?: boolean;
    frontierCap?: number | null;
  } = {},
) {
  const dispatch = vi.fn();
  const scenario = normalize(newDraft(), "snapshot");
  const request = {
    ...scenario.request,
    secondary_priority: "prayer_bonus",
    roles: [{ ...scenario.request.roles[0], autoDiscipline: !options.manual }],
  };
  const liveSolution = (discipline: string, weapon: number) => ({
    score: weapon,
    purchase_cost_gp: weapon,
    purchases: options.purchases
      ? [{ item_id: weapon, cost_gp: weapon, conditional: false }]
      : [],
    loadouts: {
      "role-1": {
        discipline,
        equipment: { weapon },
        performance: { bonuses: {} },
      },
    },
    secondary_value: 10,
  });
  const melee = liveSolution("melee", 100),
    ranged = liveSolution("ranged", 50),
    tradeoff = liveSolution("ranged", 40);
  const parsed = (id: string, live: ReturnType<typeof liveSolution>) => ({
    id,
    cost: live.purchase_cost_gp,
    purchases: live.purchases.map((p) => p.item_id),
    live,
    loadouts: [
      {
        roleId: "role-1",
        metrics: { dps: live.score, maxHit: 5, accuracy: 0.5, seconds: 2.4 },
        equipment: { ...emptyEquipment(), weapon: live.score },
        discipline: live.loadouts["role-1"].discipline,
      },
    ],
  });
  const result = {
    scenario: {
      ...scenario,
      request: {
        ...request,
        mode: options.future ? "future" : request.mode,
        assumed_item_ids: options.future ? [55] : [],
      },
    },
    fingerprint: "result",
    priceRevision: "prices",
    solutions: [
      parsed("best-found", melee),
      parsed("discipline-ranged-best-found", ranged),
      parsed("discipline-ranged-frontier-8-a", tradeoff),
    ],
    live: {
      scenario: {},
      result: {
        selected_solution: melee,
        curve: [{ swap_limit: 0, solution: melee }],
        running_cost_frontiers: [
          {
            swap_limit:
              options.frontierCap === undefined
                ? request.max_swaps
                : options.frontierCap,
            baseline_dps: 100,
            sampled: false,
            points: [],
          },
        ],
        secondary_frontiers: [],
        search: {},
        discipline_comparison: [
          {
            discipline: "ranged",
            score: 50,
            purchase_cost_gp: 50,
            status: "best_found",
            reasons: [],
          },
          {
            discipline: "magic",
            score: null,
            purchase_cost_gp: null,
            status: "no_feasible_solution_found",
            reasons: ["No eligible spell"],
          },
          {
            discipline: "melee",
            score: null,
            purchase_cost_gp: null,
            status: "no_feasible_solution_found",
            reasons: [],
          },
        ],
        discipline_results: [
          {
            discipline: "ranged",
            reasons: [],
            selected_solution: ranged,
            search: {},
            limitations: [],
            running_cost_frontiers: [
              {
                swap_limit:
                  options.frontierCap === undefined
                    ? request.max_swaps
                    : options.frontierCap,
                baseline_dps: 50,
                sampled: false,
                points: [],
              },
            ],
            secondary_frontiers: [
              {
                swap_limit:
                  options.frontierCap === undefined
                    ? request.max_swaps
                    : options.frontierCap,
                baseline_dps: 50,
                sampled: false,
                points: [
                  {
                    id: "discipline-ranged-frontier-8-a",
                    solution: tradeoff,
                    dps_loss: 10,
                    dps_loss_pct: 20,
                    secondary_gain: 5,
                  },
                ],
              },
            ],
          },
          {
            discipline: "magic",
            reasons: ["No eligible spell"],
            selected_solution: null,
            secondary_frontiers: [],
            search: {},
            limitations: [],
          },
        ],
      },
    },
  };
  const previous = options.previous
    ? {
        ...result,
        fingerprint: "previous",
        priceRevision:
          options.previous === "different"
            ? "old-prices"
            : result.priceRevision,
      }
    : undefined;
  vi.mocked(useGear).mockReturnValue({
    state: { mode: "single" },
    current: {
      result: options.empty ? null : result,
      solutionId,
      previous,
      outdated: options.outdated,
    },
    dispatch,
    itemById: options.owned
      ? (id: number) => (id ? { name: "Observed bow", owned: true } : undefined)
      : () => undefined,
  } as unknown as ReturnType<typeof useGear>);
  render(<LiveResultWorkspace />);
  return dispatch;
}

it("shows viewed discipline equipment while preserving the overall Auto winner", async () => {
  const dispatch = setup();
  expect(screen.getByText("Equipped weapon 50")).toBeVisible();
  expect(screen.queryByText("Equipped weapon 100")).toBeNull();
  expect(screen.getByText(/Auto selected ranged/)).toBeVisible();
  expect(screen.getByRole("tab", { name: "Ranged" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Select tradeoff 1" }),
  );
  expect(dispatch).toHaveBeenCalledWith({
    type: "ui",
    mode: "single",
    patch: { solutionId: "discipline-ranged-frontier-8-a" },
  });
});
it("shows selected discipline frontier equipment", () => {
  setup("discipline-ranged-frontier-8-a");
  expect(screen.getByText("Equipped weapon 40")).toBeVisible();
  expect(screen.getByText(/Auto selected ranged/)).toBeVisible();
  expect(screen.getByRole("heading", { name: "Selected setup" })).toBeVisible();
});
it.each([
  ["best-found", "100"],
  ["discipline-ranged-best-found", "50"],
  ["discipline-ranged-frontier-8-a", "40"],
])("exports the displayed %s loadout", async (selection, weapon) => {
  setup(selection, { outdated: true });
  await userEvent.click(
    screen.getByRole("button", { name: "Export mobile bank tag" }),
  );
  expect(screen.getByRole("textbox", { name: "Bank tag code" })).toHaveValue(
    `1,1,${weapon},0,2`,
  );
  expect(screen.getByText(/Result outdated/)).toBeVisible();
});

it("does not export an infeasible discipline", () => {
  setup("discipline-magic-best-found");
  expect(
    screen.queryByRole("button", { name: "Export mobile bank tag" }),
  ).not.toBeInTheDocument();
});
it("does not fall back to the winner for an infeasible discipline", async () => {
  setup("discipline-magic-best-found");
  expect(
    screen.getByRole("heading", {
      name: "No feasible solution found within this search",
    }),
  ).toBeVisible();
  expect(
    screen.getByText(/Viewing magic loadouts: No eligible spell/),
  ).toBeVisible();
  expect(screen.queryByText(/Equipped weapon/)).toBeNull();
  expect(screen.queryByRole("heading", { name: "What to buy" })).toBeNull();
  await userEvent.click(
    screen.getByText("Tradeoff metric", { selector: "summary" }),
  );
  expect(screen.getByText(/no feasible measurement/)).toBeVisible();
});
it("opens the initial empty workspace without tabs", () => {
  setup("best-found", { empty: true });
  expect(
    screen.getByRole("heading", { name: "Find your best configuration" }),
  ).toBeVisible();
  expect(screen.queryByRole("tablist")).toBeNull();
});
it("switches tabs through shared solution state and inspects viewed equipment", async () => {
  const dispatch = setup();
  await userEvent.click(screen.getByRole("tab", { name: "Auto overall" }));
  expect(dispatch).toHaveBeenCalledWith({
    type: "ui",
    mode: "single",
    patch: { solutionId: "best-found", slot: null },
  });
  await userEvent.click(screen.getByRole("tab", { name: "Magic" }));
  expect(dispatch).toHaveBeenCalledWith({
    type: "ui",
    mode: "single",
    patch: { solutionId: "discipline-magic-best-found", slot: null },
  });
  await userEvent.click(
    screen.getByRole("button", { name: "Equipped weapon 50" }),
  );
  expect(dispatch).toHaveBeenCalledWith({
    type: "ui",
    mode: "single",
    patch: { slot: "weapon", activeRole: "role-1" },
  });
});
it("shows manual context and hypothetical acquisition assumptions", () => {
  setup("best-found", {
    manual: true,
    future: true,
    outdated: true,
    purchases: true,
    owned: true,
  });
  expect(screen.getByText(/Hypothetical submitted result/)).toBeVisible();
  expect(screen.getByText(/Hypothetically acquired IDs: 55/)).toBeVisible();
  expect(screen.getByText(/Result outdated/)).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "Acquisition checklist" }),
  ).toBeVisible();
  expect(screen.queryByText(/Auto selected/)).toBeNull();
});
it("compares previous results under matching assumptions", async () => {
  setup("best-found", { previous: "same" });
  await userEvent.click(
    screen.getByText("Previous configuration comparison", {
      selector: "summary",
    }),
  );
  expect(screen.getByText(/Calculated DPS: 100.00/)).toBeVisible();
});
it("withholds comparison when price provenance differs", async () => {
  setup("best-found", { previous: "different" });
  await userEvent.click(
    screen.getByText("Previous configuration comparison", {
      selector: "summary",
    }),
  );
  expect(screen.getByText(/Performance comparison unavailable/)).toBeVisible();
});

it("shows automatic ranged cost analysis at the selected frontier cap without the old arrow panel", () => {
  setup("discipline-ranged-frontier-8-a", { frontierCap: 0 });
  expect(
    screen.getByRole("heading", { name: "DPS and running cost" }),
  ).toBeVisible();
  expect(screen.queryByRole("button", { name: "Compare arrows" })).toBeNull();
});

it.each([
  ["curve-0", 0],
  ["unrestricted", null],
] as const)("follows selected %s cost group", (id, cap) => {
  setup(id, { frontierCap: cap });
  expect(
    screen.getByRole("heading", { name: "DPS and running cost" }),
  ).toBeVisible();
});
