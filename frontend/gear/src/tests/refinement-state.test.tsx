import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  emptyEquipment,
  type Equipment,
  type GearClient,
} from "../api/contracts";
import {
  HttpGearClient,
  optimizationRequest,
  parseContext,
  parseOptimization,
  parseEvaluation,
} from "../api/httpClient";
import { GearProvider, useGear } from "../state/GearProvider";
import {
  initialState,
  newDraft,
  normalize,
  reducer,
  upgradeStoredDraft,
} from "../state/scenario";
import context from "./live-context.json";
import { parseAlternatives } from "../api/contextualAlternatives";
import { dpsObjectiveResponse } from "./dps-objective-response";

const performance = {
  supported: true,
  dps: 2,
  max_hit: 10,
  accuracy: 0.5,
  attack_interval: 2.4,
  bonuses: {},
  limitations: [],
};
const scenario = normalize(newDraft(), context.account.snapshot_id, true);
function result(submitted = scenario) {
  return parseOptimization(
    dpsObjectiveResponse({
      api_version: "gear-ui-v1",
      evaluated_at: context.evaluated_at,
      price_revision: context.price_revision,
      scenario_fingerprint: "original-scenario",
      scenario: optimizationRequest(submitted),
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
        search: {},
        limitations: [],
        alternatives: {
          weapon: [
            { item_id: null, score: 1, score_delta: -1, purchase_cost_gp: 0 },
          ],
        },
        selected_solution: {
          score: 2,
          purchase_cost_gp: 0,
          purchases: [],
          loadouts: { "role-1": { equipment: { weapon: 4151 }, performance } },
        },
      },
    }),
    submitted,
  );
}
it("restores legacy untradeable-policy results as readable but outdated", () => {
  const saved = result();
  delete saved.live!.scenario.include_untradeables;
  const state = reducer(
    { ...initialState(), context: parseContext(context) },
    {
      type: "restore-results",
      results: {
        single: {
          result: saved,
          solutionId: saved.solutions[0].id,
          outdated: false,
        },
      },
    },
  );
  expect(state.single.result).toBe(saved);
  expect(state.single.outdated).toBe(true);
  expect(() =>
    parseEvaluation(
      evaluation(),
      saved,
      saved.solutions[0].id,
      "role-1",
      saved.solutions[0].loadouts[0].equipment,
    ),
  ).toThrow(/older acquisition policy/);
});

