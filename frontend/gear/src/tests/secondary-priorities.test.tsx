import { readSavedSetups } from "../state/savedSetups";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import {
  newDraft,
  newRole,
  normalize,
  initialState,
  reducer,
  readDrafts,
  storageKey,
} from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import {
  secondaryPriorities,
  validateSecondaryPriority,
} from "../api/secondaryPriorities";
import { FixtureGearClient, contextFixture } from "../fixtures/client";
import { SecondaryPrioritySummary } from "../components/SecondaryPrioritySummary";
import type { JointSolutionDTO } from "../api/contracts";
import { matchesSecondaryPriority } from "../api/secondaryPriorities";

it.each([1, 2, 3, 4])(
  "retains every priority in %i-role scenario/request identity",
  (count) => {
    for (const [priority] of secondaryPriorities) {
      const draft = {
        ...newDraft(),
        secondaryPriority: priority,
        roles: Array.from({ length: count }, (_, i) => newRole(i + 1)),
      };
      expect(optimizationRequest(normalize(draft, "snapshot"))).toHaveProperty(
        "secondary_priority",
        priority,
      );
    }
  },
);
it("migrates historical drafts and rejects unknown priority values", () => {
  const old = { ...newDraft() };
  delete old.secondaryPriority;
  sessionStorage.setItem(
    storageKey("old-priority"),
    JSON.stringify({ version: 2, single: old, multi: old }),
  );
  expect(
    readDrafts("old-priority", sessionStorage)?.single.secondaryPriority,
  ).toBe("default");
  expect(() =>
    normalize(
      { ...newDraft(), secondaryPriority: "unknown" as "default" },
      "snapshot",
    ),
  ).toThrow(/metric/);
});
it("rejects changed priority provenance and missing or invalid measurements", () => {
  expect(() => validateSecondaryPriority({}, "default", true)).not.toThrow();
  expect(() => validateSecondaryPriority({}, "accuracy", true)).toThrow(
    /metric/,
  );
  expect(() =>
    validateSecondaryPriority(
      { secondary_priority: "accuracy", secondary_value: 0.75 },
      "accuracy",
      true,
    ),
  ).not.toThrow();
  for (const secondary_value of [undefined, null, NaN, Infinity, "0.75"])
    expect(() =>
      validateSecondaryPriority(
        { secondary_priority: "accuracy", secondary_value },
        "accuracy",
        true,
      ),
    ).toThrow(/value/);
});
it("rejects a result from a different tradeoff metric", async () => {
  const client = new FixtureGearClient("none", 0);
  const result = await client.optimize(
    normalize(newDraft(), "fixture-snapshot-01"),
    new AbortController().signal,
  );
  const scenario = normalize(
    { ...newDraft(), secondaryPriority: "accuracy" },
    "fixture-snapshot-01",
  );
  const state = reducer(initialState(), {
    type: "start",
    mode: "single",
    scenario,
    generation: 1,
  });
  const rejected = reducer(state, {
    type: "success",
    mode: "single",
    result,
    generation: 1,
  });
  expect(rejected.single.result).toBeNull();
  expect(rejected.single.error).toMatch(/metric changed/);
  expect(matchesSecondaryPriority(result, { ...result, scenario })).toBe(false);
});
it("shows a measured secondary value separately from primary DPS", async () => {
  const result = await new FixtureGearClient("none", 0).optimize(
    normalize(
      { ...newDraft(), secondaryPriority: "accuracy" },
      "fixture-snapshot-01",
    ),
    new AbortController().signal,
  );
  render(
    <SecondaryPrioritySummary
      result={{ ...result, source: "live" }}
      solution={
        {
          secondary_priority: "accuracy",
          secondary_value: 0.75,
        } as JointSolutionDTO
      }
    />,
  );
  expect(screen.getByText(/Tradeoff metric: Accuracy/)).toHaveTextContent(
    "75.00%",
  );
  screen.getByText("Tradeoff metric", { exact: true }).click();
  expect(
    screen.getByText(
      /frontier explores DPS and the selected metric as equal objectives/,
    ),
  ).toBeVisible();
});
it("switches priorities while keeping accepted results outdated", async () => {
  const user = userEvent.setup();
  render(
    <GearProvider>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Demo adventurer", { exact: true });
  expect(screen.getByLabelText("Tradeoff metric")).toHaveValue("default");
  expect(
    screen.getByLabelText("Tradeoff metric").querySelectorAll("option"),
  ).toHaveLength(16);
  await user.click(
    screen.getByRole("button", { name: "Run fixture optimization" }),
  );
  await screen.findByText("Fixture result", { exact: true });
  await user.selectOptions(
    screen.getByLabelText("Tradeoff metric"),
    "prayer_bonus",
  );
  expect(screen.getByText(/Result outdated/)).toBeVisible();
});

it("retains the combined defence priority through saved drafts and requests", () => {
  const draft = {
    ...newDraft(),
    secondaryPriority: "magic_ranged_defence" as const,
  };
  sessionStorage.setItem(
    storageKey("combined-defence"),
    JSON.stringify({ version: 2, single: draft, multi: draft }),
  );
  const restored = readDrafts("combined-defence", sessionStorage)!;
  expect(restored.single.secondaryPriority).toBe("magic_ranged_defence_roll");
  expect(
    optimizationRequest(normalize(restored.single, "snapshot"))
      .secondary_priority,
  ).toBe("magic_ranged_defence_roll");
});

it("explains the combined score and selected bonuses in the result summary", async () => {
  const result = await new FixtureGearClient("none", 0).optimize(
    normalize(
      { ...newDraft(), secondaryPriority: "magic_ranged_defence_roll" },
      "fixture-snapshot-01",
    ),
    new AbortController().signal,
  );
  const solution = {
    secondary_value: -5,
    loadouts: {
      single: {
        performance: { bonuses: { defence_magic: -5, defence_ranged: 20 } },
      },
    },
  } as unknown as JointSolutionDTO;
  render(
    <SecondaryPrioritySummary
      result={{
        ...result,
        source: "live",
        scenario: {
          ...result.scenario,
          request: {
            ...result.scenario.request,
            secondary_priority: "magic_ranged_defence",
          },
        },
      }}
      solution={solution}
    />,
  );
  screen.getByText("Tradeoff metric", { exact: true }).click();
  expect(
    screen.getByText(/Tradeoff metric: Magic & ranged defence/),
  ).toHaveTextContent("-5.00 bonus");
  expect(
    screen.getByText(/lower of the magic and ranged equipment defence bonuses/),
  ).toBeVisible();
  expect(
    screen.getByText(/single defence bonuses: magic -5 \/ ranged 20/),
  ).toBeVisible();
});

it.each([
  "balanced_defence",
  "magic_ranged_defence",
  "stab_defence",
  "slash_defence",
  "crush_defence",
  "ranged_defence",
  "magic_defence",
] as const)(
  "migrates %s in Single/Multi drafts and named setups",
  (priority) => {
    const original = {
      ...newDraft(),
      secondaryPriority: priority,
      budget: "12345",
    };
    sessionStorage.setItem(
      storageKey("migration"),
      JSON.stringify({ version: 3, single: original, multi: original }),
    );
    const loaded = readDrafts("migration", sessionStorage)!;
    for (const draft of [loaded.single, loaded.multi]) {
      expect(draft.secondaryPriority).toBe(`${priority}_roll`);
      expect(draft.budget).toBe("12345");
      expect(
        optimizationRequest(normalize(draft, "snapshot")).secondary_priority,
      ).toBe(`${priority}_roll`);
    }
    sessionStorage.setItem(
      "gear.savedSetups.v1",
      JSON.stringify([
        {
          name: "Legacy",
          mode: "single",
          savedAt: "2026-11-15",
          draft: original,
        },
      ]),
    );
    expect(readSavedSetups(sessionStorage)[0].draft).toMatchObject({
      secondaryPriority: `${priority}_roll`,
      budget: "12345",
    });
    expect(original.secondaryPriority).toBe(priority);
  },
);

it("restores a legacy result as outdated after draft migration without changing its metric", async () => {
  const result = await new FixtureGearClient("none", 0).optimize(
    normalize(newDraft(), "fixture-snapshot-01"),
    new AbortController().signal,
  );
  const historical = {
    ...result,
    scenario: {
      ...result.scenario,
      request: {
        ...result.scenario.request,
        secondary_priority: "stab_defence" as const,
      },
    },
  };
  const state = { ...initialState(), context: contextFixture };
  state.single.draft = {
    ...state.single.draft,
    secondaryPriority: "stab_defence_roll",
  };
  const restored = reducer(state, {
    type: "restore-results",
    results: {
      single: { result: historical, solutionId: "saved", outdated: false },
    },
  });
  expect(restored.single.outdated).toBe(true);
  expect(restored.single.result?.scenario.request.secondary_priority).toBe(
    "stab_defence",
  );
});
