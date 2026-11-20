import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { CombatPerformance } from "../api/contracts";
import { optimizationRequest } from "../api/httpClient";
import { performanceMetrics } from "../api/runtime";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { TargetSusceptibilityFields } from "../components/TargetSusceptibilityFields";
import { newDraft, normalize } from "../state/scenario";

const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 29,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
  salve_bonus: {
    item_id: 12017,
    accuracy_percent: 100 / 6,
    damage_percent: 100 / 6,
    suppresses_slayer: true,
  },
};

it("shows the applied Salve variant and Slayer precedence", () => {
  render(
    <CombatOptionSummary
      role={{ ...newDraft().roles[0], style: "ranged", stance: "rapid" }}
      weapon="Rune crossbow"
      itemName={() => "Salve amulet(i)"}
      performance={performance}
    />,
  );
  const effect = screen.getByLabelText("Salve amulet effect");
  expect(effect).toHaveTextContent("Salve amulet(i)");
  expect(effect).toHaveTextContent("+16.67% accuracy and damage");
  expect(effect).toHaveTextContent("Takes precedence over the Slayer bonus");
});

it("accepts legacy performance and rejects malformed Salve metadata", () => {
  expect(performanceMetrics({ ...performance, salve_bonus: null }).dps).toBe(4);
  expect(performanceMetrics(performance).dps).toBe(4);
  expect(() =>
    performanceMetrics({
      ...performance,
      salve_bonus: { ...performance.salve_bonus!, accuracy_percent: -5 },
    }),
  ).toThrow(/Salve/);
});

it("shows damage alone for a Strength-based ranged attack", () => {
  render(
    <CombatOptionSummary
      role={{ ...newDraft().roles[0], style: "ranged", stance: "rapid" }}
      weapon="Hunter's spear"
      performance={{
        ...performance,
        salve_bonus: {
          item_id: 10588,
          accuracy_percent: 0,
          damage_percent: 20,
          suppresses_slayer: true,
        },
        slayer_effects: [
          {
            item_id: 11865,
            kind: "mask",
            accuracy_numerator: 23,
            damage_numerator: 20,
            denominator: 20,
            base_max_hit: null,
          },
        ],
      }}
    />,
  );
  expect(screen.getByLabelText("Salve amulet effect")).toHaveTextContent(
    "Salve amulet (#10588) · +20% damage against undead",
  );
  expect(screen.getByLabelText("Salve amulet effect")).toHaveTextContent(
    "Takes precedence over the Slayer bonus for damage",
  );
  expect(screen.getByLabelText("Slayer task effect")).toHaveTextContent(
    "+15% accuracy",
  );
  expect(screen.getByLabelText("Slayer task effect")).not.toHaveTextContent(
    "damage",
  );
});

it("edits a custom undead trait without replacing other traits", () => {
  const target = {
    name: "Custom NPC",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
    traits: ["dragon"],
  };
  const onChange = vi.fn();
  const { rerender } = render(
    <TargetSusceptibilityFields target={target} onChange={onChange} />,
  );
  const checkbox = screen.getByLabelText("Undead target");
  expect(checkbox).not.toBeChecked();
  fireEvent.click(checkbox);
  expect(onChange).toHaveBeenLastCalledWith({ traits: ["dragon", "undead"] });
  const combatTarget = { ...target, ...onChange.mock.lastCall![0] };
  rerender(
    <TargetSusceptibilityFields target={combatTarget} onChange={onChange} />,
  );
  const draft = { ...newDraft(), combatTarget };
  expect(
    optimizationRequest(normalize(draft, "snapshot")).roles[0].target.traits,
  ).toEqual(["dragon", "undead"]);
  fireEvent.click(checkbox);
  expect(onChange).toHaveBeenLastCalledWith({ traits: ["dragon"] });
});
