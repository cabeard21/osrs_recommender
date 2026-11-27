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

it("shows a rounded search-only range until a full ETA or merge arrives", async () => {
  const update = await startRun();
  const searching: OptimizationProgress = {
    phase: "frontiers",
    completed: 12,
    total: 16,
    elapsed_seconds: 270,
    lane_counts: { complete: 12, running: 4, pending: 0 },
    eta_seconds: null,
    search_eta_range_seconds: [132.1, 181.9],
  };
  act(() => update(searching));
  expect(screen.getByText(/≈ 2m–3m 15s left in searches/)).toBeVisible();
  expect(screen.queryByText(/Estimating time left/)).not.toBeInTheDocument();

  act(() => update({ ...searching, eta_seconds: 192 }));
  expect(screen.getByText(/3m 12s left/)).toBeVisible();
  expect(screen.queryByText(/left in searches/)).not.toBeInTheDocument();

  act(() => update({ ...searching, phase: "merge", completed: 16 }));
  expect(
    screen.getByRole("status", { name: "Optimization progress" }),
  ).toHaveTextContent("Combining results");
  expect(screen.queryByText(/left in searches/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Estimating time left/)).not.toBeInTheDocument();
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

it("keeps active rows aligned across colliding labels and worker reuse", async () => {
  const update = await startRun();
  const collidingLabel =
    "role-1: Magic / role-2: Ranged · Divine magic, Divine rangin";
  const live = [33, 34, 35, 36, 37, 38].map((lane_id) => ({
    lane_id,
    label:
      lane_id === 33 || lane_id === 37 ? collidingLabel : `Profile ${lane_id}`,
    status: "running" as const,
    stage: "frontiers",
    stage_label: "Exploring trade-offs",
    stage_fraction: lane_id === 37 ? 0.4 : null,
    fraction: 0.99,
  }));
  const checkpoint: OptimizationProgress = {
    phase: "frontiers",
    completed: 33,
    total: 40,
    elapsed_seconds: 1031,
    eta_seconds: null,
    fraction: 0.92,
    lane_counts: { complete: 33, running: 6, pending: 1 },
    lanes: live,
  };
  act(() => update(checkpoint));
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(6);
  expect(rows[0]).toHaveTextContent("Exploring trade-offs");
  expect(rows[0]).not.toHaveTextContent("99%");
  expect(rows[4]).toHaveTextContent("40%");
  expect(screen.getByText(/Estimating time left/)).toBeVisible();
  expect(
    screen.getByRole("progressbar", { name: "Searches completed" }),
  ).toHaveAttribute("aria-valuenow", "33");

  act(() =>
    update({
      ...checkpoint,
      lane_counts: { complete: 33, running: 6, pending: 0, collecting: 1 },
      lanes: [
        ...live.slice(1),
        { ...live[0], lane_id: 39, label: "New search" },
      ],
    }),
  );
  expect(screen.getAllByRole("listitem")).toHaveLength(6);
  expect(screen.getAllByText(collidingLabel)).toHaveLength(1);
  expect(rows[4]).toBeInTheDocument();
  expect(rows[0]).not.toBeInTheDocument();
  expect(screen.getByText(/1 collecting/)).toBeVisible();

  act(() =>
    update({
      ...checkpoint,
      phase: "merge",
      completed: 40,
      lanes: [],
      lane_counts: { complete: 40, running: 0, pending: 0 },
    }),
  );
  expect(screen.getByRole("status")).toHaveTextContent("Combining results");
  expect(
    screen.queryByRole("list", { name: "Parallel searches" }),
  ).not.toBeInTheDocument();

  act(() =>
    update({
      ...checkpoint,
      phase: "complete",
      completed: 40,
      lanes: [],
      lane_counts: { complete: 40, running: 0, pending: 0 },
      eta_seconds: 0,
    }),
  );
  expect(screen.getByRole("status")).toHaveTextContent("Finalizing results");
  expect(screen.queryByText(/0s left/)).not.toBeInTheDocument();
});
