import type {
  JointSolutionDTO,
  ObjectiveFrontierGroup,
  OptimizationReply,
} from "../api/contracts";
import { createBrowserUuid } from "../browserUuid";
import type { LabReturnTarget } from "./snapshot";
import { loadLabSession, selectedLabSolution } from "./snapshot";

const OPEN_CURRENT = "Open the Tradeoff Lab from the current result.";
const SETUP_UNAVAILABLE = `This setup is unavailable in the optimizer. ${OPEN_CURRENT}`;
const NO_DESTINATION =
  "The original Gear optimizer tab did not respond. Return to it and reopen the Lab from the result.";
const NO_CHANNEL = "This browser cannot send a setup to the Gear optimizer.";
const RESPONSE_TIMEOUT_MS = 5000;
const isMessage = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isText = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= 512;

/** Resolve only authoritative reports from the exact accepted run and frontier. */
export function resolveLabReturn(
  result: OptimizationReply | null,
  target: LabReturnTarget,
  pointId: string,
): JointSolutionDTO {
  const live = result?.live;
  if (
    !result ||
    result.source !== "live" ||
    !live ||
    (live.run_id ?? live.result.run_id) !== target.runId ||
    (result.scenario.request.roles.length > 1 ? "multi" : "single") !==
      target.workspace
  )
    throw new Error(`The optimization run has changed. ${OPEN_CURRENT}`);

  const matches = (group: ObjectiveFrontierGroup) =>
    (group.id ?? group.group_id) === target.groupId &&
    group.swap_limit === target.swapLimit;
  const discipline = live.result.discipline_results?.find((branch) =>
    branch.objective_frontiers?.some(matches),
  );
  const group = (
    discipline
      ? discipline.objective_frontiers
      : live.result.objective_frontiers
  )?.find(matches);
  if (!group) throw new Error(`This frontier is unavailable. ${OPEN_CURRENT}`);

  const point = group.points.find(({ id }) => id === pointId);
  if (point) return point.solution;
  if (group.baseline_solution_id === pointId && group.baseline_solution)
    return group.baseline_solution;

  // A snapshot may contain an accepted, already displayed selection outside
  // the sample. Its alias or materialized archive ID must belong to this scope.
  const runCap = result.scenario.request.max_swaps;
  const cap = target.swapLimit;
  const alias = discipline
    ? cap === runCap
      ? `discipline-${discipline.discipline}-best-found`
      : undefined
    : cap === null
      ? "unrestricted"
      : target.workspace === "multi"
        ? `curve-${cap}`
        : cap === runCap
          ? "best-found"
          : undefined;
  const savedSelection =
    pointId === alias || pointId.startsWith(`${target.groupId}-`)
      ? selectedLabSolution(result, pointId)
      : undefined;
  if (savedSelection && (cap === null || savedSelection.maximum_actions <= cap))
    return savedSelection;
  throw new Error(SETUP_UNAVAILABLE);
}

function openChannel(originId: string | null): BroadcastChannel | undefined {
  if (!originId || typeof BroadcastChannel !== "function") return undefined;
  try {
    return new BroadcastChannel(`gear-tradeoff-return:${originId}`);
  } catch {
    return undefined;
  }
}

function returnTargetForPoint(token: string, pointId: string): LabReturnTarget {
  const { snapshot, returnTarget } = loadLabSession(token);
  if (!returnTarget || !snapshot.points.some((point) => point.id === pointId))
    throw new Error(SETUP_UNAVAILABLE);
  return returnTarget;
}

export function listenForLabReturn(
  originId: string | null,
  apply: (target: LabReturnTarget, pointId: string) => void,
): (() => void) | undefined {
  const channel = openChannel(originId);
  if (!channel) return undefined;
  channel.onmessage = ({ data }: MessageEvent<unknown>) => {
    if (!isMessage(data) || !isText(data.requestId)) return;
    const requestId = data.requestId;
    if (data.type === "check-origin") {
      channel.postMessage({ type: "origin-result", requestId, ok: true });
      return;
    }
    if (data.type !== "select" || !isText(data.token) || !isText(data.pointId))
      return;
    let error: string | undefined;
    try {
      const target = returnTargetForPoint(data.token, data.pointId);
      if (target.originId !== originId) throw new Error(SETUP_UNAVAILABLE);
      apply(target, data.pointId);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : SETUP_UNAVAILABLE;
    }
    channel.postMessage({
      type: "selection-result",
      requestId,
      ok: error === undefined,
      error,
    });
  };
  return () => channel.close();
}

export async function requestLabReturn(
  token: string,
  pointId: string,
): Promise<void> {
  const target = returnTargetForPoint(token, pointId);
  return requestOrigin(
    target.originId,
    { type: "select", token, pointId },
    NO_DESTINATION,
  );
}

export function requestLabOrigin(originId: string): Promise<void> {
  return requestOrigin(
    originId,
    { type: "check-origin" },
    "The original Gear optimizer tab is unavailable. If it is still open, switch to it using your browser tabs.",
  );
}

async function requestOrigin(
  originId: string,
  message:
    | { type: "check-origin" }
    | { type: "select"; token: string; pointId: string },
  unavailable: string,
): Promise<void> {
  const requestId = createBrowserUuid();
  const channel = requestId ? openChannel(originId) : undefined;
  if (!channel)
    throw new Error(message.type === "select" ? NO_CHANNEL : unavailable);
  const responseType =
    message.type === "select" ? "selection-result" : "origin-result";
  return new Promise((resolve, reject) => {
    const finish = (error?: string) => {
      window.clearTimeout(timeout);
      channel.close();
      if (error) reject(new Error(error));
      else resolve();
    };
    const timeout = window.setTimeout(
      () => finish(unavailable),
      RESPONSE_TIMEOUT_MS,
    );
    channel.onmessage = ({ data }: MessageEvent<unknown>) => {
      if (
        isMessage(data) &&
        data.type === responseType &&
        data.requestId === requestId &&
        typeof data.ok === "boolean"
      )
        finish(
          data.ok
            ? undefined
            : isText(data.error)
              ? data.error
              : SETUP_UNAVAILABLE,
        );
    };
    try {
      channel.postMessage({ ...message, requestId });
    } catch {
      finish(message.type === "select" ? NO_CHANNEL : unavailable);
    }
  });
}
