import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App from "../App";
import { HttpGearClient } from "../api/httpClient";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { relativeTime } from "../components/Timestamp";
import { GearProvider } from "../state/GearProvider";
import {
  draftFieldErrors,
  newDraft,
  normalize,
  parseGp,
} from "../state/scenario";
import context from "./live-context.json";

const performance = {
  supported: true,
  dps: 2.5,
  max_hit: 13,
  accuracy: 0.78,
  attack_interval: 2.4,
  bonuses: { melee_strength: 82 },
  limitations: [],
};
const weaponId = context.items[0].item_id;
const reply = (scenario: unknown) => ({
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
  },
});

type Handler = (init?: RequestInit) => Promise<Response> | Response;
function setup(
  handlers: {
    context?: Handler;
    optimize?: Handler;
    browse?: Handler;
  } = {},
) {
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(url), "http://localhost").pathname;
    if (path.endsWith("/context"))
      return handlers.context
        ? handlers.context(init)
        : new Response(JSON.stringify(context));
    if (path.endsWith("/optimizations"))
      return handlers.optimize
        ? handlers.optimize(init)
        : new Response(JSON.stringify(reply(JSON.parse(String(init?.body)))));
    if (path.endsWith("/items"))
      return handlers.browse
        ? handlers.browse(init)
        : new Response(
            JSON.stringify({
              items: context.items,
              total: 1,
              next_offset: null,
            }),
          );
    return new Response(JSON.stringify(context.items[0]));
  }) as unknown as typeof fetch;
  render(
    <GearProvider client={new HttpGearClient("/ui-api/gear", fetcher)}>
      <App />
    </GearProvider>,
  );
  return fetcher;
}
const ready = () => screen.findByText("Synchronized ranger", { exact: true });
afterEach(() => vi.restoreAllMocks());

it("announces optimization progress in a status region while a run is pending", async () => {
  const user = userEvent.setup();
  setup({ optimize: () => new Promise(() => undefined) });
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  expect(
    await screen.findByRole("status", { name: "Optimization progress" }),
  ).toHaveTextContent("Searching supported configurations");
});

it("removes the progress status once the run is cancelled", async () => {
  const user = userEvent.setup();
  setup({ optimize: () => new Promise(() => undefined) });
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await user.click(screen.getByRole("button", { name: "Cancel optimization" }));
  expect(
    screen.queryByRole("status", { name: "Optimization progress" }),
  ).not.toBeInTheDocument();
});

it("keeps Run available after a refresh fails once account data has loaded", async () => {
  const user = userEvent.setup();
  let refreshFails = false;
  setup({
    context: () =>
      refreshFails
        ? new Response("{}", { status: 503 })
        : new Response(JSON.stringify(context)),
  });
  await ready();
  refreshFails = true;
  await user.click(screen.getByRole("button", { name: "Refresh account" }));
  await screen.findByText("Displayed data may be stale.");
  expect(
    screen.getByRole("button", { name: "Run optimization" }),
  ).toBeEnabled();
});

it("keeps Run disabled when account data never loaded", async () => {
  setup({ context: () => new Response("{}", { status: 503 }) });
  await screen.findByRole("button", { name: "Retry context" });
  expect(
    screen.getByRole("button", { name: "Run optimization" }),
  ).toBeDisabled();
});

async function openInspector(user: ReturnType<typeof userEvent.setup>) {
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  await user.click(screen.getByRole("button", { name: /^weapon / }));
  return screen.findByRole("dialog", { name: "Item inspector" });
}

it("reports loading instead of zero matches, and keeps old results while searching", async () => {
  const user = userEvent.setup();
  let release: (response: Response) => void = () => undefined;
  let calls = 0;
  setup({
    browse: () => {
      calls += 1;
      if (calls === 1)
        return new Response(
          JSON.stringify({
            items: context.items,
            total: 1,
            next_offset: null,
          }),
        );
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    },
  });
  const dialog = within(await openInspector(user));
  await dialog.findByText(/1 matching items/);
  await user.type(dialog.getByLabelText("Search name or numeric ID"), "z");
  await dialog.findByText("Searching items…");
  expect(dialog.queryByText(/^0 matching items/)).not.toBeInTheDocument();
  expect(
    dialog.getAllByRole("button", { name: /^Try / }).length,
  ).toBeGreaterThan(0);
  await waitFor(() => expect(calls).toBe(2));
  release(
    new Response(JSON.stringify({ items: [], total: 0, next_offset: null })),
  );
  await dialog.findByText(/^0 matching items/);
});

it("says when excluded items are hidden from a browse page", async () => {
  const user = userEvent.setup();
  setup();
  const dialog = within(await openInspector(user));
  await dialog.findByText(/1 matching items/);
  await user.click(
    await dialog.findByRole("button", { name: /Exclude item in draft/ }),
  );
  await dialog.findByText(/1 excluded item hidden/);
});

