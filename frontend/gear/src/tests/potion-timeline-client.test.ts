import { describe, expect, it, vi } from "vitest";
import { HttpGearClient } from "../api/httpClient";
import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";
import { newDraft, normalize } from "../state/scenario";

const scenario = normalize(newDraft(), "snapshot");
const role = scenario.request.roles[0].id;
const option = {
  attack_type: "slash",
  stance: "aggressive",
  spell: null,
  powered_attack: null,
};
const result = {
  source: "live",
  scenario,
  snapshotId: "snapshot",
  catalogVersion: "catalog",
  modelVersion: "combat",
  live: { scenario: { roles: [{ id: role, style: "slash" }] } },
} as unknown as OptimizationReply;
const solution = {
  score: 5,
  secondary_value: 0,
  potions: { selected_ids: ["super_strength"] },
  loadouts: {
    [role]: {
      equipment: { weapon: 4151 },
      combat_option: option,
      selected_prayer_ids: [],
      performance: {},
    },
  },
} as unknown as JointSolutionDTO;
const point = (time_seconds: number, dps: number | null) => ({
  time_seconds,
  levels: { strength: 99 },
  dps,
  secondary_value: null,
  roles: { [role]: { dps, secondary_value: null, reasons: [] } },
});
const objectivePoint = (
  sample: ReturnType<typeof point>,
  values: Record<string, number | null>,
) => ({
  ...sample,
  objective_values: values,
  roles: {
    [role]: {
      ...sample.roles[role],
      objective_values: sample.dps === null ? {} : values,
    },
  },
});
const timeline = () => ({
  snapshot_id: "snapshot",
  catalog_version: "catalog",
  model_version: "combat",
  decay_model_version: "potion-decay-v1",
  configuration_fingerprint: "config",
  secondary_priority: "default",
  baseline: point(0, 4),
  samples: [point(0, 5), point(60, null)],
});

it("uses frozen session references for vector timelines", async () => {
  const selected = { ...solution, objective_values: { prayer_bonus: 3 } };
  const vector = {
    ...result,
    scenario: {
      ...scenario,
      request: {
        ...scenario.request,
        objectives: [{ kind: "prayer_bonus" as const }],
      },
    },
    solutions: [],
    live: {
      ...result.live!,
      run_id: "frozen-run",
      result: {
        objective_frontiers: [
          { points: [{ id: "group-objective-point", solution: selected }] },
        ],
      },
    },
  } as unknown as OptimizationReply;
  const data = timeline();
  const enriched = {
    ...data,
    objective_definitions: [
      {
        id: "prayer_bonus",
        kind: "prayer_bonus",
        label: "Prayer bonus",
        unit: "bonus",
      },
    ],
    baseline: objectivePoint(data.baseline, { prayer_bonus: 3 }),
    samples: data.samples.map((point) =>
      objectivePoint(point, { prayer_bonus: 3 }),
    ),
  };
  const transport = vi.fn(
    async () => new Response(JSON.stringify(enriched), { status: 200 }),
  );
  await new HttpGearClient(
    "/ui-api/gear",
    transport as typeof fetch,
  ).potionTimeline(vector, selected, new AbortController().signal);
  expect(
    JSON.parse(
      (transport.mock.calls[0] as unknown as [string, RequestInit])[1]
        .body as string,
    ),
  ).toEqual({ run_id: "frozen-run", solution_id: "group-objective-point" });
});
const transport = (body: unknown, status = 200) =>
  vi
    .fn<typeof fetch>()
    .mockImplementation(
      async () => new Response(JSON.stringify(body), { status }),
    );

