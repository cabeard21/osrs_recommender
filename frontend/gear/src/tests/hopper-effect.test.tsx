import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { CombatOptionSummary } from "../components/CombatOptionSummary";

const role = {
  style: "ranged" as const,
  attackType: "slash" as const,
  stance: "rapid" as const,
  spell: "fire_strike",
};
const performance = {
  supported: true,
  dps: 5,
  max_hit: 20,
  accuracy: 0.7,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
  aquanite_hopper: {
    proc_chance: 0.11,
    secondary_accuracy: 0.6,
    secondary_max_hit: 6,
    expected_damage_delta: 0.3,
    expected_ammunition_per_attack: 1.11,
    approximate: true,
    assumptions: [
      "Ruby damage is reduced to one third.",
      "Extra bolts use normal Ava recovery.",
    ],
  },
};

test("hopper explanation distinguishes conditional shot stats and estimated DPS", () => {
  render(
    <CombatOptionSummary
      role={role}
      weapon="Rune crossbow"
      performance={performance}
    />,
  );
  const details = screen.getByLabelText("Aquanite hopper effect");
  expect(details).toHaveTextContent("Approximate Aquanite hopper effect");
  expect(details).toHaveTextContent("11.0% extra-shot chance");
  expect(details).toHaveTextContent(
    "On activation: secondary max 6, 60.0% accuracy",
  );
  expect(details).toHaveTextContent("+0.30 expected damage per attack");
  expect(details).toHaveTextContent("+0.100 estimated DPS");
  expect(details).toHaveTextContent("1.11 expected bolts per attack");
  expect(
    screen.getByText("Ruby damage is reduced to one third."),
  ).toBeVisible();
  expect(
    screen.getByText("Extra bolts use normal Ava recovery."),
  ).toBeVisible();
});

test("hopper labels enchanted bolt details as primary shot and handles unknown interval", () => {
  render(
    <CombatOptionSummary
      role={role}
      weapon="Rune crossbow"
      performance={{
        ...performance,
        attack_interval: null,
        bolt_effect: {
          family: "ruby",
          proc_chance: 0.06,
          activation_probability: 0.06,
          expected_damage_per_attack: 14.7,
          total_max_hit: 100,
          normal_max_hit: 20,
          target_hitpoints: 500,
          diary_boosted: false,
          expected_damage_delta: 2,
        },
      }}
    />,
  );
  expect(screen.getByLabelText("Enchanted bolt effect")).toHaveTextContent(
    "Primary shot: ruby bolt effect",
  );
  expect(screen.getByLabelText("Aquanite hopper effect")).not.toHaveTextContent(
    "estimated DPS",
  );
});

test("legacy performance has no hopper explanation", () => {
  const { aquanite_hopper: _hopper, ...legacy } = performance;
  render(
    <CombatOptionSummary
      role={role}
      weapon="Rune crossbow"
      performance={legacy}
    />,
  );
  expect(
    screen.queryByLabelText("Aquanite hopper effect"),
  ).not.toBeInTheDocument();
});
