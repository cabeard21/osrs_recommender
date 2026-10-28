import { expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { contextFixture } from "../fixtures/client";
import { newDraft, normalize } from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { selectedCombatOptions, setCombatOptionEnabled } from "../api/combatOptions";
import { CombatOptionsControls } from "../components/CombatOptionsControls";
import type { GearContext } from "../api/contracts";

function context(magicEligible = false): GearContext {
  return {
    ...contextFixture,
    source: "live",
    live: {
      capabilities: {
        combat_options: {
          attack_types: ["stab", "slash", "crush", "light", "standard", "heavy", "magic"].map((id) => ({ id, available: true })),
          stances: ["accurate", "aggressive", "defensive", "controlled", "rapid", "longrange"].map((id) => ({ id, available: true })),
          spells: [
            { id: "wind_strike", available: true },
            { id: "fire_wave", available: magicEligible, reason: magicEligible ? undefined : "Magic level unmet" },
          ],
        },
      },
    } as unknown as GearContext["live"],
  };
}

test("defaults to every eligible option and preserves explicit exclusions across sync", () => {
  const role = { ...newDraft().roles[0], style: "magic" as const };
  const initial = selectedCombatOptions(role, context());
  expect(initial?.spells).toEqual(["wind_strike"]);
  const disabled = setCombatOptionEnabled(role, "spells", "wind_strike", false, context());
  expect(selectedCombatOptions(disabled, context())?.spells).toEqual([]);
  expect(selectedCombatOptions(disabled, context(true))?.spells).toEqual([]);
  expect(disabled.combatOptionExplicitlyEmpty?.spells).toBe(true);
  const reenabled = setCombatOptionEnabled(disabled, "spells", "fire_wave", true, context(true));
  expect(selectedCombatOptions(reenabled, context(true))?.spells).toEqual(["fire_wave"]);
});

test("newly eligible options are selected when the user did not explicitly empty the group", () => {
  const role = { ...newDraft().roles[0], style: "magic" as const };
  expect(selectedCombatOptions(role, context(true))?.spells).toEqual(["wind_strike", "fire_wave"]);
});

test("empty filters are sent explicitly and disabled optimization retains fixed assumptions", () => {
  const draft = newDraft();
  draft.roles[0] = {
    ...draft.roles[0],
    combatOptionDisabled: {
      attack_types: ["stab", "slash", "crush"],
      stances: [],
      spells: [],
    },
  };
  const request = optimizationRequest(normalize(draft, "fixture-snapshot-01", true, context()));
  expect(request.roles[0].combat_options?.attack_types).toEqual([]);
  draft.roles[0].combatOptionOptimization = false;
  expect(optimizationRequest(normalize(draft, "fixture-snapshot-01", true, context())).roles[0].combat_options).toBeUndefined();
});

test("live optimization requires account combat capabilities", () => {
  expect(() => normalize(newDraft(), "fixture-snapshot-01", true, contextFixture)).toThrow(/Synced combat options are unavailable/);
  const fixed = newDraft();
  fixed.roles[0].combatOptionOptimization = false;
  expect(optimizationRequest(normalize(fixed, "fixture-snapshot-01", true, contextFixture)).roles[0].combat_options).toBeUndefined();
});

test("Combat Options controls allow an empty selection and resetting defaults", async () => {
  const user = userEvent.setup();
  const role = newDraft().roles[0];
  const onChange = vi.fn();
  render(<CombatOptionsControls role={role} context={context()} liveMode onChange={onChange} />);
  await user.click(screen.getByText("Combat Options"));
  await user.click(screen.getByRole("checkbox", { name: "stab" }));
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ combatOptionDisabled: expect.objectContaining({ attack_types: ["stab"] }) }));
  await user.click(screen.getByRole("button", { name: "Reset to Defaults" }));
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ combatOptionOptimization: true, combatOptionDisabled: { attack_types: [], stances: [], spells: [] }, combatOptionExplicitlyEmpty: {} }));
});

test("Select All clears an explicit empty group", async () => {
  const user = userEvent.setup();
  const role = {
    ...newDraft().roles[0],
    combatOptionDisabled: { attack_types: ["stab", "slash", "crush"], stances: [], spells: [] },
    combatOptionExplicitlyEmpty: { attack_types: true },
  };
  const onChange = vi.fn();
  render(<CombatOptionsControls role={role} context={context()} liveMode onChange={onChange} />);
  await user.click(screen.getByText("Combat Options"));
  await user.click(screen.getByRole("button", { name: "Select All attack types" }));
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
    combatOptionDisabled: expect.objectContaining({ attack_types: [] }),
    combatOptionExplicitlyEmpty: { attack_types: false },
  }));
});

test("eligible Magic spells can be selected in Combat Options", async () => {
  const user = userEvent.setup();
  const role = { ...newDraft().roles[0], style: "magic" as const };
  const onChange = vi.fn();
  render(<CombatOptionsControls role={role} context={context()} liveMode onChange={onChange} />);
  await user.click(screen.getByText("Combat Options"));
  const wind = screen.getByRole("checkbox", { name: "wind strike" });
  expect(wind).toBeEnabled();
  expect(wind).toBeChecked();
  await user.click(wind);
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
    combatOptionExplicitlyEmpty: expect.objectContaining({ spells: true }),
  }));
});
