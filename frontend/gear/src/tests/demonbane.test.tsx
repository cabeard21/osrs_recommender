import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient, contextFixture } from "../fixtures/client";
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
import { spellQuickPicks } from "../api/combatOptions";
import type {
  CombatPerformance,
  OptimizationReply,
  GearContext,
} from "../api/contracts";
import { matchesOptimizationPolicy } from "../api/optimizationModes";
import { saveSetup, readSavedSetups } from "../state/savedSetups";

it("defaults legacy roles to off without mutating stored drafts", () => {
  const draft = newDraft();
  const legacy = {
    ...draft,
    roles: draft.roles.map(({ markOfDarkness: _, ...role }) => role),
  };
  expect(upgradeStoredDraft(legacy)?.roles[0].markOfDarkness).toBe(false);
  expect(legacy.roles[0]).not.toHaveProperty("markOfDarkness");
  expect(
    upgradeStoredDraft({
      ...draft,
      roles: [{ ...draft.roles[0], markOfDarkness: "yes" }],
    }),
  ).toBeNull();
});

it("transports independent Mark flags and identifies draft changes", () => {
  const draft = newDraft();
  const selected = {
    ...draft,
    roles: [
      { ...draft.roles[0], markOfDarkness: true, autoDiscipline: true },
      newRole(2),
    ],
  };
  const scenario = normalize(selected, "snapshot");
  expect(
    optimizationRequest(scenario).roles.map((r) => r.mark_of_darkness),
  ).toEqual([true, false]);
  expect(
    describeDraftChanges(selected, normalize(draft, "snapshot").request),
  ).toContain("Configuration 1 Mark of Darkness: off → on");
});

it("offers a saved checkbox for magic and retains it in Auto", async () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <App />
    </GearProvider>,
  );
  await screen.findByLabelText("On a Slayer task");
  fireEvent.click(screen.getByRole("button", { name: "magic" }));
  const checkbox = await screen.findByLabelText("Maintain Mark of Darkness");
  expect(checkbox).not.toBeChecked();
  expect(checkbox).toHaveAccessibleDescription(
    "Applies to demonbane spells only; includes rune upkeep. Refreshes use the selected weapon.",
  );
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "Auto" }));
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
  demonbane_bonus: {
    item_id: 29594,
    spell: "dark_demonbane",
    accuracy_percent: 80,
    damage_percent: 50,
    vulnerability_percent: 100,
    mark_of_darkness: true,
  },
};

it("explains the demonbane bonus and maintained Mark", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "magic",
        attackType: "slash",
        stance: "accurate",
        spell: "dark_demonbane",
      }}
      weapon="Purging staff"
      performance={performance}
    />,
  );
  expect(screen.getByLabelText("Demonbane effect")).toHaveTextContent(
    "+80% accuracy",
  );
  expect(screen.getByLabelText("Demonbane effect")).toHaveTextContent(
    "Mark of Darkness maintained; rune upkeep included",
  );
});

it("rejects malformed demonbane metadata", () => {
  expect(() =>
    performanceMetrics({
      ...performance,
      demonbane_bonus: {
        ...performance.demonbane_bonus!,
        vulnerability_percent: -1,
      },
    }),
  ).toThrow(/demonbane/);
  expect(() =>
    performanceMetrics({ ...performance, demonbane_bonus: [] as never }),
  ).toThrow();
});

it("preserves Mark in saved setups and rejects mismatched result settings", () => {
  const draft = newDraft();
  const scenario = normalize(draft, "snapshot");
  const selected = {
    ...draft,
    roles: [{ ...draft.roles[0], markOfDarkness: true }],
  };
  saveSetup("Mark setup", "single", selected, sessionStorage);
  expect(readSavedSetups(sessionStorage)[0].draft.roles[0].markOfDarkness).toBe(
    true,
  );
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
  expect(updated.single.error).toMatch(/Mark of Darkness settings changed/);
});

it("selects only available demonbane spells and adds the highest available tier", () => {
  const context = {
    ...contextFixture,
    live: {
      capabilities: {
        combat_options: {
          attack_types: [],
          stances: [],
          spells: [
            { id: "inferior_demonbane", available: true },
            { id: "superior_demonbane", available: true },
            { id: "dark_demonbane", available: false },
          ],
        },
      },
    },
  } as unknown as GearContext;
  const picks = spellQuickPicks({ ...newRole(1), style: "magic" }, context);
  expect(picks.find((pick) => pick.label === "Demonbane")?.ids).toEqual([
    "inferior_demonbane",
    "superior_demonbane",
  ]);
  expect(picks.find((pick) => pick.label === "Highest tier")?.ids).toEqual([
    "superior_demonbane",
  ]);
});

it("shows reduced effectiveness in the applied weapon bonus", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "melee",
        attackType: "slash",
        stance: "accurate",
        spell: "fire_strike",
      }}
      weapon="Emberlight"
      performance={{
        ...performance,
        demonbane_bonus: {
          item_id: 29589,
          spell: null,
          accuracy_percent: 70,
          damage_percent: 70,
          vulnerability_percent: 70,
          mark_of_darkness: false,
        },
      }}
    />,
  );
  expect(screen.getByLabelText("Demonbane effect")).toHaveTextContent(
    "+49% accuracy and +49% maximum hit",
  );
  expect(screen.getByLabelText("Demonbane effect")).toHaveTextContent(
    "70% target effectiveness",
  );
});