it("shows item names rather than bare IDs in exclusions", async () => {
  const user = userEvent.setup();
  setup();
  const dialog = within(await openInspector(user));
  await user.click(
    await dialog.findByRole("button", { name: /Exclude item in draft/ }),
  );
  await user.click(
    dialog.getByRole("button", { name: "Close Item inspector" }),
  );
  expect(
    screen.getByRole("button", {
      name: `Remove exclusion ${context.items[0].name} (#${weaponId})`,
      hidden: true,
    }),
  ).toBeInTheDocument();
});

it("labels each help toggle after the setting it explains", async () => {
  setup();
  await ready();
  expect(
    screen.getByText("About the equipment support policy"),
  ).toBeInTheDocument();
  expect(screen.getByText("About optimization modes")).toBeInTheDocument();
  expect(screen.queryByText("About this setting")).not.toBeInTheDocument();
});

it("exposes the equipment grid and discipline picker as labelled groups", async () => {
  const user = userEvent.setup();
  setup();
  await ready();
  expect(
    screen.getByRole("group", { name: "Configuration 1 discipline" }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  expect(
    screen.getByRole("group", { name: "equipment slots" }),
  ).toBeInTheDocument();
});

it("uses one product name and no milestone labels in the shell", async () => {
  setup();
  await ready();
  expect(screen.queryByText("RUNIC VAULT")).not.toBeInTheDocument();
  expect(screen.queryByText(/PREVIEW 01/)).not.toBeInTheDocument();
  expect(screen.queryByText(/MILESTONE/)).not.toBeInTheDocument();
});

it("names the handoff actions for what they do and resets copy feedback", async () => {
  const user = userEvent.setup();
  setup();
  await ready();
  await user.click(screen.getByRole("button", { name: "ChatGPT handoff" }));
  const dialog = within(
    await screen.findByRole("dialog", { name: "ChatGPT handoff" }),
  );
  await user.click(dialog.getByRole("button", { name: "Copy handoff text" }));
  await dialog.findByText("Copied handoff text");
  await user.click(
    dialog.getByRole("button", { name: "Close ChatGPT handoff" }),
  );
  await user.click(screen.getByRole("button", { name: "ChatGPT handoff" }));
  const reopened = within(
    await screen.findByRole("dialog", { name: "ChatGPT handoff" }),
  );
  expect(reopened.queryByText("Copied handoff text")).not.toBeInTheDocument();
});

it("explains that editing settings cancelled a run", async () => {
  const user = userEvent.setup();
  let signal: AbortSignal | null | undefined;
  setup({
    optimize: (init) => {
      signal = init?.signal;
      return new Promise(() => undefined);
    },
  });
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await user.type(
    screen.getByLabelText("Additional purchase budget (GP)"),
    "5",
  );
  expect(signal?.aborted).toBe(true);
  expect(
    await screen.findByText(/Run cancelled because settings changed/),
  ).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  expect(
    screen.queryByText(/Run cancelled because settings changed/),
  ).not.toBeInTheDocument();
});

it("locks settings during a Thorough run until it is cancelled", async () => {
  const user = userEvent.setup();
  setup({ optimize: () => new Promise(() => undefined) });
  await ready();
  const budget = screen.getByLabelText("Additional purchase budget (GP)");
  await user.selectOptions(
    screen.getByLabelText("Optimization mode"),
    "thorough",
  );
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  expect(budget).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Cancel optimization" }));
  expect(budget).toBeEnabled();
});

it("shows headline DPS before the grid, with the purchase total", async () => {
  const user = userEvent.setup();
  setup({
    optimize: (init) => {
      const body = reply(JSON.parse(String(init?.body)));
      Object.assign(body.result.selected_solution, {
        purchase_cost_gp: 2500,
        purchases: [
          {
            item_id: weaponId,
            cost_gp: 2500,
            conditional: false,
            slot: "weapon",
          },
        ],
      });
      return new Response(JSON.stringify(body));
    },
  });
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  const metrics = await screen.findByLabelText("Calculated combat performance");
  const grid = screen.getByRole("group", { name: "equipment slots" });
  expect(
    metrics.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.getByText("Buy 1 item · 2,500 GP")).toBeVisible();
  expect(screen.getByRole("button", { name: /^weapon Buy / })).toBeVisible();
  expect(screen.getByText(`${context.items[0].name} · 2,500 GP`)).toBeVisible();
});

it("marks equipment as owned instead of the ambiguous 'selected'", async () => {
  const user = userEvent.setup();
  setup();
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  expect(screen.getByText("No additional purchases")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /^weapon selected/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^head Empty / })).toBeVisible();
});

it("confirms a lock, marks the slot, and offers unlock and re-run in the inspector", async () => {
  const user = userEvent.setup();
  const fetcher = setup();
  const dialog = within(await openInspector(user));
  await user.click(
    await dialog.findByRole("button", {
      name: `Lock weapon to ${context.items[0].name}`,
    }),
  );
  expect(await dialog.findByText("Locked in draft")).toBeVisible();
  expect(
    screen.getByRole("button", { name: /^weapon .*Locked/, hidden: true }),
  ).toBeInTheDocument();
  const optimizations = () =>
    vi
      .mocked(fetcher)
      .mock.calls.filter(([url]) =>
        new URL(String(url), "http://localhost").pathname.endsWith(
          "/optimizations",
        ),
      );
  const before = optimizations().length;
  await user.click(dialog.getByRole("button", { name: "Re-run optimization" }));
  await waitFor(() => expect(optimizations().length).toBe(before + 1));
  const refreshed = within(
    await screen.findByRole("dialog", { name: "Item inspector" }),
  );
  await user.click(
    await refreshed.findByRole("button", { name: "Unlock weapon" }),
  );
  await waitFor(() =>
    expect(refreshed.queryByText("Locked in draft")).not.toBeInTheDocument(),
  );
});

