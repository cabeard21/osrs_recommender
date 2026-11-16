import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../App";
import { HttpGearClient } from "../api/httpClient";
import { formatInterval } from "../components/resultFormat";
import { budgetToSlider, sliderToBudget } from "../state/budget";
import { describeDraftChanges } from "../state/draftChanges";
import { GearProvider } from "../state/GearProvider";
import { readResults, saveResults } from "../state/resultStorage";
import type { SavedResult } from "../state/resultStorage";
import { initialState, newDraft, reducer } from "../state/scenario";
import context from "./live-context.json";
import { dpsObjectiveResponse } from "./dps-objective-response";

const performance = {
  supported: true,
  dps: 3.27,
  max_hit: 16,
  accuracy: 0.974,
  attack_interval: 1.7999999999999998,
  bonuses: { melee_strength: 58 },
  limitations: [],
};
const weaponId = context.items[0].item_id;
const availableBaseline = {
  status: "available",
  equipment: {},
  performance: { ...performance, dps: 2.84, attack_interval: 2.4 },
  reasons: [],
};
const reply = (
  scenario: unknown,
  overrides: Record<string, unknown> = {},
  resultOverrides: Record<string, unknown> = {},
) =>
  dpsObjectiveResponse({
    api_version: "gear-ui-v1",
    evaluated_at: context.evaluated_at,
    scenario,
    scenario_fingerprint: "scenario-1",
    price_revision: context.price_revision,
    items: context.items,
    baseline: {
      status: "unavailable",
      equipment: {},
      performance: null,
      reasons: ["No scan"],
    },
    result: {
      snapshot_id: context.account.snapshot_id,
      catalog_version: context.catalog_version,
      model_version: context.model_version,
      assumptions_fingerprint: "assumptions",
      search: {
        quality: "best_found",
        candidate_truncation: false,
        termination_reason: "bounded_search_complete",
      },
      limitations: [],
      selected_solution: {
        score: performance.dps,
        loadouts: {
          "role-1": { equipment: { weapon: weaponId }, performance },
        },
        purchases: [],
        purchase_cost_gp: 0,
      },
      ...resultOverrides,
    },
    ...overrides,
  });

type Reply = (scenario: unknown) => unknown;
function fetcherFor(makeReply: Reply = reply, ctx: unknown = context) {
  return vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(url), "http://localhost").pathname;
    if (path.endsWith("/context")) return new Response(JSON.stringify(ctx));
    if (path.endsWith("/optimizations"))
      return new Response(
        JSON.stringify(makeReply(JSON.parse(String(init?.body)))),
      );
    if (path.endsWith("/items"))
      return new Response(
        JSON.stringify({ items: context.items, total: 1, next_offset: null }),
      );
    if (path.includes("/targets"))
      return new Response(
        JSON.stringify({ items: [], total: 0, next_offset: null }),
      );
    return new Response(JSON.stringify(context.items[0]));
  }) as unknown as typeof fetch;
}
function mount(fetcher: typeof fetch) {
  render(
    <GearProvider client={new HttpGearClient("/ui-api/gear", fetcher)}>
      <App />
    </GearProvider>,
  );
}
const optimizeCalls = (fetcher: typeof fetch) =>
  vi
    .mocked(fetcher)
    .mock.calls.filter(([url]) =>
      new URL(String(url), "http://localhost").pathname.endsWith(
        "/optimizations",
      ),
    );
const ready = () => screen.findByText("Synchronized ranger", { exact: true });
const runAndWait = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  return screen.findByRole("heading", { name: /Best configuration found/ });
};
const budgetField = () =>
  screen.getByLabelText("Additional purchase budget (GP)");

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

it("formats intervals as ticks without floating point noise", () => {
  expect(formatInterval(1.7999999999999998)).toBe("3 ticks (1.8s)");
  expect(formatInterval(0.6)).toBe("1 tick (0.6s)");
});

it("hides the discipline comparison when a manual run returns no rows", async () => {
  const user = userEvent.setup();
  mount(
    fetcherFor((scenario) =>
      reply(scenario, {}, { discipline_comparison: [] }),
    ),
  );
  await ready();
  await runAndWait(user);
  expect(
    screen.queryByRole("region", { name: "Combat discipline comparison" }),
  ).not.toBeInTheDocument();
});

