import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { RunningCostFrontier } from "../components/RunningCostFrontier";
import type { JointSolutionDTO, RunningCost } from "../api/contracts";

const cost: RunningCost = {
  status: "known",
  gp_per_attack: 12,
  gp_per_hour: 14400,
  gp_per_damage: 2,
  resources: [
    {
      item_id: 556,
      name: "Air rune",
      required_quantity: 2,
      consumed_quantity: 0,
      supplied_quantity: 2,
      supplied_by: "Staff of air",
      unit_price_gp: null,
      price_layer: "unknown",
    },
  ],
  reasons: [],
};
const solution = {
  score: 2,
  loadouts: {
    mage: {
      equipment: { weapon: 1381 },
      performance: {
        supported: true,
        dps: 2,
        max_hit: 8,
        accuracy: 1,
        attack_interval: 3,
        bonuses: {},
        limitations: [],
      },
      combat_option: {
        attack_type: "magic",
        stance: "accurate",
        spell: "fire_strike",
        powered_attack: null,
      },
      running_cost: cost,
    },
  },
  running_cost: cost,
  purchase_cost_gp: 100,
  maximum_actions: 0,
} as unknown as JointSolutionDTO;
it("shows casting costs, free runes, spell and selectable points", async () => {
  const onSelect = vi.fn();
  render(
    <RunningCostFrontier
      group={{
        swap_limit: 0,
        baseline_dps: 2,
        sampled: false,
        points: [{ id: "running-0-a", solution, dps_loss: 0, dps_loss_pct: 0 }],
      }}
      selectedId="best-found"
      selected={solution}
      onSelect={onSelect}
      itemName={() => "Staff of air"}
    />,
  );
  expect(
    screen.getByRole("heading", { name: "DPS and running cost" }),
  ).toBeInTheDocument();
  expect(
    screen.getAllByText(/Air rune.*supplied by Staff of air/).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText(/fire strike/i)).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Select cost tradeoff 1" }),
  );
  expect(onSelect).toHaveBeenCalledWith("running-0-a");
});
it("labels unavailable cost without displaying zero", () => {
  render(
    <RunningCostFrontier
      selected={{
        ...solution,
        running_cost: {
          ...cost,
          status: "unavailable",
          gp_per_damage: null,
          reasons: ["Missing rune price"],
        },
      }}
      selectedId="best-found"
      onSelect={() => {}}
      itemName={String}
    />,
  );
  expect(screen.getByText(/Missing rune price/)).toBeInTheDocument();
});

import { validateRunningCost } from "../api/runningCosts";
it("rejects negative or missing consumption prices rather than coercing them", () => {
  expect(() => validateRunningCost(cost)).not.toThrow();
  expect(() => validateRunningCost({ ...cost, gp_per_damage: -1 })).toThrow();
  expect(() => validateRunningCost({ ...cost, gp_per_damage: NaN })).toThrow();
  expect(() =>
    validateRunningCost({
      ...cost,
      resources: [{ ...cost.resources[0], consumed_quantity: -1 }],
    }),
  ).toThrow();
});
it("supports keyboard selection, paid resources, sampled data and unknown baseline", async () => {
  const onSelect = vi.fn();
  const paid = {
    ...solution,
    score: 1,
    running_cost: {
      ...cost,
      resources: [
        {
          ...cost.resources[0],
          consumed_quantity: 2,
          supplied_quantity: 0,
          unit_price_gp: 5,
          price_layer: "cached",
        },
      ],
    },
  };
  render(
    <RunningCostFrontier
      group={{
        swap_limit: null,
        baseline_dps: 3,
        baseline_solution: {
          ...solution,
          running_cost: { ...cost, status: "unavailable", gp_per_damage: null },
        },
        sampled: true,
        points: [
          { id: "cost-b", solution: paid, dps_loss: 2, dps_loss_pct: null },
        ],
      }}
      selectedId="cost-b"
      selected={paid}
      onSelect={onSelect}
      itemName={String}
    />,
  );
  expect(
    screen.getByText(/numerical comparison coverage is incomplete/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Showing a sample/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Select cost tradeoff 1" }),
  ).toHaveTextContent("Highest priced DPS");
  const chart = screen.getByRole("button", {
    name: "Select cost chart tradeoff 1",
  });
  chart.focus();
  await userEvent.keyboard("{Enter}");
  await userEvent.keyboard(" ");
  expect(onSelect).toHaveBeenCalledTimes(2);
  expect(screen.getAllByText(/5 GP each.*cached/).length).toBeGreaterThan(0);
});
it("does not fabricate costs for legacy responses", () => {
  const { container } = render(
    <RunningCostFrontier
      selectedId="legacy"
      onSelect={() => {}}
      itemName={String}
    />,
  );
  expect(container).toBeEmptyDOMElement();
});