it.each([
  { cap: undefined, casts: 100 },
  { cap: null, casts: 100 },
  { cap: 0, casts: undefined },
  { cap: 0, casts: null },
  { cap: 0, casts: 100 },
])(
  "checks Wilderness settings when restoring a result ($cap GP, $casts casts)",
  ({ cap, casts }) => {
    const liveContext = parseContext(context);
    const saved = result(
      normalize(newDraft(), liveContext.snapshotId, true, liveContext),
    );
    const settings = {
      depth: "level_21_plus",
      skulled: false,
      protect_item: false,
    } as const;
    const wilderness = {
      ...settings,
      ...(cap === undefined ? {} : { max_loss_gp: cap }),
      ...(casts === undefined ? {} : { spell_casts: casts }),
    };
    saved.scenario.request.wilderness = wilderness;
    saved.live!.scenario.wilderness = wilderness;
    const draft = upgradeStoredDraft({
      ...newDraft(),
      wilderness: settings,
      wildernessRiskBudget: cap == null ? undefined : "0",
    })!;
    const initial = initialState();
    const state = reducer(
      {
        ...initial,
        context: liveContext,
        single: { ...initial.single, draft },
      },
      {
        type: "restore-results",
        results: {
          single: {
            result: saved,
            solutionId: saved.solutions[0].id,
            outdated: false,
          },
        },
      },
    );
    expect(state.single.result).toBe(saved);
    expect(state.single.outdated).toBe(cap == null || casts == null);
  },
);
function evaluation(
  proposed: Record<string, number> = {},
  submitted = scenario,
) {
  const fixed = {
    status: "valid",
    equipment: { weapon: 4151 },
    performance,
    reasons: [],
    purchase_cost_gp: 0,
    purchases: [],
    assumed_item_ids: [],
  };
  return {
    api_version: "gear-ui-v1",
    evaluated_at: context.evaluated_at,
    scenario: optimizationRequest(submitted),
    scenario_fingerprint: "original-scenario",
    snapshot_id: context.account.snapshot_id,
    catalog_version: context.catalog_version,
    model_version: context.model_version,
    assumptions_fingerprint: "assumptions",
    price_revision: context.price_revision,
    items: context.items,
    baseline: fixed,
    proposed: { ...fixed, equipment: proposed },
    deltas: {
      dps: 0,
      max_hit: 0,
      accuracy: 0,
      attack_interval: 0,
      purchase_cost_gp: 0,
      equipment_changes: [
        { slot: "weapon", baseline_item_id: 4151, proposed_item_id: null },
      ],
      added_purchase_ids: [],
      removed_purchase_ids: [],
    },
  };
}
describe("live refinement transport", () => {
  it.each([
    { imaginary: [] },
    { ammo: [] },
    {
      weapon: [{ item_id: -1, score: 1, score_delta: 0, purchase_cost_gp: 0 }],
    },
    {
      weapon: [{ item_id: 99, score: 1, score_delta: 0, purchase_cost_gp: 0 }],
    },
    {
      head: [{ item_id: 4151, score: 1, score_delta: 0, purchase_cost_gp: 0 }],
    },
    {
      weapon: [
        {
          item_id: 4151,
          score: Number.NaN,
          score_delta: 0,
          purchase_cost_gp: 0,
        },
      ],
    },
    {
      weapon: [
        { item_id: 4151, score: 1, score_delta: 0, purchase_cost_gp: -1 },
      ],
    },
  ])("rejects malformed contextual alternatives: %j", (value) => {
    expect(() => parseAlternatives(value, result().items!, [])).toThrow();
  });
  it("rejects excluded contextual alternative IDs and normalizes absent rows", () => {
    expect(parseAlternatives(undefined, [], [])).toEqual({});
    expect(() =>
      parseAlternatives(
        {
          weapon: [
            { item_id: 4151, score: 1, score_delta: 0, purchase_cost_gp: 0 },
          ],
        },
        result().items!,
        [4151],
      ),
    ).toThrow();
  });
  it("submits immutable original and proposed equipment with abort support", async () => {
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify(evaluation())),
    ) as unknown as typeof fetch;
    const accepted = result();
    const before = structuredClone(accepted);
    const signal = new AbortController().signal;
    const trial = await new HttpGearClient("/ui-api/gear", fetcher).evaluate(
      accepted,
      "best-found",
      "role-1",
      emptyEquipment(),
      signal,
    );
    const [url, init] = vi.mocked(fetcher).mock.calls[0];
    expect(url).toBe("/ui-api/gear/evaluations");
    expect(init).toMatchObject({
      method: "POST",
      signal,
      credentials: "same-origin",
      cache: "no-store",
    });
    expect(JSON.parse(String(init?.body))).toEqual({
      scenario: accepted.live!.scenario,
      baseline_loadouts: { "role-1": { weapon: 4151 } },
      proposed_loadouts: { "role-1": {} },
    });
    expect(trial).toMatchObject({
      source: "live",
      equipment: emptyEquipment(),
      live: { deltas: { dps: 0 } },
    });
    expect(accepted).toEqual(before);
  });
  it.each(["fixed", "optimize"] as const)(
    "keeps the selected solution prayers fixed for item comparisons in %s mode",
    async (mode) => {
      const submitted = {
        ...scenario,
        request: {
          ...scenario.request,
          roles: scenario.request.roles.map((role) => ({
            ...role,
            prayers: {
              mode,
              allowed_ids: mode === "optimize" ? ["ultimate_strength"] : [],
              selected_ids: mode === "fixed" ? ["ultimate_strength"] : [],
            },
          })),
        },
      };
      const accepted = result(submitted);
      accepted.solutions[0].loadouts[0].selectedPrayerIds = [
        "ultimate_strength",
      ];
      const fetcher = vi.fn(
        async () => new Response(JSON.stringify(evaluation({}, submitted))),
      ) as unknown as typeof fetch;
      await new HttpGearClient("/ui-api/gear", fetcher).evaluate(
        accepted,
        "best-found",
        "role-1",
        emptyEquipment(),
      );
      const [, init] = vi.mocked(fetcher).mock.calls[0];
      expect(JSON.parse(String(init?.body)).selected_prayer_ids).toEqual({
        "role-1": ["ultimate_strength"],
      });
    },
  );
  it("preserves invalid reasons and null metrics instead of fabricating a trial", async () => {
    const reply = evaluation();
    Object.assign(reply.proposed, {
      status: "invalid",
      performance: null,
      reasons: [
        {
          path: "proposed_loadouts.role-1.weapon",
          message: "Locked weapon cannot be removed",
        },
      ],
    });
    Object.assign(reply, { deltas: null });
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify(reply)),
    ) as unknown as typeof fetch;
    const trial = await new HttpGearClient("/ui-api/gear", fetcher).evaluate(
      result(),
      "best-found",
      "role-1",
      emptyEquipment(),
    );
    expect(trial.proposed).toBeNull();
    expect(
      trial.source === "live" && trial.live.proposed.reasons[0].message,
    ).toContain("Locked");
  });
  it("retains authoritative wrong-slot validation reasons for a recognized physical item", async () => {
    const reply = evaluation({ head: 4151 });
    Object.assign(reply.proposed, {
      status: "invalid",
      performance: null,
      reasons: [
        {
          path: "proposed_loadouts.role-1.head",
          message: "Physical item 4151 does not occupy head",
        },
      ],
    });
    Object.assign(reply, { deltas: null });
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify(reply)),
    ) as unknown as typeof fetch;
    const trial = await new HttpGearClient("/ui-api/gear", fetcher).evaluate(
      result(),
      "best-found",
      "role-1",
      { ...emptyEquipment(), head: 4151 },
    );
    expect(
      trial.source === "live" && trial.live.proposed.reasons[0].message,
    ).toContain("does not occupy head");
    expect(trial.proposed).toBeNull();
  });
  it.each([
    { snapshot_id: "old" },
    { scenario_fingerprint: "other" },
    { catalog_version: "old" },
    { model_version: "old" },
    { assumptions_fingerprint: "other" },
    { price_revision: "other" },
    { proposed: { ...evaluation().proposed, equipment: { weapon: 4151 } } },
    {
      proposed: {
        ...evaluation().proposed,
        performance: { ...performance, dps: null },
      },
    },
    { deltas: { ...evaluation().deltas, accuracy: "invented" } },
    { items: [] },
  ])("rejects stale or malformed evaluations: %j", async (patch) => {
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify({ ...evaluation(), ...patch })),
    ) as unknown as typeof fetch;
    await expect(
      new HttpGearClient("/ui-api/gear", fetcher).evaluate(
        result(),
        "best-found",
        "role-1",
        emptyEquipment(),
      ),
    ).rejects.toThrow();
  });
  it("supports concrete exclusions while preserving locks and single-style restrictions", () => {
    const draft = { ...newDraft(), exclusions: [4151] };
    expect(
      optimizationRequest(normalize(draft, "account", true)),
    ).toHaveProperty("excluded_item_ids", [4151]);
    expect(() =>
      normalize({ ...draft, exclusions: [-1] }, "account", true),
    ).toThrow();
    expect(() =>
      normalize(
        { ...draft, roles: [{ ...draft.roles[0], locks: { weapon: 4151 } }] },
        "account",
        true,
      ),
    ).toThrow("locked");
  });
  it("preserves backend field errors and does not evaluate fixture results over HTTP", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "invalid_request",
              message: "Invalid equipment",
              fields: [
                {
                  path: "proposed_loadouts.role-1.weapon",
                  message: "Unknown physical item",
                },
              ],
            },
          }),
          { status: 422 },
        ),
    ) as unknown as typeof fetch;
    const client = new HttpGearClient("/ui-api/gear", fetcher);
    await expect(
      client.evaluate(result(), "best-found", "role-1", emptyEquipment()),
    ).rejects.toThrow("proposed_loadouts.role-1.weapon: Unknown physical item");
    await expect(
      client.evaluate(
        { ...result(), source: "fixture" },
        "best-found",
        "role-1",
        emptyEquipment(),
      ),
    ).rejects.toThrow("accepted live");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([
    {
      status: "invalid",
      performance,
      reasons: [{ path: "equipment", message: "Unmet requirement" }],
    },
    { status: "unsupported", performance: null, reasons: [] },
    { purchase_cost_gp: -1 },
    { purchases: [{ item_id: 99, cost_gp: 3, conditional: false }] },
    { assumed_item_ids: [99] },
    { status: "valid", purchase_cost_gp: null },
  ])("rejects invalid acquisition or validity metadata: %j", async (patch) => {
    const reply = {
      ...evaluation(),
      proposed: { ...evaluation().proposed, ...patch },
    };
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify(reply)),
    ) as unknown as typeof fetch;
    await expect(
      new HttpGearClient("/ui-api/gear", fetcher).evaluate(
        result(),
        "best-found",
        "role-1",
        emptyEquipment(),
      ),
    ).rejects.toThrow();
  });
});