it("headlines the DPS gain over current gear", async () => {
  const user = userEvent.setup();
  mount(
    fetcherFor((scenario) => reply(scenario, { baseline: availableBaseline })),
  );
  await ready();
  await runAndWait(user);
  expect(screen.getByText("3.27 DPS")).toBeVisible();
  expect(screen.getByText("+0.43 (+15.1%) vs current gear")).toBeVisible();
  expect(
    screen.getByRole("button", { name: /^weapon .*Changed/ }),
  ).toBeVisible();
});

it("explains why the comparison with current gear is missing", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await runAndWait(user);
  expect(
    screen.getByText("Comparison with current gear unavailable: No scan"),
  ).toBeVisible();
});

it("shows the loadout before the scenario details", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  const heading = await runAndWait(user);
  const used = screen.getByText("This result used");
  expect(
    heading.compareDocumentPosition(used) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("focuses the invalid field and offers no retry for a validation error", async () => {
  const user = userEvent.setup();
  const fetcher = fetcherFor();
  mount(fetcher);
  await ready();
  await user.clear(budgetField());
  await user.type(budgetField(), "abc");
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/Budget must/);
  expect(
    screen.queryByRole("button", { name: "Retry optimization" }),
  ).not.toBeInTheDocument();
  expect(budgetField()).toHaveFocus();
  expect(optimizeCalls(fetcher)).toHaveLength(0);
});

it("flags zero allowed disciplines inline before submitting", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await user.click(screen.getByRole("button", { name: "Auto" }));
  const allowed = within(
    screen.getByRole("group", { name: "Allowed combat disciplines" }),
  );
  for (const name of ["melee", "ranged", "magic"])
    await user.click(allowed.getByRole("checkbox", { name }));
  expect(
    screen.getByText("Choose at least one combat discipline."),
  ).toBeVisible();
});

it("blames the missing sync, not filters, when an unsynced run finds nothing", async () => {
  const user = userEvent.setup();
  const unsynced = {
    ...context,
    account: { ...context.account, last_sync_at: null },
  };
  mount(
    fetcherFor(
      (scenario) => reply(scenario, {}, { selected_solution: null }),
      unsynced,
    ),
  );
  await screen.findByRole("heading", { name: "No synchronized account" });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  expect(
    await screen.findByText(/No account data has been synced/),
  ).toBeVisible();
});

it("runs on Enter only in numeric settings, not search or name fields", async () => {
  const user = userEvent.setup();
  const fetcher = fetcherFor();
  mount(fetcher);
  await ready();
  await user.type(screen.getByLabelText("Search NPCs"), "abyssal{Enter}");
  await user.type(screen.getByLabelText("Custom target"), "x{Enter}");
  expect(optimizeCalls(fetcher)).toHaveLength(0);
  await user.type(budgetField(), "{Enter}");
  await screen.findByRole("heading", { name: /Best configuration found/ });
  expect(optimizeCalls(fetcher)).toHaveLength(1);
});

it("restores the last result after a reload", async () => {
  const user = userEvent.setup();
  const fetcher = fetcherFor();
  mount(fetcher);
  await ready();
  await runAndWait(user);
  cleanup();
  mount(fetcherFor());
  expect(
    await screen.findByRole("heading", { name: /Best configuration found/ }),
  ).toBeVisible();
});

it("does not restore a result from a different account snapshot", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await runAndWait(user);
  cleanup();
  const resynced = {
    ...context,
    account: { ...context.account, snapshot_id: "a-newer-snapshot" },
  };
  mount(fetcherFor(reply, resynced));
  await ready();
  expect(
    await screen.findByRole("heading", {
      name: "Find your best configuration",
    }),
  ).toBeVisible();
});

it("ignores saved results missing the fields the reducer reads", () => {
  sessionStorage.setItem(
    "gear-results:p:single",
    JSON.stringify({
      result: { solutions: [], live: {} },
      solutionId: "best-found",
      outdated: false,
    }),
  );
  expect(readResults("p", sessionStorage)).toEqual({});
});

it("keeps one mode's saved result when the other exceeds the storage quota", () => {
  const saved = {
    result: {
      solutions: [],
      live: {},
      scenario: { request: { roles: [{ id: "role-1" }] } },
    },
    solutionId: "best-found",
    outdated: false,
  } as unknown as SavedResult;
  const setItem = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key: string,
    value: string,
  ) {
    if (key.endsWith(":multi")) throw new DOMException("full");
    setItem.call(this, key, value);
  });
  saveResults("p", { single: saved, multi: saved }, sessionStorage);
  expect(Object.keys(readResults("p", sessionStorage))).toEqual(["single"]);
});

