import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { SecondaryFrontier } from "../components/SecondaryFrontier";
import { newDraft, normalize } from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import type {
  JointSolutionDTO,
  SecondaryFrontierGroup,
} from "../api/contracts";

const solutionDefaults: JointSolutionDTO = {
  score: 0,
  loadouts: {},
  purchases: [],
  purchase_cost_gp: 0,
  transitions: [],
  carried_item_ids: [],
  distinct_items: 0,
  gear_inventory_slots: 0,
  max_gear_inventory_slots: 0,
  remaining_supply_slots: 28,
  remaining_inventory_slots: 28,
  reserved_supply_slots: 0,
  maximum_actions: 0,
};
it("requests the full frontier even when a restored draft has an old cap", () => {
  for (const maxDpsLossPct of ["15", "101", ""]) {
    const scenario = normalize({ ...newDraft(), maxDpsLossPct }, "snapshot");
    expect(optimizationRequest(scenario).max_dps_loss_pct).toBe(100);
  }
});
it("selects a tradeoff without optimization", async () => {
  const select = vi.fn();
  const group = {
    swap_limit: 8,
    baseline_dps: 10,
    sampled: false,
    points: [
      {
        id: "frontier-8-a",
        dps_loss: 0,
        dps_loss_pct: 0,
        secondary_gain: 0,
        solution: {
          ...solutionDefaults,
          score: 10,
          secondary_value: 20,
          purchase_cost_gp: 0,
          maximum_actions: 0,
        },
      },
      {
        id: "frontier-8-b",
        dps_loss: 0.5,
        dps_loss_pct: 5,
        secondary_gain: 30,
        solution: {
          ...solutionDefaults,
          score: 9.5,
          secondary_value: 50,
          purchase_cost_gp: 100,
          maximum_actions: 2,
        },
      },
    ],
  } satisfies SecondaryFrontierGroup;
  render(
    <SecondaryFrontier
      group={group}
      selectedId="best-found"
      onSelect={select}
      priority="balanced_defence"
    />,
  );
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByText("DPS", { selector: "svg text" })).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Highest Balanced defence" }),
  );
  expect(select).toHaveBeenCalledWith("frontier-8-b");
  select.mockClear();
  await userEvent.click(
    screen.getByRole("button", { name: "Select tradeoff 2" }),
  );
  expect(select).toHaveBeenCalledWith("frontier-8-b");
  const chartPoint = screen.getByRole("button", {
    name: "Select chart tradeoff 2",
  });
  chartPoint.focus();
  await userEvent.keyboard("{Enter}");
  expect(select).toHaveBeenCalledTimes(2);
});

it("handles an empty frontier and undefined percentage loss", () => {
  render(
    <SecondaryFrontier
      group={{ swap_limit: 0, baseline_dps: 0, sampled: false, points: [] }}
      selectedId="best-found"
      onSelect={() => {}}
      priority="accuracy"
    />,
  );
  expect(screen.getByText(/No additional tradeoff/)).toBeInTheDocument();
});

it("does not invent frontier data for default or legacy results", () => {
  const view = render(
    <SecondaryFrontier
      selectedId="best-found"
      onSelect={() => {}}
      priority="default"
    />,
  );
  expect(view.container).toBeEmptyDOMElement();
});
it("labels sampling, zero-DPS normalization and accuracy units", () => {
  const group = {
    swap_limit: 0,
    baseline_dps: 0,
    sampled: true,
    points: [
      {
        id: "zero",
        dps_loss: 0,
        dps_loss_pct: null,
        secondary_gain: 0.1,
        solution: {
          ...solutionDefaults,
          score: 0,
          secondary_value: 0.5,
          purchase_cost_gp: 0,
          maximum_actions: 0,
        },
      },
    ],
  } satisfies SecondaryFrontierGroup;
  render(
    <SecondaryFrontier
      group={group}
      selectedId="zero"
      onSelect={() => {}}
      priority="accuracy"
    />,
  );
  expect(screen.getByText(/Showing a sample/)).toBeInTheDocument();
  expect(screen.getByText(/percentage unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/10.00 percentage points/)).toBeInTheDocument();
});

it("shows the selected five defence bonuses and allows chart pointer selection", async () => {
  const select = vi.fn();
  const group = {
    swap_limit: 0,
    baseline_dps: 1,
    sampled: false,
    points: [
      {
        id: "defence",
        dps_loss: 0,
        dps_loss_pct: 0,
        secondary_gain: 0,
        solution: {
          ...solutionDefaults,
          score: 1,
          secondary_value: 2,
          purchase_cost_gp: 0,
          maximum_actions: 0,
          loadouts: {
            "role-1": {
              equipment: {},
              performance: {
                supported: true,
                dps: 1,
                max_hit: 1,
                accuracy: 1,
                attack_interval: 2.4,
                bonuses: { defence_stab: 10 },
                limitations: [],
              },
            },
          },
        },
      },
    ],
  } satisfies SecondaryFrontierGroup;
  render(
    <SecondaryFrontier
      group={group}
      selectedId="defence"
      onSelect={select}
      priority="balanced_defence"
    />,
  );
  expect(
    screen.getByText(/stab 10.*slash 0.*crush 0.*ranged 0.*magic 0/),
  ).toBeInTheDocument();
  const point = screen.getByRole("button", { name: "Select chart tradeoff 1" });
  await userEvent.click(point);
  point.focus();
  await userEvent.keyboard("x");
  expect(select).toHaveBeenCalledTimes(1);
  await userEvent.keyboard(" ");
  expect(select).toHaveBeenCalledTimes(2);
});

it("explains combined defence and shows the selected component bonuses", () => {
  const solution = {
    ...solutionDefaults,
    secondary_value: -5,
    loadouts: {
      single: {
        performance: { bonuses: { defence_magic: -5, defence_ranged: 20 } },
      },
    },
  } as unknown as JointSolutionDTO;
  render(
    <SecondaryFrontier
      priority="magic_ranged_defence"
      selectedId="combined"
      onSelect={() => {}}
      group={{
        swap_limit: 0,
        baseline_dps: 10,
        sampled: false,
        points: [
          {
            id: "combined",
            dps_loss: 0,
            dps_loss_pct: 0,
            secondary_gain: 0,
            solution,
          },
        ],
      }}
    />,
  );
  expect(
    screen.getByText(/lower of the magic and ranged equipment defence bonuses/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/single defence bonuses: magic -5 \/ ranged 20/),
  ).toBeInTheDocument();
});

it("marks a single solution as both endpoints and explains historical caps", async () => {
  const onSelect = vi.fn();
  render(
    <SecondaryFrontier
      priority="prayer_bonus"
      selectedId="only"
      onSelect={onSelect}
      legacyCapped
      group={{
        swap_limit: 0,
        baseline_dps: 0,
        sampled: false,
        points: [
          {
            id: "only",
            dps_loss: 0,
            dps_loss_pct: null,
            secondary_gain: 0,
            solution: { ...solutionDefaults, score: 0, secondary_value: -2 },
          },
        ],
      }}
    />,
  );
  expect(
    screen.getByText(/Highest DPS and highest Prayer bonus/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Historical capped frontier/)).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Highest Prayer bonus" }),
  );
  expect(onSelect).toHaveBeenCalledWith("only");
});
