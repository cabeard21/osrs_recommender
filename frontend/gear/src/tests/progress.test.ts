import { afterEach, expect, it, vi } from "vitest";
import { createProgressId, pollOptimizationProgress } from "../api/progress";

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
  await vi.advanceTimersByTimeAsync(1000);
  expect(update).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
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
  await vi.advanceTimersByTimeAsync(1000);
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
  await vi.advanceTimersByTimeAsync(1000);
  expect(transport).toHaveBeenCalledTimes(2);
  rejectPost(new Error("failed"));
  await rejected;
  await vi.advanceTimersByTimeAsync(5000);
  expect(transport).toHaveBeenCalledTimes(2);
});
