import { expect, test } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { normalize, newDraft } from "../state/scenario";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { TargetHitpointsFields } from "../components/TargetHitpointsFields";

const target = {
  name: "Fixture",
  defence_level: 1,
  magic_level: 1,
  bonuses: {},
  hitpoints: 500,
};
test("shared HP overrides survive normalization without changing the draft", () => {
  const draft = {
    ...newDraft(),
    combatTarget: target,
    targetInputs: { current_hitpoints: "100" },
  };
  expect(normalize(draft, "x").request.target.definition).toMatchObject({
    hitpoints: 500,
    current_hitpoints: 100,
  });
  expect(draft.combatTarget).not.toHaveProperty("current_hitpoints");
});
test.each(["0", "-1", "1.2", "NaN", "501"])(
  "rejects invalid target current HP %s",
  (value) => {
    const draft = {
      ...newDraft(),
      combatTarget: target,
      targetInputs: { current_hitpoints: value },
    };
    expect(() => normalize(draft, "x")).toThrow(/hitpoints/);
  },
);
test("per-role HP overrides normalize and blank resets to default", () => {
  const draft = newDraft();
  draft.roles[0] = {
    ...draft.roles[0],
    combatTarget: { ...target, current_hitpoints: 99 },
    targetInputs: { current_hitpoints: "" },
  };
  expect(
    normalize(draft, "x").request.roles[0].combatTarget?.current_hitpoints,
  ).toBeNull();
});
test("NPC base HP is read only but current HP is editable", () => {
  const patches: unknown[] = [];
  render(
    <TargetHitpointsFields
      target={target}
      fixedBase
      onChange={(patch) => patches.push(patch)}
    />,
  );
  expect(screen.getByLabelText("Target base hitpoints")).toHaveAttribute(
    "readonly",
  );
  fireEvent.change(screen.getByLabelText("Target current hitpoints"), {
    target: { value: "100" },
  });
  expect(patches[0]).toMatchObject({
    combatTarget: { current_hitpoints: 100 },
    targetInputs: { current_hitpoints: "100" },
  });
});
test("proc explanation identifies HP-dependent DPS and ordinary hit values", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "ranged",
        attackType: "slash",
        stance: "rapid",
        spell: "fire_strike",
      }}
      weapon="Adamant crossbow"
      performance={{
        supported: true,
        dps: 5,
        max_hit: 20,
        accuracy: 0.7,
        attack_interval: 3,
        bonuses: {},
        limitations: [],
        bolt_effect: {
          family: "ruby",
          proc_chance: 0.06,
          activation_probability: 0.06,
          expected_damage_per_attack: 15,
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
    /ruby.*6.0%/i,
  );
  expect(screen.getByLabelText("Enchanted bolt effect")).toHaveTextContent(
    /500 HP/,
  );
  expect(screen.getByText(/Ordinary hit: max 20/)).toBeVisible();
});

test("custom base HP edits and clearing current HP preserve nullable defaults", () => {
  const patches: unknown[] = [];
  const { rerender } = render(
    <TargetHitpointsFields
      target={target}
      onChange={(patch) => patches.push(patch)}
    />,
  );
  expect(screen.getByLabelText("Target base hitpoints")).not.toHaveAttribute(
    "readonly",
  );
  fireEvent.change(screen.getByLabelText("Target base hitpoints"), {
    target: { value: "600" },
  });
  fireEvent.change(screen.getByLabelText("Target current hitpoints"), {
    target: { value: "99" },
  });
  rerender(
    <TargetHitpointsFields
      target={{ ...target, current_hitpoints: 99 }}
      onChange={(patch) => patches.push(patch)}
    />,
  );
  fireEvent.change(screen.getByLabelText("Target current hitpoints"), {
    target: { value: "" },
  });
  expect(patches[0]).toMatchObject({ combatTarget: { hitpoints: 600 } });
  expect(patches[2]).toMatchObject({
    combatTarget: { current_hitpoints: null },
  });
});
