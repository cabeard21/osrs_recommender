import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  JointSolutionDTO,
  ObjectiveFrontierGroup,
  OptimizationReply,
} from "../api/contracts";
import { example, METRICS, metricValue } from "./model";
import { loadLabSession, loadLabSnapshot, storeLabSnapshot } from "./snapshot";
import type { LabReturnTarget } from "./snapshot";
import {
  listenForLabReturn,
  requestLabReturn,
  requestLabOrigin,
  resolveLabReturn,
} from "./returnSelection";

const target: LabReturnTarget = {
  originId: "471f3864-8f3e-4995-81f1-780bdb2eb740",
  workspace: "single",
  runId: "4a9ff7b2-2156-41dc-aad8-1c8ceee5ce19",
  groupId: "frontier-discipline-ranged-8",
  swapLimit: 8,
};
const otherOrigin = "c4062e4b-0b32-4e8c-a772-be4ef4f40741";
const saved = {
  ...example,
  selectedId: example.points[0].id,
  sampleCount: 2,
  sourceDescription: "Saved from current optimization result.",
  metrics: METRICS.map((metric, index) => ({
    ...metric,
    unit: ["dps", "roll", "bonus"][index],
  })),
  points: example.points.slice(0, 2).map((point) => ({
    ...point,
    values: Object.fromEntries(
      METRICS.map((metric) => [metric.key, metricValue(point, metric.key)]),
    ),
  })),
};
const selectedId = saved.selectedId;
const point = { score: 4, maximum_actions: 0 } as JointSolutionDTO;
const group: ObjectiveFrontierGroup = {
  id: target.groupId,
  swap_limit: target.swapLimit,
  baseline_dps: 4,
  sampled: true,
  points: [{ id: selectedId, solution: point, dps_loss: 0, dps_loss_pct: 0 }],
};
const result = {
  source: "live",
  fingerprint: "same-inputs",
  scenario: { request: { max_swaps: 8, roles: [{ id: "role-1" }] } },
  solutions: [],
  live: {
    run_id: target.runId,
    result: {
      discipline_results: [
        {
          discipline: "ranged",
          selected_solution: point,
          objective_frontiers: [group],
        },
      ],
    },
  },
} as unknown as OptimizationReply;

afterEach(() => {
  localStorage.clear();
  vi.useRealTimers();
});

describe("lab return target", () => {
  it("reads both new return metadata and browse-only snapshots", () => {
    const legacy = storeLabSnapshot(saved);
    const session = storeLabSnapshot(saved, undefined, target);
    expect(loadLabSession(legacy).returnTarget).toBeUndefined();
    expect(loadLabSession(session).returnTarget).toEqual(target);
    expect(loadLabSnapshot(session)).toEqual(saved);
  });

  it("rejects invalid return metadata", () => {
    expect(() =>
      storeLabSnapshot(saved, undefined, { ...target, swapLimit: -1 }),
    ).toThrow(/invalid/i);
  });
});

