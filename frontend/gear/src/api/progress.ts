import type {
  OptimizationProgress,
  ProgressLane,
  ProgressLaneCounts,
  ProgressStage,
} from "./contracts";

/** Fast enough for a smooth bar; the endpoint is a cheap in-memory read. */
export const PROGRESS_POLL_MS = 400;
const MAX_TEXT = 100;
const MAX_LANE_LABEL = 512;
const MAX_STAGES = 12;
const MAX_LANES = 12;
const STAGE_STATUSES = new Set(["complete", "active", "pending"]);
const LANE_STATUSES = new Set(["complete", "running", "pending"]);

export { createBrowserUuid as createProgressId } from "../browserUuid";

function text(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_TEXT;
}

function unit(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  );
}

function rows<T>(
  value: unknown,
  limit: number,
  parse: (row: Record<string, unknown>) => T | null,
): T[] | undefined {
  if (!Array.isArray(value) || value.length > limit) return undefined;
  const parsed = value.map((row) =>
    row && typeof row === "object"
      ? parse(row as Record<string, unknown>)
      : null,
  );
  return parsed.every((row) => row !== null) ? (parsed as T[]) : undefined;
}

function stage(row: Record<string, unknown>): ProgressStage | null {
  return text(row.id) &&
    text(row.label) &&
    typeof row.status === "string" &&
    STAGE_STATUSES.has(row.status) &&
    unit(row.fraction)
    ? {
        id: row.id,
        label: row.label,
        status: row.status as ProgressStage["status"],
        fraction: row.fraction,
      }
    : null;
}

function lane(row: Record<string, unknown>): ProgressLane | null {
  return typeof row.label === "string" &&
    row.label.length <= MAX_LANE_LABEL &&
    typeof row.status === "string" &&
    LANE_STATUSES.has(row.status) &&
    (row.stage === null || text(row.stage)) &&
    unit(row.fraction)
    ? {
        ...(count(row.lane_id) ? { lane_id: row.lane_id } : {}),
        label: row.label,
        status: row.status as ProgressLane["status"],
        stage: row.stage as string | null,
        ...(text(row.stage_label) ? { stage_label: row.stage_label } : {}),
        ...(unit(row.stage_fraction) || row.stage_fraction === null
          ? { stage_fraction: row.stage_fraction }
          : {}),
        fraction: row.fraction,
      }
    : null;
}

function count(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function seconds(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function laneCounts(value: unknown): ProgressLaneCounts | undefined {
  if (!value || typeof value !== "object") return undefined;
  const row = value as Record<string, unknown>;
  return count(row.complete) && count(row.running) && count(row.pending)
    ? {
        complete: row.complete,
        running: row.running,
        pending: row.pending,
        ...(count(row.collecting) ? { collecting: row.collecting } : {}),
      }
    : undefined;
}

/** Untrusted server telemetry: required fields must be valid; invalid extras are dropped. */
export function parseProgress(raw: unknown): OptimizationProgress | null {
  if (!raw || typeof raw !== "object") return null;
  const body = raw as Record<string, unknown>;
  const completed = body.completed ?? body.completed_profiles;
  const total = body.total ?? body.total_profiles;
  if (
    !text(body.phase) ||
    !Number.isInteger(completed) ||
    (completed as number) < 0 ||
    !Number.isInteger(total) ||
    (total as number) < (completed as number) ||
    typeof body.elapsed_seconds !== "number" ||
    !Number.isFinite(body.elapsed_seconds) ||
    body.elapsed_seconds < 0
  )
    return null;
  const progress: OptimizationProgress = {
    phase: body.phase,
    completed: completed as number,
    total: total as number,
    elapsed_seconds: body.elapsed_seconds,
  };
  if (text(body.label)) progress.label = body.label;
  if (unit(body.fraction)) progress.fraction = body.fraction;
  if (body.eta_seconds === null || seconds(body.eta_seconds))
    progress.eta_seconds = body.eta_seconds;
  const range = body.search_eta_range_seconds;
  if (Array.isArray(range) && range.length === 2) {
    const [lower, upper] = range;
    if (seconds(lower) && seconds(upper) && lower <= upper)
      progress.search_eta_range_seconds = [lower, upper];
  }
  const stages = rows(body.stages, MAX_STAGES, stage);
  if (stages) progress.stages = stages;
  const lanes = rows(body.lanes, MAX_LANES, lane);
  if (lanes) progress.lanes = lanes;
  const counts = laneCounts(body.lane_counts);
  if (counts) progress.lane_counts = counts;
  return progress;
}

/** Best-effort status polling never delays or fails the optimization itself. */
export function pollOptimizationProgress(
  base: string,
  id: string,
  signal: AbortSignal,
  transport: typeof fetch,
  update: (progress: OptimizationProgress) => void,
): () => void {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active = !signal.aborted;
  const stop = () => {
    active = false;
    clearTimeout(timer);
    controller.abort();
    signal.removeEventListener("abort", stop);
  };
  signal.addEventListener("abort", stop, { once: true });
  async function poll() {
    try {
      const response = await transport(
        `${base}/optimizations/progress?progress_id=${encodeURIComponent(id)}`,
        {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        },
      );
      if (response.ok) {
        const body = await response.json();
        const progress = parseProgress(body.progress);
        if (active && body.progress_id === id && progress) update(progress);
      }
    } catch {
      // Optional telemetry can be absent or temporarily unavailable.
    } finally {
      if (active) timer = setTimeout(() => void poll(), PROGRESS_POLL_MS);
    }
  }
  if (active) timer = setTimeout(() => void poll(), PROGRESS_POLL_MS);
  return stop;
}
