import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import App from "../App";
import {
  HttpGearClient,
  optimizationRequest,
  parseOptimization,
} from "../api/httpClient";
import { GearProvider } from "../state/GearProvider";
import { newDraft, normalize } from "../state/scenario";
import context from "./live-context.json";

// Transport contract examples only. Combat parity is verified by Python tests.
const performance = {
  supported: true,
  dps: 2.3456789,
  max_hit: 13,
  accuracy: 0.78,
  attack_interval: 2.4,
  bonuses: { melee_strength: 82 },
  limitations: [],
};
const response = () => ({
  api_version: "gear-ui-v1",
  evaluated_at: context.evaluated_at,
  scenario: optimizationRequest(
    normalize(newDraft(), context.account.snapshot_id),
  ),
  scenario_fingerprint: "scenario-1",
  price_revision: context.price_revision,
  items: context.items,
  baseline: {
    status: "available",
    equipment: { weapon: 4151 },
    performance,
    reasons: [],
  },
  result: {
    snapshot_id: context.account.snapshot_id,
    catalog_version: context.catalog_version,
    model_version: context.model_version,
    assumptions_fingerprint: "assumptions",
    search: {
      quality: "best_found",
      candidate_truncation: true,
      termination_reason: "bounded_search_complete",
    },
    limitations: ["Ordinary attacks only"],
    selected_solution: {
      score: performance.dps,
      loadouts: { "role-1": { equipment: { weapon: 4151 }, performance } },
      purchases: [],
      purchase_cost_gp: 0,
    },
  },
});
it("validates single-role secondary priority provenance and measurements", () => {
  const scenario = normalize(
    { ...newDraft(), secondaryPriority: "accuracy" },
    context.account.snapshot_id,
  );
  const reply = response();
  reply.scenario = optimizationRequest(scenario);
  Object.assign(reply, { secondary_priority: "accuracy" });
  Object.assign(reply.result, { secondary_priority: "accuracy" });
  Object.assign(reply.result.selected_solution, {
    secondary_priority: "accuracy",
    secondary_value: 0.78,
  });
  expect(parseOptimization(reply, scenario).solutions[0].weightedDps).toBe(
    performance.dps,
  );
  for (const row of [reply, reply.result, reply.result.selected_solution]) {
    Object.assign(row, { secondary_priority: "default" });
    expect(() => parseOptimization(reply, scenario)).toThrow(/priority/);
    Object.assign(row, { secondary_priority: "accuracy" });
  }
  Object.assign(reply.result.selected_solution, { secondary_value: null });
  expect(() => parseOptimization(reply, scenario)).toThrow(/value/);
});
function setup(
  reply = response(),
  optimize?: (init?: RequestInit) => Promise<Response>,
) {
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/context"))
      return new Response(JSON.stringify(context));
    if (String(url).endsWith("/optimizations"))
      return optimize
        ? optimize(init)
        : new Response(
            JSON.stringify({
              ...reply,
              scenario: JSON.parse(String(init?.body)),
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
it("submits a single domain role with physical locks and exact budget, without fixture-only fields", async () => {
  const fetcher = vi.fn(
    async (_url, init) =>
      new Response(
        JSON.stringify({
          ...response(),
          scenario: JSON.parse(String(init?.body)),
        }),
      ),
  ) as unknown as typeof fetch;
  const d = newDraft();
  d.budget = "12345";
  d.roles[0].locks = { ammo: null, weapon: 4151 };
  const result = await new HttpGearClient("/ui-api/gear", fetcher).optimize(
    normalize(d, context.account.snapshot_id),
    new AbortController().signal,
  );
  const [, init] = vi.mocked(fetcher).mock.calls[0];
  const body = JSON.parse(String(init?.body));
  expect(body.roles[0]).toMatchObject({
    style: "slash",
    stance: "accurate",
    locks: { ammunition: null, weapon: 4151 },
    target: { defence_level: 1 },
  });
  expect(body.roles[0]).not.toHaveProperty("name");
  expect(body).not.toHaveProperty("excluded_item_ids");
  expect(body.budget_gp).toBe(12345);
  expect(result.solutions[0].loadouts[0].metrics).toMatchObject({
    dps: performance.dps,
    seconds: 2.4,
  });
  expect(result.source).toBe("live");
});
it("renders actual results, baseline and immutable scenarios, then preserves a compatible previous result", async () => {
  const user = userEvent.setup();
  setup();
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  expect(
    screen.getByLabelText("Calculated combat performance"),
  ).toHaveTextContent("2.35");
  expect(
    screen.getByLabelText("Calculated combat performance"),
  ).toHaveTextContent("2.4 seconds");
  expect(
    screen.getByRole("heading", { name: "Current equipment comparison" }),
  ).toBeVisible();
  expect(screen.getByText(/Candidate pruning truncated/)).toBeVisible();
  await user.clear(screen.getByLabelText("Additional purchase budget (GP)"));
  await user.type(
    screen.getByLabelText("Additional purchase budget (GP)"),
    "100",
  );
  expect(screen.getByText(/Result outdated/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Reoptimize" }));
  await screen.findByRole("heading", {
    name: "Previous configuration comparison",
  });
  expect(
    screen.queryByText(/Authored fixture numbers/),
  ).not.toBeInTheDocument();
});
it("shows indeterminate progress and cancels the transport without accepting a late response", async () => {
  const user = userEvent.setup();
  let finish!: (r: Response) => void;
  let signal: AbortSignal | null | undefined;
  setup(response(), (init) => {
    signal = init?.signal;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  expect(screen.getByRole("button", { name: "Optimizing…" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Cancel optimization" }));
  expect(signal?.aborted).toBe(true);
  finish(new Response(JSON.stringify(response())));
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: /Best configuration found/ }),
    ).not.toBeInTheDocument(),
  );
});
it("shows no solution and unavailable baseline reasons without inventing metrics", async () => {
  const user = userEvent.setup();
  const reply = response();
  Object.assign(reply.result, { selected_solution: null });
  Object.assign(reply.baseline, {
    status: "unavailable",
    performance: null,
    reasons: ["No equipment scan"],
  });
  setup(reply);
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /No feasible solution/ });
  expect(screen.getByText("No equipment scan")).toBeVisible();
  expect(
    screen.queryByLabelText("Calculated combat performance"),
  ).not.toBeInTheDocument();
});
it("preserves structured field errors and never switches to fixtures", async () => {
  const user = userEvent.setup();
  setup(
    response(),
    async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "invalid_request",
            message: "Scenario invalid",
            fields: [
              { field: "budget_gp", message: "Budget must be nonnegative" },
            ],
          },
        }),
        { status: 422 },
      ),
  );
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByText(/budget_gp: Budget must be nonnegative/);
  expect(screen.queryByText("Demo adventurer")).not.toBeInTheDocument();
});
it("rejects malformed, mismatched and unsupported optimization responses", () => {
  const scenario = normalize(newDraft(), context.account.snapshot_id);
  for (const patch of [
    { api_version: "other" },
    { scenario: {} },
    { items: [] },
    {
      baseline: {
        status: "unavailable",
        equipment: {},
        performance,
        reasons: [],
      },
    },
    { result: { ...response().result, snapshot_id: "old" } },
    { result: { ...response().result, limitations: [{}] } },
    {
      result: {
        ...response().result,
        selected_solution: {
          ...response().result.selected_solution,
          purchase_cost_gp: -1,
        },
      },
    },
    {
      result: {
        ...response().result,
        selected_solution: {
          ...response().result.selected_solution,
          loadouts: {
            "role-1": { equipment: { not_a_slot: 4151 }, performance },
          },
        },
      },
    },
    {
      result: {
        ...response().result,
        selected_solution: {
          ...response().result.selected_solution,
          loadouts: {
            "role-1": {
              equipment: { weapon: 4151 },
              performance: { ...performance, supported: false },
            },
          },
        },
      },
    },
  ])
    expect(() =>
      parseOptimization({ ...response(), ...patch }, scenario),
    ).toThrow();
});
it("cancels and rejects an account refresh during optimization", async () => {
  const user = userEvent.setup();
  let finish!: (r: Response) => void;
  let signal: AbortSignal | null | undefined;
  let reads = 0;
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/context"))
      return new Response(
        JSON.stringify(
          reads++
            ? {
                ...context,
                account: { ...context.account, snapshot_id: "new-account" },
              }
            : context,
        ),
      );
    signal = init?.signal;
    return new Promise<Response>((resolve) => {
      finish = resolve;
    });
  }) as unknown as typeof fetch;
  render(
    <GearProvider client={new HttpGearClient("/ui-api/gear", fetcher)}>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await user.click(screen.getByRole("button", { name: "Refresh account" }));
  await screen.findByText(
    "Account changed during optimization. Refresh and rerun.",
  );
  expect(signal?.aborted).toBe(true);
  finish(new Response(JSON.stringify(response())));
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: /Best configuration found/ }),
    ).not.toBeInTheDocument(),
  );
});
it("draft edits abort pending work and late successes cannot publish", async () => {
  const user = userEvent.setup();
  let finish!: (r: Response) => void;
  let signal: AbortSignal | null | undefined;
  setup(response(), (init) => {
    signal = init?.signal;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await user.type(
    screen.getByLabelText("Additional purchase budget (GP)"),
    "1",
  );
  expect(signal?.aborted).toBe(true);
  finish(new Response(JSON.stringify(response())));
  await waitFor(() =>
    expect(
      screen.queryByRole("heading", { name: /Best configuration found/ }),
    ).not.toBeInTheDocument(),
  );
});
it("retains a previous result but withholds its metric comparison for a different target", async () => {
  const user = userEvent.setup();
  setup();
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  await user.clear(screen.getByLabelText("Target defence"));
  await user.type(screen.getByLabelText("Target defence"), "100");
  await user.click(screen.getByRole("button", { name: "Reoptimize" }));
  await screen.findByRole("heading", {
    name: "Previous configuration comparison",
  });
  expect(screen.getByText(/Performance comparison unavailable/)).toBeVisible();
});
it("supports explicit hypothetical skills and quests while keeping requests local", () => {
  const draft = newDraft();
  draft.assumptions.skillLevels = "strength=90, ranged=75";
  draft.assumptions.completedQuests = "monkey_madness_i";
  expect(() => normalize(draft, "x", true)).toThrow("hypothetical");
  draft.mode = "future";
  const request = optimizationRequest(normalize(draft, "x", true));
  expect(request.skill_overrides).toEqual({ strength: 90, ranged: 75 });
  expect(request.quest_overrides).toEqual({ monkey_madness_i: "complete" });
  expect(context.account).not.toHaveProperty("skill_overrides");
  expect(
    optimizationRequest(normalize({ ...draft, exclusions: [4151] }, "x", true)),
  ).toHaveProperty("excluded_item_ids", [4151]);
});
it("retains backend target metadata when editing preset defence", async () => {
  const user = userEvent.setup();
  const fetcher = setup();
  await screen.findByText("Synchronized ranger", { exact: true });
  await user.selectOptions(
    screen.getByLabelText("Target selection"),
    "Dagannoth Supreme",
  );
  await user.clear(screen.getByLabelText("Target defence"));
  await user.type(screen.getByLabelText("Target defence"), "120");
  await user.click(screen.getByRole("button", { name: "Run optimization" }));
  await screen.findByRole("heading", { name: /Best configuration found/ });
  const call = vi
    .mocked(fetcher)
    .mock.calls.find(([url]) => String(url).endsWith("/optimizations"))!;
  const target = JSON.parse(String(call[1]?.body)).roles[0].target;
  const source = context.capabilities.encounter_presets[0].roles[0].target;
  expect(target).toEqual({ ...source, defence_level: 120 });
});

it("accepts strict backend provenance without community classification bytes", () => {
  const scenario = normalize(
    { ...newDraft(), supportPolicy: "verified_only" },
    context.account.snapshot_id,
  );
  const reply = response();
  reply.scenario = optimizationRequest(scenario);
  Object.assign(reply.result, {
    support_policy: "verified_only",
    support_provenance: "",
  });
  expect(
    parseOptimization(reply, scenario).scenario.request.support_policy,
  ).toBe("verified_only");
  Object.assign(reply.result, { support_policy: "community_best_effort" });
  expect(() => parseOptimization(reply, scenario)).toThrow(/support policy/);
  Object.assign(reply.result, {
    support_policy: "verified_only",
    support_provenance: 42,
  });
  expect(() => parseOptimization(reply, scenario)).toThrow(/provenance/);
});
