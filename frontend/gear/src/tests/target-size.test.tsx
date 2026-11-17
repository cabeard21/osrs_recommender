import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { TargetFields } from "../components/TargetFields";
import { RoleTargetEditor } from "../components/RoleTargetEditor";
import { newDraft } from "../state/scenario";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { performanceMetrics } from "../api/runtime";

const sizePerformance = {
  supported: true,
  dps: 5,
  max_hit: 40,
  accuracy: 0.8,
  attack_interval: 3.6,
  bonuses: {},
  limitations: [],
  size_damage_bonus: { item_id: 27021, target_size: 5, max_hit_bonus: 10 },
};

it("reports the evaluated size damage bonus", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "melee",
        attackType: "slash",
        stance: "accurate",
        spell: "",
      }}
      weapon="Colossal blade"
      performance={sizePerformance}
    />,
  );
  expect(screen.getByLabelText("Target size weapon effect")).toHaveTextContent(
    "+10 max hit against size 5",
  );
  expect(performanceMetrics(sizePerformance).maxHit).toBe(40);
});

it.each([
  { item_id: 0 },
  { target_size: -1 },
  { target_size: 65 },
  { max_hit_bonus: -1 },
  { target_size: 1.5 },
  { max_hit_bonus: Number.NaN },
])("rejects invalid size effect metadata %j", (invalid) => {
  expect(() =>
    performanceMetrics({
      ...sizePerformance,
      size_damage_bonus: { ...sizePerformance.size_damage_bonus, ...invalid },
    }),
  ).toThrow(/size/i);
});

it("edits custom global target size while retaining other stats", () => {
  const draft = newDraft();
  draft.combatTarget = {
    name: "Custom",
    defence_level: 42,
    magic_level: 10,
    bonuses: {},
    size: 2,
  };
  const change = vi.fn();
  render(
    <TargetFields
      draft={draft}
      liveMode={false}
      targets={[]}
      errors={{}}
      change={change}
    />,
  );
  fireEvent.change(screen.getByLabelText("Target size"), {
    target: { value: "5" },
  });
  expect(change).toHaveBeenLastCalledWith(
    expect.objectContaining({
      combatTarget: { ...draft.combatTarget, size: 5 },
      targetInputs: { size: "5" },
    }),
  );
});

it("edits custom role target size with a backward-compatible default", () => {
  const draft = newDraft();
  const change = vi.fn();
  render(
    <RoleTargetEditor
      draft={draft}
      role={draft.roles[0]}
      targets={[]}
      onChange={change}
    />,
  );
  const input = screen.getByLabelText("Role target size");
  expect(input).toHaveValue(1);
  fireEvent.change(input, { target: { value: "3" } });
  expect(change).toHaveBeenLastCalledWith(
    expect.objectContaining({
      combatTarget: expect.objectContaining({ size: 3 }),
      targetInputs: { size: "3" },
    }),
  );
});

it("clears stale custom inputs when selecting a global target preset", () => {
  const draft = newDraft();
  draft.targetInputs = { size: "", flat_armour: "5" };
  draft.combatTarget = {
    name: "Custom",
    defence_level: 1,
    magic_level: 1,
    bonuses: {},
    size: 5,
  };
  const preset = {
    name: "Preset",
    defence_level: 20,
    magic_level: 10,
    bonuses: {},
    size: 2,
  };
  const change = vi.fn();
  render(
    <TargetFields
      draft={draft}
      liveMode={true}
      targets={[preset]}
      errors={{}}
      change={change}
    />,
  );
  fireEvent.change(screen.getByLabelText("Target selection"), {
    target: { value: "Preset" },
  });
  expect(change).toHaveBeenLastCalledWith(
    expect.objectContaining({ combatTarget: preset, targetInputs: {} }),
  );
});
