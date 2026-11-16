import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { CombatPerformance } from "../api/contracts";
import { performanceMetrics } from "../api/runtime";
import { CombatOptionSummary } from "../components/CombatOptionSummary";

const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 25,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
};
const bonus = {
  item_id: 21012,
  accuracy_percent: 30,
  damage_percent: 25,
  slayer_damage_additive: false,
};

it.each([
  [22978, 20, 20],
  [21012, 30, 25],
  [25916, 30, 25],
  [25918, 30, 25],
  [30070, 75, 40],
])(
  "accepts reviewed dragonbane form %i",
  (item_id, accuracy_percent, damage_percent) => {
    expect(
      performanceMetrics({
        ...performance,
        dragonbane_bonus: {
          ...bonus,
          item_id,
          accuracy_percent,
          damage_percent,
        },
      }).dps,
    ).toBe(4);
  },
);

it.each([
  { item_id: 1 },
  { item_id: "21012" },
  { accuracy_percent: 25 },
  { damage_percent: 30 },
  { slayer_damage_additive: "true" },
  {
    item_id: 22978,
    accuracy_percent: 20,
    damage_percent: 20,
    slayer_damage_additive: true,
  },
])("rejects inconsistent dragonbane report %j", (invalid) => {
  expect(() =>
    performanceMetrics({
      ...performance,
      dragonbane_bonus: { ...bonus, ...invalid },
    } as unknown as CombatPerformance),
  ).toThrow(/dragonbane/);
});

it("accepts missing and null dragonbane metadata", () => {
  expect(performanceMetrics(performance).dps).toBe(4);
  expect(
    performanceMetrics({ ...performance, dragonbane_bonus: null }).dps,
  ).toBe(4);
});

it.each([false, true])(
  "explains crossbow damage and additive task context %s",
  (additive) => {
    render(
      <CombatOptionSummary
        role={{
          style: "ranged",
          attackType: "slash",
          stance: "rapid",
          spell: "fire_strike",
        }}
        weapon="Dragon hunter crossbow"
        performance={{
          ...performance,
          dragonbane_bonus: { ...bonus, slayer_damage_additive: additive },
        }}
      />,
    );
    const report = screen.getByLabelText("Dragonbane effect");
    expect(report).toHaveTextContent("+30% accuracy and +25% maximum hit");
    if (additive) expect(report).toHaveTextContent("combined +40%");
    else expect(report).not.toHaveTextContent("combined");
  },
);