let current: ReturnType<typeof useGear>;
function Harness() {
  current = useGear();
  return <p>{current.state.context?.snapshotId ?? "loading"}</p>;
}
async function mountClient() {
  const accepted = result();
  let reads = 0;
  const client: GearClient = {
    getContext: vi.fn(async () =>
      parseContext(
        reads++ ? { ...context, price_revision: "new-prices" } : context,
      ),
    ),
    getItem: vi.fn(),
    alternatives: vi.fn(),
    optimize: vi.fn(async () => accepted),
    evaluate: vi.fn(),
  };
  render(
    <GearProvider client={client}>
      <Harness />
    </GearProvider>,
  );
  await screen.findByText(context.account.snapshot_id);
  await act(() => current.run());
  act(() =>
    current.dispatch({ type: "ui", mode: "single", patch: { slot: "weapon" } }),
  );
  return { client, accepted };
}
describe("trial request isolation", () => {
  it("ignores older same-result trials and leaves accepted/draft equipment untouched", async () => {
    const { client, accepted } = await mountClient();
    const pending: ((
      trial: Awaited<ReturnType<GearClient["evaluate"]>>,
    ) => void)[] = [];
    vi.mocked(client.evaluate).mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    const draft = structuredClone(current.current.draft);
    const makeTrial = (equipment: Equipment) => ({
      source: "live" as const,
      resultFingerprint: accepted.fingerprint,
      solutionId: "best-found",
      roleId: "role-1",
      equipment,
      baseline: { dps: 2, maxHit: 10, accuracy: 0.5 },
      proposed: { dps: 1, maxHit: 5, accuracy: 0.5 },
      live: evaluation(
        equipment.weapon ? { weapon: equipment.weapon } : {},
      ) as import("../api/contracts").EvaluationDTO,
    });
    let first!: Promise<void>, second!: Promise<void>;
    act(() => {
      first = current.previewTrial(emptyEquipment());
    });
    act(() => {
      second = current.previewTrial({ ...emptyEquipment(), weapon: 4151 });
    });
    await act(async () => {
      pending[1](makeTrial({ ...emptyEquipment(), weapon: 4151 }));
      await second;
    });
    await act(async () => {
      pending[0](makeTrial(emptyEquipment()));
      await first;
    });
    expect(current.current.trial?.equipment.weapon).toBe(4151);
    expect(current.current.result).toEqual(accepted);
    expect(current.current.draft).toEqual(draft);
  });
  it.each([
    "revert",
    "cancel",
    "edit",
    "slot",
    "context",
    "navigate",
    "handoff",
  ])("invalidates an in-flight evaluation after %s", async (kind) => {
    const { client } = await mountClient();
    let reject!: (error: Error) => void;
    let signal: AbortSignal | undefined;
    vi.mocked(client.evaluate).mockImplementation((_r, _s, _id, _e, s) => {
      signal = s;
      return new Promise((_resolve, no) => {
        reject = no;
      });
    });
    let running!: Promise<void>;
    act(() => {
      running = current.previewTrial(emptyEquipment());
    });
    expect(current.current.trialPending).toBe(true);
    if (kind === "revert") act(() => current.revertTrial());
    if (kind === "cancel") act(() => current.cancelTrial());
    if (kind === "edit")
      act(() => current.edit({ ...current.current.draft, budget: "12" }));
    if (kind === "slot")
      act(() =>
        current.dispatch({
          type: "ui",
          mode: "single",
          patch: { slot: "head" },
        }),
      );
    if (kind === "context") await act(() => current.loadContext());
    if (kind === "navigate")
      act(() => current.dispatch({ type: "navigate", mode: "multi" }));
    if (kind === "handoff")
      act(() => current.dispatch({ type: "use-single-in-multi" }));
    await waitFor(() => expect(signal?.aborted).toBe(true));
    await act(async () => {
      reject(new Error("obsolete failure"));
      await running;
    });
    expect(current.current.trialPending).toBe(false);
    expect(current.current.trialError).toBeNull();
    expect(current.current.trial).toBeNull();
    expect(current.state.single.trialPending).toBe(false);
  });
  it("clears completed trials when price provenance changes", () => {
    let state = initialState();
    const accepted = result();
    state = {
      ...state,
      context: parseContext(context),
      single: {
        ...state.single,
        result: accepted,
        trial: {
          source: "fixture",
          resultFingerprint: accepted.fingerprint,
          solutionId: "best-found",
          roleId: "role-1",
          equipment: emptyEquipment(),
          baseline: { dps: 2, maxHit: 10, accuracy: 0.5 },
          proposed: { dps: 1, maxHit: 5, accuracy: 0.5 },
        },
      },
    };
    state = reducer(state, {
      type: "context",
      context: parseContext({ ...context, price_revision: "changed" }),
    });
    expect(state.single.trial).toBeNull();
    expect(state.single.outdated).toBe(true);
  });
  it("does not accept fixture trial values into a live result", () => {
    const accepted = result();
    const state = {
      ...initialState(),
      single: { ...initialState().single, result: accepted },
    };
    expect(
      reducer(state, {
        type: "trial",
        mode: "single",
        trial: {
          source: "fixture",
          resultFingerprint: accepted.fingerprint,
          solutionId: "best-found",
          roleId: "role-1",
          equipment: emptyEquipment(),
          baseline: { dps: 2, maxHit: 10, accuracy: 0.5 },
          proposed: { dps: 3, maxHit: 20, accuracy: 0.5 },
        },
      }),
    ).toBe(state);
  });
});