it.each([
  ["10m", "10000000"],
  ["500K", "500000"],
  ["1.5b", "1500000000"],
  ["1,000", "1000"],
  ["12345", "12345"],
  ["1.5", "1.5"],
  ["lots", "lots"],
])("parses the budget %s", (input, expected) => {
  expect(parseGp(input)).toBe(expected);
});

it("submits shorthand budgets as whole GP and shows the readback", async () => {
  const user = userEvent.setup();
  const fetcher = setup();
  await ready();
  const budget = screen.getByLabelText("Additional purchase budget (GP)");
  await user.clear(budget);
  await user.type(budget, "2.5m");
  expect(screen.getByText("2,500,000 GP")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  const call = vi
    .mocked(fetcher)
    .mock.calls.find(([url]) =>
      new URL(String(url), "http://localhost").pathname.endsWith(
        "/optimizations",
      ),
    );
  expect(JSON.parse(String(call?.[1]?.body)).budget_gp).toBe(2500000);
});

it("shows a field error beside an invalid budget and warns about a zero budget", async () => {
  const user = userEvent.setup();
  setup();
  await ready();
  const budget = screen.getByLabelText("Additional purchase budget (GP)");
  expect(screen.getByText(/Budget is 0/)).toBeVisible();
  await user.clear(budget);
  await user.type(budget, "lots");
  expect(budget).toHaveAttribute("aria-invalid", "true");
  expect(budget).toHaveAccessibleDescription(/Budget must be a whole number/);
  expect(
    draftFieldErrors({ ...newDraft(), budget: "1m" }).budget,
  ).toBeUndefined();
});

it("flags settings changed from the sticky action bar", async () => {
  const user = userEvent.setup();
  setup();
  await ready();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  expect(
    screen.queryByText(/^Settings changed since this result/),
  ).not.toBeInTheDocument();
  await user.type(
    screen.getByLabelText("Additional purchase budget (GP)"),
    "5",
  );
  expect(screen.getByText(/^Settings changed since this result/)).toBeVisible();
});

it("scrolls to results after a run only on the stacked layout", async () => {
  const user = userEvent.setup();
  const scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  const matches = (query: string) => query.includes("max-width");
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) => ({ matches: matches(query) }) as MediaQueryList,
  );
  setup();
  await ready();
  expect(scrollIntoView).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  expect(scrollIntoView).toHaveBeenCalledOnce();
});

it("closes the side-panel inspector with Escape when focus is outside it", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({ matches: query.includes("min-width: 1280px") }) as MediaQueryList,
  );
  setup();
  await openInspector(user);
  screen.getByRole("heading", { name: /Best configuration found/ });
  (document.activeElement as HTMLElement | null)?.blur();
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "Item inspector" }),
    ).not.toBeInTheDocument(),
  );
});

it("finds items by name for a multi-style lock", async () => {
  const user = userEvent.setup();
  location.hash = "multi";
  setup();
  await ready();
  await user.click(screen.getByText("Equipment locks & exclusions"));
  await user.type(screen.getByLabelText("Find item to lock"), "whip");
  await user.click(
    await screen.findByRole("button", {
      name: `${context.items[0].name} (#${weaponId})`,
    }),
  );
  expect(screen.getByLabelText("Physical item ID or empty")).toHaveValue(
    String(weaponId),
  );
});

it("formats timestamps relative to now", () => {
  const now = Date.parse("2026-11-01T12:00:00Z");
  expect(relativeTime("2026-11-01T11:59:50Z", now)).toBe("just now");
  expect(relativeTime("2026-11-01T11:30:00Z", now)).toBe("30 minutes ago");
  expect(relativeTime("2026-10-30T12:00:00Z", now)).toBe("2 days ago");
  expect(relativeTime("not a date", now)).toBeNull();
});

it("removes controls that could never do anything", async () => {
  setup();
  await ready();
  expect(screen.queryByText(/Survivability/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Ban degradables/)).not.toBeInTheDocument();
  expect(screen.queryByText(/RuneLite tag export/)).not.toBeInTheDocument();
});

it("rejects a magic stance the backend does not accept", () => {
  const draft = newDraft();
  draft.roles[0] = { ...draft.roles[0], style: "magic", stance: "longrange" };
  expect(() => normalize(draft, context.account.snapshot_id)).toThrow(
    /stance is unsupported/,
  );
});

it("replaces a crashed view with a recovery message", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const Boom = () => {
    throw new Error("bad payload");
  };
  render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Something went wrong showing this view",
  );
  expect(screen.getByRole("button", { name: "Reload page" })).toBeEnabled();
});
