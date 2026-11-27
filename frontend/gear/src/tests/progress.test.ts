import { afterEach, expect, it, vi } from "vitest";
import {
  createProgressId,
  parseProgress,
  pollOptimizationProgress,
  PROGRESS_POLL_MS,
} from "../api/progress";

const base = {
  phase: "gear_search",
  completed: 0,
  total: 0,
  elapsed_seconds: 1,
};

it("keeps valid stage, lane, fraction and ETA telemetry", () => {
  expect(
    parseProgress({
      ...base,
      label: "Searching gear combinations",
      fraction: 0.42,
      eta_seconds: 12.5,
      stages: [
        {
          id: "gear_search",
          label: "Searching",
          status: "active",
          fraction: 0.4,
        },
      ],
      lanes: [
        {
          label: "Melee",
          status: "running",
          stage: "gear_search",
          fraction: 0.5,
        },
        { label: "Magic", status: "pending", stage: null, fraction: 0 },
      ],
    }),
  ).toEqual({
    ...base,
    label: "Searching gear combinations",
    fraction: 0.42,
    eta_seconds: 12.5,
    stages: [
      {
        id: "gear_search",
        label: "Searching",
        status: "active",
        fraction: 0.4,
      },
    ],
    lanes: [
      {
        label: "Melee",
        status: "running",
        stage: "gear_search",
        fraction: 0.5,
      },
      { label: "Magic", status: "pending", stage: null, fraction: 0 },
    ],
  });
});

it("drops malformed optional telemetry but rejects malformed required fields", () => {
  expect(
    parseProgress({
      ...base,
      fraction: 2,
      eta_seconds: -1,
      label: "x".repeat(101),
      stages: [{ id: "a", label: "A", status: "bogus", fraction: 0 }],
      lanes: "nope",
    }),
  ).toEqual(base);
  expect(
    parseProgress({
      ...base,
      lane_counts: { complete: 1, running: 2, pending: 3 },
      lanes: [
        {
          label: "Melee",
          status: "running",
          stage: "frontiers",
          stage_label: "Exploring trade-offs",
          fraction: 0.5,
        },
      ],
    }),
  ).toEqual({
    ...base,
    lane_counts: { complete: 1, running: 2, pending: 3 },
    lanes: [
      {
        label: "Melee",
        status: "running",
        stage: "frontiers",
        stage_label: "Exploring trade-offs",
        fraction: 0.5,
      },
    ],
  });
  expect(
    parseProgress({ ...base, lane_counts: { complete: -1, running: 0 } }),
  ).toEqual(base);
  expect(parseProgress({ ...base, eta_seconds: null })).toEqual({
    ...base,
    eta_seconds: null,
  });
  expect(parseProgress({ ...base, completed: 3, total: 2 })).toBeNull();
  expect(parseProgress({ ...base, elapsed_seconds: Number.NaN })).toBeNull();
  expect(parseProgress(null)).toBeNull();
  expect(
    parseProgress({
      phase: "x",
      completed_profiles: 1,
      total_profiles: 2,
      elapsed_seconds: 0,
    }),
  ).toEqual({ phase: "x", completed: 1, total: 2, elapsed_seconds: 0 });
});

it("keeps stable lane identities, full labels, and unknown stage progress", () => {
  const row = {
    label:
      "role-1: Magic / role-2: Ranged · Divine magic, Divine ranging, Divine super combat".repeat(
        2,
      ),
    status: "running",
    stage: "frontiers",
    fraction: 0.9,
  };
  const lane_counts = { complete: 33, running: 2, pending: 4, collecting: 1 };
  const lanes = [
    { ...row, lane_id: 0, stage_fraction: null },
    { ...row, lane_id: 1, stage_fraction: 0.6 },
  ];
  expect(parseProgress({ ...base, total: 40, lane_counts, lanes })).toEqual({
    ...base,
    total: 40,
    lane_counts,
    lanes,
  });
  expect(
    parseProgress({
      ...base,
      lanes: [{ ...row, lane_id: -2, stage_fraction: 3 }],
    })?.lanes,
  ).toEqual([row]);
});

