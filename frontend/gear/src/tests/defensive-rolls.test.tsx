import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import {
  validateSecondaryPriority,
  defenceRollExplanation,
  migrateSecondaryPriority,
  matchesSecondaryPriority,
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

it("offers nineteen roll metrics and no equipment defence metrics", () => {
  expect(
    secondaryPriorities.filter(([id]) => id.endsWith("_defence_roll")),
  ).toHaveLength(19);
  expect(secondaryPriorities).toHaveLength(25);
  expect(secondaryPriorities.some(([id]) => id.endsWith("_defence"))).toBe(
    false,
  );
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

const meleeMetrics = [
  ["melee_defence_roll", ["stab", "slash", "crush"]],
  ["melee_magic_defence_roll", ["stab", "slash", "crush", "magic"]],
  ["melee_ranged_defence_roll", ["stab", "slash", "crush", "ranged"]],
  ["stab_magic_defence_roll", ["stab", "magic"]],
  ["stab_ranged_defence_roll", ["stab", "ranged"]],
  ["stab_magic_ranged_defence_roll", ["stab", "magic", "ranged"]],
  ["slash_magic_defence_roll", ["slash", "magic"]],
  ["slash_ranged_defence_roll", ["slash", "ranged"]],
  ["slash_magic_ranged_defence_roll", ["slash", "magic", "ranged"]],
  ["crush_magic_defence_roll", ["crush", "magic"]],
  ["crush_ranged_defence_roll", ["crush", "ranged"]],
  ["crush_magic_ranged_defence_roll", ["crush", "magic", "ranged"]],
] as const;
it.each(meleeMetrics)(
  "validates all and only included components for %s",
  (priority, styles) => {
    const measured = (components: Record<string, number | null>) => ({
      ...solution,
      secondary_priority: priority,
      loadouts: {
        single: { performance: { player_defence_rolls: components } },
      },
    });
    const included = Object.fromEntries(styles.map((style) => [style, 1234]));
    expect(() =>
      validateSecondaryPriority(measured(included), priority, true),
    ).not.toThrow();
    for (const style of styles) {
      expect(() =>
        validateSecondaryPriority(
          measured({ ...included, [style]: null }),
          priority,
          true,
        ),
      ).toThrow(/roll/);
    }
  },
);

it.each(meleeMetrics)(
  "explains the weakest included components for %s",
  (priority, styles) => {
    expect(defenceRollExplanation(priority)).toContain(
      `lowest of the ${styles.join(", ")} player defence rolls`,
    );
  },
);
it("does not describe strength bonuses as defensive rolls", () => {
  expect(defenceRollExplanation("melee_strength_bonus")).toBe("");
});

it("leaves current roll metrics unchanged during migration", () => {
  expect(migrateSecondaryPriority("melee_defence_roll")).toBe(
    "melee_defence_roll",
  );
});
it("excludes utility roles but validates supported combat roles", () => {
  expect(() =>
    validateSecondaryPriority(
      {
        ...solution,
        loadouts: { utility: { performance: { supported: true } } },
      },
      "magic_ranged_defence_roll",
      true,
    ),
  ).not.toThrow();
  for (const performance of [
    { supported: true, dps: 1, player_defence_rolls: rolls },
    { supported: true, bonuses: {}, player_defence_rolls: rolls },
  ])
    expect(() =>
      validateSecondaryPriority(
        { ...solution, loadouts: { single: { performance } } },
        "magic_ranged_defence_roll",
        true,
      ),
    ).not.toThrow();
  expect(() =>
    validateSecondaryPriority(
      { ...solution, loadouts: { single: { performance: { dps: 1 } } } },
      "magic_ranged_defence_roll",
      true,
    ),
  ).toThrow(/Invalid/);
});
it("rejects invented DPS-only measurements but accepts historical null", () => {
  expect(() =>
    validateSecondaryPriority({ secondary_value: 1 }, "default", true),
  ).toThrow(/invent/);
  expect(() =>
    validateSecondaryPriority({ secondary_value: null }, "default", true),
  ).not.toThrow();
});
it("compares historical defaults, caps and frontier policies", () => {
  const reply = (
    request: Record<string, unknown>,
    policy?: Record<string, unknown>,
  ) =>
    ({
      scenario: { request },
      ...(policy ? { live: { frontier_policy: policy } } : {}),
    }) as unknown as OptimizationReply;
  expect(
    matchesSecondaryPriority(
      reply({}),
      reply({ secondary_priority: "default", max_dps_loss_pct: 10 }),
    ),
  ).toBe(true);
  expect(
    matchesSecondaryPriority(
      reply({ max_dps_loss_pct: 10 }),
      reply({ max_dps_loss_pct: 100 }),
    ),
  ).toBe(false);
  expect(
    matchesSecondaryPriority(
      reply({}, { policy: "old" }),
      reply({}, { policy: "new" }),
    ),
  ).toBe(false);
});
