import type { OptimizationProgress } from "./contracts";

/** randomUUID requires a secure context; getRandomValues also works on HTTP. */
export function createProgressId(): string | null {
  const source = globalThis.crypto;
  if (typeof source?.randomUUID === "function") return source.randomUUID();
  if (typeof source?.getRandomValues !== "function") return null;
  const bytes = source.getRandomValues(new Uint8Array(16));
  const uuid = Array.from(bytes, (byte, index) => {
    const value =
      index === 6 ? (byte & 15) | 64 : index === 8 ? (byte & 63) | 128 : byte;
    return value.toString(16).padStart(2, "0");
  }).join("");
  return `${uuid.slice(0, 8)}-${uuid.slice(8, 12)}-${uuid.slice(12, 16)}-${uuid.slice(16, 20)}-${uuid.slice(20)}`;
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
        const raw = body.progress;
        const progress = raw && {
          ...raw,
          completed: raw.completed ?? raw.completed_profiles,
          total: raw.total ?? raw.total_profiles,
        };
        if (
          active &&
          body.progress_id === id &&
          progress &&
          typeof progress.phase === "string" &&
          progress.phase.length <= 100 &&
          Number.isInteger(progress.completed) &&
          progress.completed >= 0 &&
          Number.isInteger(progress.total) &&
          progress.total >= progress.completed &&
          Number.isFinite(progress.elapsed_seconds) &&
          progress.elapsed_seconds >= 0
        )
          update(progress);
      }
    } catch {
      // Optional telemetry can be absent or temporarily unavailable.
    } finally {
      if (active) timer = setTimeout(() => void poll(), 1000);
    }
  }
  if (active) timer = setTimeout(() => void poll(), 1000);
  return stop;
}
