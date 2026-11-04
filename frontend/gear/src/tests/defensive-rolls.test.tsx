import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import {
  validateSecondaryPriority,
  secondaryPriorities,
} from "../api/secondaryPriorities";
import { SecondaryFrontier } from "../components/SecondaryFrontier";
import { SecondaryPrioritySummary } from "../components/SecondaryPrioritySummary";
import { formatDefenceRoll } from "../components/defenceRollFormat";
import type { OptimizationReply, JointSolutionDTO } from "../api/contracts";
import type { SecondaryFrontierGroup } from "../api/contracts";

const rolls = {
  stab: 1000,
  slash: 1000,
  crush: 1000,
  ranged: 2000,
  magic: 3000,
  limitations: [],
};
const solution = {
  secondary_priority: "magic_ranged_defence_roll",
  secondary_value: 2000,
  score: 10,
  purchase_cost_gp: 0,
  maximum_actions: 0,
  loadouts: { single: { performance: { player_defence_rolls: rolls } } },
};

it("offers seven additional roll metrics", () => {
  expect(
    secondaryPriorities.filter(([id]) => id.endsWith("_defence_roll")),
  ).toHaveLength(7);
});
it("formats summary rolls and fractional components in thousands", () => {
  const selected = {
    ...solution,
    secondary_value: 12345.67,
    loadouts: {
      single: {
        performance: {
          player_defence_rolls: { ...rolls, magic: 12345, ranged: 500 },
        },
      },
    },
  };
  render(
    <SecondaryPrioritySummary
      result={
        {
          source: "live",
          scenario: {
            request: {
              secondary_priority: "magic_ranged_defence_roll",
              roles: [],
              skill_overrides: {},
            },
          },
        } as unknown as OptimizationReply
      }
      solution={selected as unknown as JointSolutionDTO}
    />,
  );
  expect(
    screen.getByText(/Tradeoff metric: Magic & ranged defence roll/),
  ).toHaveTextContent("12.35k roll");
  expect(
    screen.getByText(/single defence rolls: magic 12.35k \/ ranged 0.50k/),
  ).toBeInTheDocument();
  expect(formatDefenceRoll(null)).toBe("unavailable");
});
it("requires relevant roll components without requiring irrelevant magic", () => {
  expect(() =>
    validateSecondaryPriority(solution, "magic_ranged_defence_roll", true),
  ).not.toThrow();
  for (const magic of [null, undefined, -1, NaN, Infinity, 1.5]) {
    expect(() =>
      validateSecondaryPriority(
        {
          ...solution,
          loadouts: {
            single: {
              performance: { player_defence_rolls: { ...rolls, magic } },
            },
          },
        },
        "magic_ranged_defence_roll",
        true,
      ),
    ).toThrow(/roll/);
  }
  expect(() =>
    validateSecondaryPriority(
      { ...solution, loadouts: {} },
      "magic_ranged_defence_roll",
      true,
    ),
  ).toThrow(/roll/);
  expect(() =>
    validateSecondaryPriority(
      {
        ...solution,
        secondary_priority: "ranged_defence_roll",
        loadouts: {
          single: {
            performance: { player_defence_rolls: { ...rolls, magic: null } },
          },
        },
      },
      "ranged_defence_roll",
      true,
    ),
  ).not.toThrow();
});
it("shows roll units and selected components", () => {
  render(
    <SecondaryFrontier
      priority="magic_ranged_defence_roll"
      selectedId="roll"
      onSelect={() => {}}
      group={
        {
          swap_limit: 0,
          baseline_dps: 10,
          sampled: false,
          points: [
            {
              id: "roll",
              dps_loss: 0,
              dps_loss_pct: 0,
              secondary_gain: 0,
              solution,
            },
          ],
        } as unknown as SecondaryFrontierGroup
      }
    />,
  );
  expect(
    screen.getByText(/single defence rolls: magic 3.00k \/ ranged 2.00k/),
  ).toBeInTheDocument();
  expect(screen.getByText("0.00k roll (0.00%)")).toBeInTheDocument();
  expect(screen.getByText(/survival probability/)).toBeInTheDocument();
});

it.each([0, 12345.67])(
  "formats fractional roll gains against the highest-DPS baseline %s",
  (baseline) => {
    const group = {
      swap_limit: 0,
      baseline_dps: 10,
      sampled: false,
      points: [
        {
          id: "base",
          dps_loss: 0,
          dps_loss_pct: 0,
          secondary_gain: 0,
          solution: { ...solution, secondary_value: baseline },
        },
        {
          id: "gain",
          dps_loss: 1,
          dps_loss_pct: 10,
          secondary_gain: 567.89,
          solution: {
            ...solution,
            score: 9,
            secondary_value: baseline + 567.89,
          },
        },
      ],
    } as unknown as SecondaryFrontierGroup;
    render(
      <SecondaryFrontier
        priority="magic_ranged_defence_roll"
        selectedId="gain"
        onSelect={() => {}}
        group={group}
      />,
    );
    expect(
      screen.getByText(
        baseline ? "0.57k roll (4.60%)" : "0.57k roll (percentage unavailable)",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Gain vs highest-DPS roll")).toBeInTheDocument();
    expect(
      screen.getByText(
        new RegExp(
          `Tradeoff 2: 9.000 DPS, ${((baseline + 567.89) / 1000).toFixed(2)}k Magic`,
        ),
      ),
    ).toBeInTheDocument();
  },
);