it.each([
  "best-found",
  "curve-2",
  "unrestricted",
  "discipline-melee-best-found",
])(
  "loads the archived %s setup even when it is absent from the chart sample",
  async (alias) => {
    const selected = { ...solution, objective_values: { prayer_bonus: 3 } };
    const vector = {
      ...result,
      scenario: {
        ...scenario,
        request: {
          ...scenario.request,
          objectives: [{ kind: "prayer_bonus" }],
        },
      },
      solutions:
        alias === "unrestricted" ? [] : [{ id: alias, live: selected }],
      unrestricted:
        alias === "unrestricted" ? { id: alias, live: selected } : undefined,
      live: {
        ...result.live!,
        run_id: "frozen-run",
        result: {
          selected_solution:
            alias === "unrestricted" ? { ...selected, score: 6 } : selected,
          unrestricted: alias === "unrestricted" ? selected : null,
          objective_frontiers: [],
          objective_run: {
            selected_solution_id:
              alias === "unrestricted"
                ? "objective-another"
                : "objective-stored-selection",
            solution_references: { [alias]: "objective-stored-selection" },
          },
        },
      },
    } as unknown as OptimizationReply;
    const data = timeline();
    const fetcher = transport({
      ...data,
      baseline: objectivePoint(data.baseline, { prayer_bonus: 3 }),
      samples: data.samples.map((point) =>
        objectivePoint(point, { prayer_bonus: 3 }),
      ),
    });
    await new HttpGearClient("/gear", fetcher).potionTimeline(
      vector,
      selected,
      new AbortController().signal,
    );
    expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({
      run_id: "frozen-run",
      solution_id: "objective-stored-selection",
    });
  },
);