it("clears the validation flag so later run errors can offer a retry", () => {
  const failed = reducer(initialState(), {
    type: "error",
    mode: "single",
    generation: 0,
    error: "Budget must be a whole number",
    validation: true,
  });
  expect(failed.single.errorIsValidation).toBe(true);
  const edited = reducer(failed, {
    type: "edit",
    mode: "single",
    draft: failed.single.draft,
  });
  expect(edited.single.errorIsValidation).toBe(false);
});

it("says current gear is measured at its configured attack style", async () => {
  const user = userEvent.setup();
  mount(
    fetcherFor((scenario) => reply(scenario, { baseline: availableBaseline })),
  );
  await ready();
  await runAndWait(user);
  expect(
    screen.getByText(/Current gear uses your configured attack style/),
  ).toBeVisible();
});

it("maps the budget slider logarithmically across the whole GP range", () => {
  expect(sliderToBudget(0)).toBe(0);
  expect(sliderToBudget(100)).toBe(2147483647);
  expect(budgetToSlider(0)).toBe(0);
  expect(budgetToSlider(2147483647)).toBe(100);
  expect(budgetToSlider(500_000_000)).toBeLessThan(100);
  expect(budgetToSlider(sliderToBudget(50))).toBe(50);
});

it("fills the budget from a preset", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await user.click(screen.getByRole("button", { name: "100m" }));
  expect(budgetField()).toHaveValue("100m");
});

it("only emphasizes Reoptimize when the result is outdated", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await runAndWait(user);
  const button = screen.getByRole("button", { name: "Reoptimize" });
  expect(button).not.toHaveClass("primary");
  await user.clear(budgetField());
  await user.type(budgetField(), "5m");
  expect(screen.getByRole("button", { name: "Reoptimize" })).toHaveClass(
    "primary",
  );
  expect(
    screen.getByText(/Settings changed since this result: Budget/),
  ).toBeVisible();
});

it("describes what changed between the draft and the submitted request", () => {
  const draft = { ...newDraft(), budget: "5m", defence: "120" };
  const changes = describeDraftChanges(draft, {
    budget_gp: 10_000_000,
    mode: draft.mode,
    optimization_mode: "fast",
    target: { name: draft.target, defence: 1 },
    roles: [{}],
  });
  expect(changes).toEqual([
    "Budget: 10,000,000 → 5,000,000 GP",
    "Target defence: 1 → 120",
  ]);
});

it("marks the current page and names the legacy view in navigation", async () => {
  mount(fetcherFor());
  await ready();
  const nav = screen.getByRole("navigation", { name: "Workspace navigation" });
  expect(
    within(nav).getByRole("link", { name: "Gear optimizer" }),
  ).toHaveAttribute("aria-current", "page");
  expect(
    within(nav).getByRole("link", { name: "Legacy gear view" }),
  ).toHaveAttribute("href", "/gear-legacy");
});

it("offers inspector actions before item bonuses, using item names", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await runAndWait(user);
  await user.click(screen.getByRole("button", { name: /^weapon / }));
  const dialog = await screen.findByRole("dialog", { name: "Item inspector" });
  const lock = await within(dialog).findByRole("button", {
    name: `Lock weapon to ${context.items[0].name}`,
  });
  const bonuses = within(dialog).getByText("Item bonuses", {
    selector: "summary",
  });
  expect(
    lock.compareDocumentPosition(bonuses) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    within(dialog).getByRole("region", { name: "Candidate comparison" }),
  ).not.toHaveTextContent("→");
});

it("leads target selection with search and warns about the default target", async () => {
  mount(fetcherFor());
  await ready();
  expect(screen.getByText("Use custom target stats")).toBeVisible();
  expect(
    screen.getByLabelText("Target defence").closest("details"),
  ).not.toHaveAttribute("open");
  expect(screen.getByText(/No NPC selected/)).toBeVisible();
});

it("explains why a configuration cannot be removed in multi-style", async () => {
  const user = userEvent.setup();
  mount(fetcherFor());
  await ready();
  await user.click(screen.getByRole("button", { name: "Multi-style" }));
  const removes = screen.getAllByRole("button", {
    name: "Remove configuration",
  });
  expect(removes[0]).toBeDisabled();
  expect(
    screen.getAllByText("At least two configurations are required.")[0],
  ).toBeVisible();
});