describe("applying a saved Lab point", () => {
  it("checks for the originating tab without applying a setup", async () => {
    const apply = vi.fn();
    const close = listenForLabReturn(target.originId, apply);
    try {
      await expect(requestLabOrigin(target.originId)).resolves.toBeUndefined();
      expect(apply).not.toHaveBeenCalled();
    } finally {
      close?.();
    }
  });

  it("reports that the original tab is unavailable even if another optimizer is open", async () => {
    vi.useFakeTimers();
    const close = listenForLabReturn(otherOrigin, vi.fn());
    try {
      const pending = expect(requestLabOrigin(target.originId)).rejects.toThrow(
        /original Gear optimizer tab is unavailable/i,
      );
      await vi.runAllTimersAsync();
      await pending;
    } finally {
      close?.();
    }
  });

  it("reads the point from the originating Auto discipline archive", () => {
    expect(resolveLabReturn(result, target, selectedId)).toBe(point);
    expect(
      resolveLabReturn(result, target, "discipline-ranged-best-found"),
    ).toBe(point);
    expect(() => resolveLabReturn(result, target, "best-found")).toThrow(
      /setup.*unavailable/i,
    );
  });

  it("rejects a different run with the same fingerprint", () => {
    const rerun = {
      ...result,
      live: { ...result.live!, run_id: otherOrigin },
    };
    expect(() => resolveLabReturn(rerun, target, selectedId)).toThrow(
      /run.*changed/i,
    );
  });

  it("rejects a point with the wrong workspace, frontier or action cap", () => {
    expect(() =>
      resolveLabReturn(result, { ...target, workspace: "multi" }, selectedId),
    ).toThrow(/run.*changed/i);
    expect(() =>
      resolveLabReturn(result, { ...target, groupId: "elsewhere" }, selectedId),
    ).toThrow(/frontier.*unavailable/i);
    expect(() =>
      resolveLabReturn(result, { ...target, swapLimit: 7 }, selectedId),
    ).toThrow(/frontier.*unavailable/i);
    expect(() => resolveLabReturn(result, target, "missing-point")).toThrow(
      /setup.*unavailable/i,
    );
  });

  it("returns a saved Multi selection from its exact lower-cap frontier", () => {
    const scoped = {
      ...target,
      workspace: "multi",
      swapLimit: 4,
      groupId: "frontier-global-4",
    } as const;
    const viewedId = `${scoped.groupId}-viewed`;
    const multi = {
      ...result,
      scenario: {
        request: { max_swaps: 8, roles: [{ id: "role-1" }, { id: "role-2" }] },
      },
      solutions: [
        { id: "curve-4", live: point },
        { id: viewedId, live: point },
        { id: "frontier-global-8-viewed", live: point },
      ],
      live: {
        run_id: target.runId,
        result: {
          objective_frontiers: [
            { ...group, id: scoped.groupId, swap_limit: scoped.swapLimit },
          ],
        },
      },
    } as unknown as OptimizationReply;
    expect(resolveLabReturn(multi, scoped, "curve-4")).toBe(point);
    expect(resolveLabReturn(multi, scoped, viewedId)).toBe(point);
    expect(() =>
      resolveLabReturn(multi, scoped, "frontier-global-8-viewed"),
    ).toThrow(/setup.*unavailable/i);
  });

  it("returns an acknowledgement from only the originating tab", async () => {
    const token = storeLabSnapshot(saved, undefined, target);
    const first = vi.fn();
    const second = vi.fn();
    const closeFirst = listenForLabReturn(target.originId, first);
    const closeSecond = listenForLabReturn(otherOrigin, second);
    try {
      await requestLabReturn(token, selectedId);
      expect(first).toHaveBeenCalledExactlyOnceWith(target, selectedId);
      expect(second).not.toHaveBeenCalled();
    } finally {
      closeFirst?.();
      closeSecond?.();
    }
  });

  it("reports an origin rejection and rejects selections outside the saved points", async () => {
    const token = storeLabSnapshot(saved, undefined, target);
    const apply = vi.fn(() => {
      throw new Error("The optimization run has changed.");
    });
    const close = listenForLabReturn(target.originId, apply);
    try {
      await expect(requestLabReturn(token, selectedId)).rejects.toThrow(
        /run has changed/,
      );
      await expect(requestLabReturn(token, "unlisted")).rejects.toThrow(
        /setup.*unavailable/i,
      );
      expect(apply).toHaveBeenCalledTimes(1);
    } finally {
      close?.();
    }
  });

  it("times out with recovery instructions if the originating tab is closed", async () => {
    vi.useFakeTimers();
    const token = storeLabSnapshot(saved, undefined, target);
    const pending = expect(requestLabReturn(token, selectedId)).rejects.toThrow(
      /original Gear optimizer tab.*reopen/i,
    );
    await vi.runAllTimersAsync();
    await pending;
  });

  it("rejects an expired Lab session without applying a selection", async () => {
    vi.useFakeTimers();
    const token = storeLabSnapshot(saved, undefined, target);
    vi.setSystemTime(Date.now() + 2 * 60 * 60 * 1000 + 1);
    await expect(requestLabReturn(token, selectedId)).rejects.toThrow(
      /expired/i,
    );
  });
});
