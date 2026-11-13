import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import {
  newDraft,
  newRole,
  normalize,
  upgradeStoredDraft,
  initialState,
  reducer,
} from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { describeDraftChanges } from "../state/draftChanges";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { performanceMetrics } from "../api/runtime";
import type { CombatPerformance, OptimizationReply } from "../api/contracts";
import { matchesOptimizationPolicy } from "../api/optimizationModes";
import { saveSetup, readSavedSetups } from "../state/savedSetups";

it("defaults legacy roles to off without mutating stored drafts", () => {
  const draft = newDraft();
  const legacy = {
    ...draft,
    roles: draft.roles.map(({ onSlayerTask: _, ...role }) => role),
  };
  expect(upgradeStoredDraft(legacy)?.roles[0].onSlayerTask).toBe(false);
  expect(legacy.roles[0]).not.toHaveProperty("onSlayerTask");
  expect(
    upgradeStoredDraft({
      ...draft,
      roles: [{ ...draft.roles[0], onSlayerTask: "yes" }],
    }),
  ).toBeNull();
});

it("transports independent task flags and identifies draft changes", () => {
  const draft = newDraft();
  const selected = {
    ...draft,
    roles: [
      { ...draft.roles[0], onSlayerTask: true, autoDiscipline: true },
      newRole(2),
    ],
  };
  const scenario = normalize(selected, "snapshot");
  expect(
    optimizationRequest(scenario).roles.map((r) => r.on_slayer_task),
  ).toEqual([true, false]);
  expect(
    describeDraftChanges(selected, normalize(draft, "snapshot").request),
  ).toContain("Configuration 1 Slayer task: off → on");
});

it("offers a saved checkbox and retains it when changing discipline", async () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <App />
    </GearProvider>,
  );
  const checkbox = await screen.findByLabelText("On a Slayer task");
  expect(checkbox).not.toBeChecked();
  expect(checkbox).toHaveAccessibleDescription(
    "This target counts toward my current Slayer task.",
  );
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "magic" }));
  expect(checkbox).toBeChecked();
});

const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 29,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
  slayer_effects: [
    {
      item_id: 11865,
      kind: "mask",
      accuracy_numerator: 23,
      damage_numerator: 23,
      denominator: 20,
      base_max_hit: null,
    },
    {
      item_id: 21255,
      kind: "magic_dart",
      accuracy_numerator: 1,
      damage_numerator: 1,
      denominator: 1,
      base_max_hit: 25,
    },
  ],
};

it("explains applied mask and enchanted Magic Dart effects", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "magic",
        attackType: "slash",
        stance: "accurate",
        spell: "magic_dart",
      }}
      weapon="Slayer's staff (e)"
      performance={performance}
    />,
  );
  const effects = screen.getAllByLabelText("Slayer task effect");
  expect(effects[0]).toHaveTextContent("+15% accuracy and damage");
  expect(effects[0]).toHaveTextContent("#11865");
  expect(effects[1]).toHaveTextContent("Magic Dart base max hit 25");
});

it("rejects malformed effect metadata", () => {
  expect(() =>
    performanceMetrics({
      ...performance,
      slayer_effects: [{ ...performance.slayer_effects![0], denominator: 0 }],
    }),
  ).toThrow(/Slayer/);
});

it("preserves task status in saved setups", () => {
  const draft = newDraft();
  const selected = {
    ...draft,
    roles: [{ ...draft.roles[0], onSlayerTask: true }],
  };
  saveSetup("Task setup", "single", selected, sessionStorage);
  expect(readSavedSetups(sessionStorage)[0].draft.roles[0].onSlayerTask).toBe(
    true,
  );
});

it("rejects results evaluated with different task settings", () => {
  const draft = newDraft();
  const scenario = normalize(draft, "snapshot");
  const selected = {
    ...draft,
    roles: [{ ...draft.roles[0], onSlayerTask: true }],
  };
  const result = {
    scenario: normalize(selected, "snapshot"),
  } as OptimizationReply;
  expect(
    matchesOptimizationPolicy({ scenario } as OptimizationReply, result),
  ).toBe(false);
  const state = reducer(initialState(), {
    type: "start",
    mode: "single",
    scenario,
    generation: 1,
  });
  const updated = reducer(state, {
    type: "success",
    mode: "single",
    generation: 1,
    result,
  });
  expect(updated.single.result).toBeNull();
  expect(updated.single.error).toMatch(/Slayer task settings changed/);
});
