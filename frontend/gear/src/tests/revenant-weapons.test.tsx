import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { CombatPerformance } from "../api/contracts";
import { performanceMetrics } from "../api/runtime";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { WildernessSettings } from "../components/WildernessSettings";
import { newDraft } from "../state/scenario";

const draft = newDraft();
const performance = {
  supported: true,
  max_hit: 20,
  accuracy: 0.9,
  attack_interval: 2.4,
  dps: 3.75,
  bonuses: {},
  limitations: [],
};

it("explains the combat effect of enabling Wilderness before a run", () => {
  render(
    <WildernessSettings
      draft={draft}
      change={vi.fn()}
      changeObjectives={vi.fn()}
    />,
  );
  expect(
    screen.getByRole("checkbox", { name: "Wilderness" }),
  ).toHaveAccessibleDescription(/every NPC fight.*charged revenant weapons/i);
});

it("displays the reported passive state and accepts older results", () => {
  const summary = (result: CombatPerformance) => (
    <CombatOptionSummary
      role={draft.roles[0]}
      weapon="Viggora's chainmace"
      performance={result}
    />
  );
  const { rerender } = render(
    summary({ ...performance, wilderness_weapon_passive: true }),
  );
  expect(screen.getByLabelText("Wilderness weapon passive")).toHaveTextContent(
    "+50% attack roll",
  );
  rerender(summary({ ...performance, wilderness_weapon_passive: false }));
  expect(screen.getByLabelText("Wilderness weapon passive")).toHaveTextContent(
    "inactive",
  );
  rerender(summary(performance));
  expect(screen.queryByLabelText("Wilderness weapon passive")).toBeNull();
  expect(() => performanceMetrics(performance)).not.toThrow();
});

it("rejects an invalid passive state in a result", () => {
  const invalid = { ...performance, wilderness_weapon_passive: "on" };
  expect(() =>
    performanceMetrics(invalid as unknown as CombatPerformance),
  ).toThrow(/Wilderness/);
});
