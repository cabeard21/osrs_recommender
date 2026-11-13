import { readDrafts, storageKey } from "../state/scenario";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import {
  initialState,
  reducer,
  newDraft,
  normalize,
  upgradeStoredDraft,
} from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { describeDraftChanges } from "../state/draftChanges";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { performanceMetrics } from "../api/runtime";
import { matchesOptimizationPolicy } from "../api/optimizationModes";
import type { OptimizationReply } from "../api/contracts";
import type { CombatPerformance } from "../api/contracts";

it("defaults old drafts to burnt and sends the explicit selected page mode", () => {
  const draft = newDraft();
  expect(draft.fireTomePages).toBe("burnt");
  expect(
    upgradeStoredDraft({ ...draft, fireTomePages: undefined })?.fireTomePages,
  ).toBe("burnt");
  expect(upgradeStoredDraft({ ...draft, fireTomePages: "invalid" })).toBeNull();
  const searing = { ...draft, fireTomePages: "searing" as const };
  const scenario = normalize(searing, "snapshot");
  expect(scenario.request.fire_tome_pages).toBe("searing");
  expect(optimizationRequest(scenario).fire_tome_pages).toBe("searing");
  expect(
    describeDraftChanges(searing, normalize(draft, "snapshot").request),
  ).toContain("Tome of Fire pages: burnt → searing");
});

it("allows selecting Fire page mode for the entire scenario", async () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <App />
    </GearProvider>,
  );
  const select = await screen.findByLabelText("Tome of Fire pages");
  expect(select).toHaveValue("burnt");
  fireEvent.change(select, { target: { value: "searing" } });
  expect(select).toHaveValue("searing");
  expect(
    screen.getByText(
      /Tome page availability, consumption, and costs are excluded/,
    ),
  ).toBeInTheDocument();
});

const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 26,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
  tome_bonus: {
    item_id: 20714,
    element: "fire",
    damage_percent: 10,
    accuracy_percent: 0,
    fire_pages: "searing",
    minimum_hit: 2,
  },
};
it("reports the evaluated tome effect and successful minimum", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "magic",
        attackType: "slash",
        stance: "accurate",
        spell: "fire_surge",
      }}
      weapon="Staff"
      performance={performance}
    />,
  );
  expect(screen.getByLabelText("Elemental tome effect")).toHaveTextContent(
    "Fire tome: +10% damage",
  );
  expect(screen.getByLabelText("Elemental tome effect")).toHaveTextContent(
    "searing pages; successful minimum hit 2",
  );
});
it("rejects malformed tome effect metadata", () => {
  expect(() =>
    performanceMetrics({
      ...performance,
      tome_bonus: { ...performance.tome_bonus!, minimum_hit: -1 },
    }),
  ).toThrow(/tome/i);
});

it("rejects invalid draft modes without silently selecting burnt", () => {
  expect(() =>
    normalize({ ...newDraft(), fireTomePages: "invalid" as never }, "snapshot"),
  ).toThrow(/Tome of Fire/);
});
it("keeps results with different Fire page modes incomparable", () => {
  const burnt = {
    scenario: normalize(newDraft(), "snapshot"),
  } as OptimizationReply;
  const legacy = {
    scenario: {
      ...burnt.scenario,
      request: { ...burnt.scenario.request, fire_tome_pages: undefined },
    },
  } as OptimizationReply;
  const searing = {
    scenario: normalize(
      { ...newDraft(), fireTomePages: "searing" },
      "snapshot",
    ),
  } as OptimizationReply;
  expect(matchesOptimizationPolicy(burnt, legacy)).toBe(true);
  expect(matchesOptimizationPolicy(burnt, searing)).toBe(false);
});
it("accepts Water and legacy combat metadata", () => {
  expect(performanceMetrics({ ...performance, tome_bonus: null }).dps).toBe(4);
  expect(
    performanceMetrics({
      ...performance,
      tome_bonus: {
        item_id: 25574,
        element: "water",
        damage_percent: 10,
        accuracy_percent: 20,
        fire_pages: null,
        minimum_hit: 1,
      },
    }).dps,
  ).toBe(4);
});

it("rejects a completed run whose Fire page mode differs from the submitted scenario", () => {
  const scenario = normalize(newDraft(), "snapshot");
  const state = reducer(initialState(), {
    type: "start",
    mode: "single",
    scenario,
    generation: 1,
  });
  const result = {
    scenario: normalize(
      { ...newDraft(), fireTomePages: "searing" },
      "snapshot",
    ),
  } as OptimizationReply;
  const updated = reducer(state, {
    type: "success",
    mode: "single",
    generation: 1,
    result,
  });
  expect(updated.single.pending).toBe(false);
  expect(updated.single.result).toBeNull();
  expect(updated.single.error).toMatch(/Tome of Fire pages changed/);
});

it("loads normalized defaults from legacy stored drafts and preserves selected pages", () => {
  const {
    fireTomePages: _oldPages,
    supportPolicy: _oldPolicy,
    ...legacy
  } = newDraft();
  sessionStorage.setItem(
    storageKey("legacy-player"),
    JSON.stringify({
      version: 3,
      single: legacy,
      multi: { ...newDraft(), fireTomePages: "searing" },
      multiSeeded: false,
    }),
  );
  const restored = readDrafts("legacy-player", sessionStorage);
  expect(restored?.single.fireTomePages).toBe("burnt");
  expect(restored?.single.supportPolicy).toBe("community_best_effort");
  expect(restored?.multi.fireTomePages).toBe("searing");
});