describe("potion timeline transport", () => {
  it("accepts an explicit DPS-only timeline with omitted empty objective maps", async () => {
    const vector = {
      ...result,
      scenario: {
        ...scenario,
        request: { ...scenario.request, objectives: [] },
      },
      live: {
        ...result.live!,
        run_id: "run",
        result: {
          selected_solution: solution,
          objective_run: { selected_solution_id: "objective-selected" },
        },
      },
    } as unknown as OptimizationReply;
    await expect(
      new HttpGearClient("/gear", transport(timeline())).potionTimeline(
        vector,
        solution,
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ secondary_priority: "default" });
  });

  it.each([true, false])(
    "allows unavailable objective samples only when the attack is unavailable (%s)",
    async (unavailable) => {
      const selected = { ...solution, objective_values: { prayer_bonus: 3 } };
      const vector = {
        ...result,
        scenario: {
          ...scenario,
          request: {
            ...scenario.request,
            objectives: [{ kind: "prayer_bonus" }],
          },
        },
        live: {
          ...result.live!,
          run_id: "run",
          result: {
            selected_solution: selected,
            objective_run: { selected_solution_id: "objective-selected" },
          },
        },
      } as unknown as OptimizationReply;
      const invalid = objectivePoint(point(60, unavailable ? null : 4), {
        prayer_bonus: null,
      });
      const body = {
        ...timeline(),
        baseline: { ...invalid, time_seconds: 0 },
        samples: [objectivePoint(point(0, 5), { prayer_bonus: 3 }), invalid],
      };
      const reply = new HttpGearClient("/gear", transport(body)).potionTimeline(
        vector,
        selected,
        new AbortController().signal,
      );
      if (unavailable)
        await expect(reply).resolves.toMatchObject({ baseline: { dps: null } });
      else await expect(reply).rejects.toThrow(/objective/i);
    },
  );

  it("validates the selected secondary value and retains finite negative equipment metrics", async () => {
    const measured = {
      ...result,
      scenario: {
        ...scenario,
        request: {
          ...scenario.request,
          secondary_priority: "magic_defence" as const,
        },
      },
    };
    const body = {
      ...timeline(),
      secondary_priority: "magic_defence",
      samples: timeline().samples.map((p) => ({ ...p, secondary_value: -3 })),
    };
    const client = new HttpGearClient("/gear", transport(body));
    await expect(
      client.potionTimeline(measured, solution, new AbortController().signal),
    ).rejects.toThrow(/Fresh/);
    await expect(
      client.potionTimeline(
        measured,
        { ...solution, secondary_value: -3 },
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ secondary_priority: "magic_defence" });
  });
  it("uses the selected performance option and excludes utility roles", async () => {
    const selected = {
      ...solution,
      loadouts: {
        [role]: {
          ...solution.loadouts[role],
          combat_option: undefined,
          performance: {
            ...solution.loadouts[role].performance,
            combat_option: option,
          },
        },
      },
    };
    const multi = {
      ...result,
      scenario: {
        ...scenario,
        request: {
          ...scenario.request,
          roles: [
            ...scenario.request.roles,
            { ...scenario.request.roles[0], id: "utility", utility: true },
          ],
        },
      },
    };
    const fetcher = transport(timeline());
    await new HttpGearClient("/gear", fetcher).potionTimeline(
      multi,
      selected,
      new AbortController().signal,
    );
    expect(
      Object.keys(
        JSON.parse(fetcher.mock.calls[0][1]!.body as string).loadouts,
      ),
    ).toEqual([role]);
  });
  it("rejects fixture results before sending and handles a generic API failure", async () => {
    const fetcher = transport({ error: {} }, 503);
    const client = new HttpGearClient("/gear", fetcher);
    await expect(
      client.potionTimeline(
        { ...result, source: "fixture" },
        solution,
        new AbortController().signal,
      ),
    ).rejects.toThrow(/live configuration/);
    expect(fetcher).not.toHaveBeenCalled();
    await expect(
      client.potionTimeline(result, solution, new AbortController().signal),
    ).rejects.toMatchObject({ code: "potion_timeline_failed" });
  });
  it("submits the selected exact setup and supports unavailable samples", async () => {
    const fetcher = transport(timeline());
    const signal = new AbortController().signal;
    const response = await new HttpGearClient("/gear", fetcher).potionTimeline(
      result,
      solution,
      signal,
    );
    expect(response.samples[1].dps).toBeNull();
    expect(fetcher.mock.calls[0][0]).toBe("/gear/potion-timelines");
    const init = fetcher.mock.calls[0][1]!;
    expect(init.signal).toBe(signal);
    expect(JSON.parse(init.body as string)).toMatchObject({
      selected_potion_ids: ["super_strength"],
      loadouts: {
        [role]: { combat_option: option, equipment: { weapon: 4151 } },
      },
    });
  });
  it.each([
    { snapshot_id: "other" },
    { catalog_version: "other" },
    { model_version: "other" },
    { decay_model_version: "other" },
    { secondary_priority: "accuracy" },
    { samples: [point(0, 9)] },
    { samples: [point(60, 5)] },
    { samples: [point(0, 5), point(0, 4)] },
    { samples: [point(0, 5), point(60, -1)] },
    { samples: [] },
    { configuration_fingerprint: "" },
    {
      samples: [
        point(0, 5),
        {
          ...point(60, 4),
          roles: { [role]: { dps: -1, secondary_value: null, reasons: [] } },
        },
      ],
    },
    {
      samples: [
        point(0, 5),
        {
          ...point(60, 4),
          roles: { [role]: { dps: 4, secondary_value: null, reasons: [1] } },
        },
      ],
    },
    { samples: [point(0, 5), { ...point(60, 4), roles: {} }] },
    { baseline: { ...point(0, 4), levels: { strength: "99" } } },
  ])("rejects inconsistent timeline data %j", async (change) => {
    await expect(
      new HttpGearClient(
        "/gear",
        transport({ ...timeline(), ...change }),
      ).potionTimeline(result, solution, new AbortController().signal),
    ).rejects.toThrow();
  });
  it("preserves API errors and rejects historical results missing fixed options", async () => {
    await expect(
      new HttpGearClient(
        "/gear",
        transport(
          { error: { code: "snapshot_changed", message: "Refresh and rerun" } },
          409,
        ),
      ).potionTimeline(result, solution, new AbortController().signal),
    ).rejects.toMatchObject({ code: "snapshot_changed" });
    const missing = {
      ...solution,
      loadouts: {
        [role]: { ...solution.loadouts[role], combat_option: undefined },
      },
    };
    await expect(
      new HttpGearClient("/gear", transport(timeline())).potionTimeline(
        result,
        missing,
        new AbortController().signal,
      ),
    ).rejects.toThrow(/combat option/i);
  });
});
