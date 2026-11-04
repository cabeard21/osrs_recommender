import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import type { OptimizationProgress, Scenario } from "../api/contracts";
it("shows current profile progress and hides cancelled late updates", async () => {
  let update!: (value: OptimizationProgress) => void;
  class ProgressClient extends FixtureGearClient {
    override optimize(
      _scenario: Scenario,
      _signal: AbortSignal,
      onProgress?: (value: OptimizationProgress) => void,
    ): ReturnType<FixtureGearClient["optimize"]> {
      update = onProgress!;
      return new Promise(() => {});
    }
  }
  render(
    <GearProvider client={new ProgressClient("none", 0)}>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Demo adventurer", { exact: true });
  fireEvent.click(
    screen.getByRole("button", { name: "Run fixture optimization" }),
  );
  act(() =>
    update({
      phase: "searching_profiles",
      completed: 2,
      total: 4,
      elapsed_seconds: 3,
    }),
  );
  expect(
    screen.getByRole("status", { name: "Optimization progress" }),
  ).toHaveTextContent("searching profiles · 2/4 profiles complete");
  fireEvent.click(screen.getByRole("button", { name: /Cancel/ }));
  act(() =>
    update({ phase: "complete", completed: 4, total: 4, elapsed_seconds: 5 }),
  );
  expect(
    screen.queryByRole("status", { name: "Optimization progress" }),
  ).not.toBeInTheDocument();
});
