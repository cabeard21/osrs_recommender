import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import type { OptimizationProgress, Scenario } from "../api/contracts";
import { formatDuration } from "../components/RunStatus";

async function startRun(): Promise<(value: OptimizationProgress) => void> {
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
  return (value) => update(value);
}

it("formats remaining time compactly", () => {
  expect(formatDuration(0.2)).toBe("1s");
  expect(formatDuration(59)).toBe("59s");
  expect(formatDuration(125)).toBe("2m 05s");
});

it("renders a single search's bar, stage checklist and ETA", async () => {
  const update = await startRun();
  act(() =>
    update({
      phase: "gear_search",
      label: "Searching gear combinations",
      completed: 0,
      total: 0,
      elapsed_seconds: 4,
      fraction: 0.456,
      eta_seconds: 75,
      stages: [
        {
          id: "preparation",
          label: "Preparing account facts",
          status: "complete",
          fraction: 1,
        },
        {
          id: "gear_search",
          label: "Searching gear combinations",
          status: "active",
          fraction: 0.3,
        },
      ],
    }),
  );
  expect(
    screen.getByRole("status", { name: "Optimization progress" }),
  ).toHaveTextContent(/^Searching gear combinations$/);
  expect(
    screen.getByRole("progressbar", { name: "Optimization completion" }),
  ).toHaveAttribute("aria-valuenow", "46");
  expect(screen.getByText(/1m 15s left/)).toBeInTheDocument();
  const stages = screen.getByRole("list", { name: "Optimization stages" });
  expect(stages).toHaveTextContent("Searching gear combinations30%");
  expect(
    screen.queryByRole("list", { name: "Parallel searches" }),
  ).not.toBeInTheDocument();
});

it("shows lane counts and running searches instead of overlapping stages", async () => {
  const update = await startRun();
  act(() =>
    update({
      phase: "gear_search",
      label: "Running 16 searches",
      completed: 6,
      total: 16,
      elapsed_seconds: 291,
      fraction: 0.5,
      eta_seconds: 301,
      lane_counts: { complete: 6, running: 3, pending: 7 },
      stages: [
        {
          id: "preparation",
          label: "Preparing account facts",
          status: "complete",
          fraction: 1,
        },
        {
          id: "gear_search",
          label: "Searching gear combinations",
          status: "active",
          fraction: 0.3,
        },
        {
          id: "merge",
          label: "Combining results",
          status: "pending",
          fraction: 0,
        },
      ],
      lanes: [
        {
          label: "Melee · Super combat",
          status: "running",
          stage: "gear_search",
          stage_label: "Searching gear combinations",
          fraction: 0.42,
        },
        {
          label: "Magic · No potions",
          status: "running",
          stage: "frontiers",
          stage_label: "Exploring trade-offs",
          fraction: 0.8,
        },
      ],
    }),
  );
  expect(
    screen.getByRole("status", { name: "Optimization progress" }),
  ).toHaveTextContent("Running 16 searches · 6/16 complete");
  expect(screen.getByText("6 done · 3 running · 7 queued")).toBeInTheDocument();
  expect(
    screen.queryByRole("list", { name: "Optimization stages" }),
  ).not.toBeInTheDocument();
  const lanes = screen.getByRole("list", { name: "Parallel searches" });
  expect(lanes).toHaveTextContent(
    "Melee · Super combatSearching gear combinations42%",
  );
  expect(lanes).toHaveTextContent("Magic · No potionsExploring trade-offs80%");
});

it("labels finished and queued searches when all rows fit", async () => {
  const update = await startRun();
  act(() =>
    update({
      phase: "frontiers",
      label: "Running 3 searches",
      completed: 1,
      total: 3,
      elapsed_seconds: 4,
      lanes: [
        { label: "Melee", status: "complete", stage: null, fraction: 1 },
        { label: "Ranged", status: "pending", stage: null, fraction: 0 },
      ],
    }),
  );
  const lanes = screen.getByRole("list", { name: "Parallel searches" });
  expect(lanes).toHaveTextContent("MeleeDone");
  expect(lanes).toHaveTextContent("RangedQueued");
});

it("shows current profile progress and hides cancelled late updates", async () => {
  const update = await startRun();
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
