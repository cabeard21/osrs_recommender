import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
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
  expect(screen.getByText(/strength 99 → 118/)).toBeInTheDocument();
  expect(
    screen.getByText(/250 GP per complete application/),
  ).toBeInTheDocument();
  expect(screen.getByText(/250 GP per dose/)).toBeInTheDocument();
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
  const toggle = screen.getByLabelText("Optimize potions");
  expect(toggle).not.toBeChecked();
  await user.click(toggle);
  expect(screen.getByText(/Empty selection permits no potions/)).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: "Run fixture optimization" }),
  );
  await screen.findByText("Fixture result", { exact: true });
  await user.click(toggle);
  expect(screen.getByText(/Result outdated/)).toBeVisible();
});