it("validates search-only ETA ranges", () => {
  expect(
    parseProgress({
      ...base,
      eta_seconds: null,
      search_eta_range_seconds: [0, 132.5],
    }),
  ).toEqual({
    ...base,
    eta_seconds: null,
    search_eta_range_seconds: [0, 132.5],
  });
  for (const range of [
    [1],
    [1, 2, 3],
    [2, 1],
    [-1, 1],
    [0, Infinity],
    [0, NaN],
    [0, "2"],
  ]) {
    expect(parseProgress({ ...base, search_eta_range_seconds: range })).toEqual(
      base,
    );
  }
});

it("creates distinct valid UUIDs without randomUUID", () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", {
    configurable: true,
    value: undefined,
  });
  try {
    const first = createProgressId();
    const second = createProgressId();
    expect(first).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(second).not.toBe(first);
  } finally {
    Object.defineProperty(crypto, "randomUUID", {
      configurable: true,
      value: original,
    });
  }
});
afterEach(() => vi.useRealTimers());
it("keeps optimization available without browser crypto", async () => {
  vi.stubGlobal("crypto", undefined);
  try {
    expect(createProgressId()).toBeNull();
    const transport = vi.fn().mockRejectedValue(new Error("POST reached"));
    await expect(
      new HttpGearClient("/gear", transport).optimize(
        normalize(newDraft(), "x"),
        new AbortController().signal,
        vi.fn(),
      ),
    ).rejects.toThrow("POST reached");
    expect(transport.mock.calls[0][0]).toBe("/gear/optimizations");
  } finally {
    vi.unstubAllGlobals();
  }
});
it("ignores stale jobs, emits current progress, and stops on disposal", async () => {
  vi.useFakeTimers();
  const update = vi.fn();
  const transport = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        progress_id: "other",
        progress: {
          phase: "searching",
          completed: 1,
          total: 4,
          elapsed_seconds: 2,
        },
      }),
    })
    .mockResolvedValue({
      ok: true,
      json: async () => ({
        progress_id: "job",
        progress: {
          phase: "searching",
          completed: 2,
          total: 4,
          elapsed_seconds: 3,
        },
      }),
    });
  const stop = pollOptimizationProgress(
    "/gear",
    "job",
    new AbortController().signal,
    transport,
    update,
  );
  await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS);
  expect(update).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS);
  expect(update).toHaveBeenCalledWith({
    phase: "searching",
    completed: 2,
    total: 4,
    elapsed_seconds: 3,
  });
  stop();
  const count = transport.mock.calls.length;
  await vi.advanceTimersByTimeAsync(5000);
  expect(transport).toHaveBeenCalledTimes(count);
});
it("suppresses late progress from an aborted request", async () => {
  vi.useFakeTimers();
  const update = vi.fn(),
    controller = new AbortController();
  let resolve!: (value: unknown) => void;
  const transport = vi.fn(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  ) as unknown as typeof fetch;
  pollOptimizationProgress(
    "/gear",
    "job",
    controller.signal,
    transport,
    update,
  );
  await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS);
  controller.abort();
  resolve({
    ok: true,
    json: async () => ({
      progress_id: "job",
      progress: {
        phase: "searching",
        completed: 2,
        total: 4,
        elapsed_seconds: 3,
      },
    }),
  });
  await vi.advanceTimersByTimeAsync(5000);
  expect(update).not.toHaveBeenCalled();
});
import { HttpGearClient } from "../api/httpClient";
import { newDraft, normalize } from "../state/scenario";
it("does not wait on a pending progress GET when the optimization fails", async () => {
  vi.useFakeTimers();
  let rejectPost!: (error: Error) => void;
  const transport = vi.fn((url: RequestInfo | URL) =>
    String(url).includes("/progress?")
      ? new Promise(() => {})
      : new Promise((_, reject) => {
          rejectPost = reject;
        }),
  ) as unknown as typeof fetch;
  const promise = new HttpGearClient("/gear", transport).optimize(
    normalize(newDraft(), "x"),
    new AbortController().signal,
    vi.fn(),
  );
  const rejected = expect(promise).rejects.toThrow("failed");
  await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS);
  expect(transport).toHaveBeenCalledTimes(2);
  rejectPost(new Error("failed"));
  await rejected;
  await vi.advanceTimersByTimeAsync(5000);
  expect(transport).toHaveBeenCalledTimes(2);
});
