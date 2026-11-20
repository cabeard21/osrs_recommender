import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PotionFields } from "../components/PotionFields";
import { SecondaryPrioritySummary } from "../components/SecondaryPrioritySummary";
import { FixtureGearClient } from "../fixtures/client";
import { newDraft, normalize } from "../state/scenario";
import type { JointSolutionDTO } from "../api/contracts";
it("shows actual base and boosted levels, application and dose prices", async () => {
  const result = await new FixtureGearClient("none", 0).optimize(
    normalize(newDraft(), "x"),
    new AbortController().signal,
  );
  const solution = {
    potions: {
      selected_ids: ["super_strength"],
      base_levels: { strength: 99 },
      boosted_levels: { strength: 118 },
      cost_per_application_gp: 250,
      model_version: "test",
      resources: [{ name: "Super strength", cost_per_dose_gp: 250 }],
    },
  } as unknown as JointSolutionDTO;
  render(<SecondaryPrioritySummary result={result} solution={solution} />);
  expect(screen.getByText(/Strength 99 → 118/)).toBeInTheDocument();
  expect(
    screen.getByText(/250 GP per complete application/),
  ).toBeInTheDocument();
  expect(screen.getByText(/250 GP per dose/)).toBeInTheDocument();
});
it("shows how much the potions add over the best no-potion loadout", async () => {
  const fixture = await new FixtureGearClient("none", 0).optimize(
    normalize(newDraft(), "x"),
    new AbortController().signal,
  );
  const result = {
    ...fixture,
    live: {
      result: {
        search: {
          potion_selection: { no_potion_score_by_swap_limit: [4, 5] },
        },
      },
    },
  } as unknown as typeof fixture;
  const solution = {
    score: 5.5,
    potions: {
      selected_ids: ["super_strength"],
      boosted_levels: { strength: 118 },
      cost_per_application_gp: null,
      model_version: "test",
    },
  } as unknown as JointSolutionDTO;
  render(
    <SecondaryPrioritySummary
      result={result}
      solution={solution}
      potionCatalog={[{ id: "super_strength", name: "Super strength" }]}
    />,
  );
  expect(screen.getByText("+0.50 DPS (+10.0%)")).toBeInTheDocument();
  expect(screen.getByText("Super strength")).toBeInTheDocument();
});

it("quick selections replace the allowed potions", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(
    <PotionFields
      policy={{ mode: "optimize", allowed_ids: [], selected_ids: [] }}
      catalog={[
        { id: "attack", name: "Attack potion" },
        { id: "super_attack", name: "Super attack" },
        { id: "divine_super_attack", name: "Divine super attack" },
      ]}
      onChange={onChange}
    />,
  );
  expect(screen.getByRole("button", { name: "None" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "No divines" }));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "optimize",
    allowed_ids: ["attack", "super_attack"],
    selected_ids: [],
  });
});

import userEvent from "@testing-library/user-event";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
it("runs the configured potion scenario and marks results outdated on changes", async () => {
  const user = userEvent.setup();
  render(
    <GearProvider>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Demo adventurer", { exact: true });
  await user.click(
    screen.getByText(/^Combat resources/, { selector: "summary" }),
  );
  const toggle = screen.getByLabelText("Optimize potions");
  expect(toggle).not.toBeChecked();
  await user.click(toggle);
  expect(screen.getByText(/No potions allowed yet/)).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: "Run fixture optimization" }),
  );
  await screen.findByText("Fixture result", { exact: true });
  await user.click(toggle);
  expect(screen.getByText(/Result outdated/)).toBeVisible();
});
