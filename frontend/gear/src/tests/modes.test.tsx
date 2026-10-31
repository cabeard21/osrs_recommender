import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import {
  newDraft,
  normalize,
  readDrafts,
  storageKey,
  initialState,
  reducer,
} from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import {
  matchesOptimizationPolicy,
  validateOptimizationPolicy,
  validateRefinementDiagnostics,
  workBudgetPolicy,
} from "../api/optimizationModes";
import { FixtureGearClient } from "../fixtures/client";
import { OptimizationModeSummary } from "../components/OptimizationModeSummary";
import type { JointSolutionDTO, OptimizationDTO } from "../api/contracts";

it("defaults historical drafts to Fast and submits explicit mode identity", () => {
  const draft = newDraft();
  expect(optimizationRequest(normalize(draft, "account"))).toHaveProperty(
    "optimization_mode",
    "fast",
  );
  expect(
    optimizationRequest(
      normalize({ ...draft, optimizationMode: "thorough" }, "account"),
    ),
  ).toHaveProperty("optimization_mode", "thorough");
  const old = { ...draft };
  delete old.optimizationMode;
  sessionStorage.setItem(
    storageKey("old"),
    JSON.stringify({ version: 2, single: old, multi: old }),
  );
  expect(readDrafts("old", sessionStorage)?.single.optimizationMode).toBe(
    "fast",
  );
});

it("rejects mislabeled modes and changed effective work budgets", () => {
  const thorough = {
    optimization_mode: "thorough",
    work_budget_policy: workBudgetPolicy("thorough"),
  };
  expect(() =>
    validateOptimizationPolicy(thorough, thorough, "thorough"),
  ).not.toThrow();
  expect(() => validateOptimizationPolicy({}, {}, "thorough")).toThrow(/mode/);
  expect(() => validateOptimizationPolicy(thorough, thorough, "fast")).toThrow(
    /mode/,
  );
  expect(() =>
    validateOptimizationPolicy(
      { ...thorough, work_budget_policy: workBudgetPolicy("fast") },
      thorough,
      "thorough",
    ),
  ).toThrow(/budget/);
  expect(() =>
    normalize(
      { ...newDraft(), optimizationMode: "unknown" as "fast" },
      "account",
    ),
  ).toThrow(/Fast or Thorough/);
});

it("validates preserved baseline metrics and bounded work before presenting diagnostics", () => {
  const before = {
    score: 2,
    purchase_cost_gp: 0,
    maximum_actions: 0,
    max_gear_inventory_slots: 0,
  };
  const diagnostic = {
    triggered: true,
    assignment_attempts: 10,
    work_budget_exhausted: false,
    objective_improvements: 1,
    tie_improvements: 0,
    baseline: { curve_solutions: [before], unrestricted: before },
  };
  expect(() => validateRefinementDiagnostics(diagnostic, 0)).not.toThrow();
  for (const patch of [
    { assignment_attempts: 2001 },
    { tie_improvements: -1 },
    { baseline: {} },
    {
      baseline: {
        curve_solutions: [{ ...before, score: NaN }],
        unrestricted: null,
      },
    },
  ])
    expect(() =>
      validateRefinementDiagnostics({ ...diagnostic, ...patch }, 0),
    ).toThrow();
});

it("reports objective gains separately from equal-DPS tie replacements and cap exhaustion", async () => {
  const client = new FixtureGearClient("none", 0);
  const result = await client.optimize(
    normalize(
      { ...newDraft(), optimizationMode: "thorough" },
      "fixture-snapshot-01",
    ),
    new AbortController().signal,
  );
  const baseline = {
    score: 2,
    purchase_cost_gp: 100,
    maximum_actions: 1,
    max_gear_inventory_slots: 2,
  } as JointSolutionDTO;
  const solution = {
    ...baseline,
    purchase_cost_gp: 150,
    maximum_actions: 2,
    max_gear_inventory_slots: 3,
  };
  const liveResult = {
    ...result,
    source: "live" as const,
    live: {
      result: {
        search: {
          local_refinement: {
            triggered: true,
            assignment_attempts: 2000,
            work_budget_exhausted: true,
            tie_improvements: 4,
            baseline: { curve_solutions: Array(9).fill(baseline) },
          },
        },
      },
    } as unknown as OptimizationDTO,
  };
  const view = render(
    <OptimizationModeSummary result={liveResult} solution={solution} />,
  );
  screen.getByText("Search details").click();
  expect(screen.getByText(/2000 extra complete assignments/)).toBeVisible();
  expect(screen.getByText(/cap reached; best valid/)).toBeVisible();
  expect(screen.getByText(/No weighted-DPS improvement/)).toHaveTextContent(
    "Equal-DPS tie changes: 4",
  );
  expect(screen.getByText(/Additional acquisition GP/)).toHaveTextContent(
    "+50 GP · maximum actions: +1 · peak gear inventory: +1",
  );
  expect(
    matchesOptimizationPolicy(result, {
      ...result,
      scenario: normalize(newDraft(), "fixture-snapshot-01"),
    }),
  ).toBe(false);
  view.rerender(
    <OptimizationModeSummary
      result={liveResult}
      solution={{ ...solution, score: 2.25 }}
    />,
  );
  expect(screen.getByText(/Selected weighted DPS change/)).toHaveTextContent(
    "+0.250000",
  );
  expect(
    screen.queryByText(/No weighted-DPS improvement/),
  ).not.toBeInTheDocument();
  view.rerender(
    <OptimizationModeSummary
      result={liveResult}
      solution={{ ...solution, score: 1.9 }}
    />,
  );
  expect(screen.getByText(/Selected weighted DPS change/)).toHaveTextContent(
    "-0.100000",
  );
  const noWork = {
    ...liveResult,
    live: {
      ...liveResult.live,
      result: {
        ...liveResult.live.result,
        search: {
          local_refinement: {
            triggered: true,
            assignment_attempts: 0,
            work_budget_exhausted: false,
          },
        },
      },
    },
  };
  view.rerender(<OptimizationModeSummary result={noWork} />);
  expect(
    screen.getByText(/No additional complete assignments required/),
  ).toBeVisible();
});

it("rejects a late Fast result for a Thorough generation", async () => {
  const client = new FixtureGearClient("none", 0);
  const fast = await client.optimize(
    normalize(newDraft(), "fixture-snapshot-01"),
    new AbortController().signal,
  );
  const scenario = normalize(
    { ...newDraft(), optimizationMode: "thorough" },
    "fixture-snapshot-01",
  );
  const started = reducer(initialState(), {
    type: "start",
    mode: "single",
    scenario,
    generation: 1,
  });
  const rejected = reducer(started, {
    type: "success",
    mode: "single",
    generation: 1,
    result: fast,
  });
  expect(rejected.single.result).toBeNull();
  expect(rejected.single.pending).toBe(false);
  expect(rejected.single.error).toMatch(/mode changed/);
});

it("retains the selected mode and preserves an outdated accepted fixture result", async () => {
  const user = userEvent.setup();
  render(
    <GearProvider>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Demo adventurer", { exact: true });
  expect(screen.getByLabelText("Optimization mode")).toHaveValue("fast");
  await user.click(
    screen.getByRole("button", { name: "Run fixture optimization" }),
  );
  await screen.findByText("Fixture result", { exact: true });
  await user.selectOptions(
    screen.getByLabelText("Optimization mode"),
    "thorough",
  );
  expect(screen.getByText(/Result outdated/)).toBeVisible();
  expect(screen.getByText("Fixture result", { exact: true })).toBeVisible();
  expect(screen.getByLabelText("Optimization mode")).toHaveValue("thorough");
});
