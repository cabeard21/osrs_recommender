import { useEffect, useState } from "react";
import { Check, Circle, Loader2 } from "lucide-react";
import type {
  OptimizationProgress,
  ProgressLane,
  ProgressLaneCounts,
  ProgressStage,
} from "../api/contracts";

type Props = {
  message: string;
  progress?: OptimizationProgress;
};

const SECONDS_PER_MINUTE = 60;

/** Compact "45s" / "2m 05s" duration; never shows fractional seconds. */
export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.ceil(seconds));
  if (whole < SECONDS_PER_MINUTE) return `${whole}s`;
  const minutes = Math.floor(whole / SECONDS_PER_MINUTE);
  return `${minutes}m ${String(whole % SECONDS_PER_MINUTE).padStart(2, "0")}s`;
}

function formatSearchEta([lower, upper]: [number, number]): string {
  const increment = upper < SECONDS_PER_MINUTE ? 5 : 15;
  const start = formatDuration(
    Math.floor(lower / increment) * increment,
  ).replace(/ 00s$/, "");
  const end = formatDuration(Math.ceil(upper / increment) * increment).replace(
    / 00s$/,
    "",
  );
  if (start === "0s") return `Up to ≈ ${end} left in searches`;
  return `≈ ${start === end ? start : `${start}–${end}`} left in searches`;
}

function percent(fraction: number): number {
  return Math.round(Math.min(1, Math.max(0, fraction)) * 100);
}

/** Older servers send only a phase slug and profile counts. */
function statusText(progress: OptimizationProgress): string {
  if (progress.phase === "complete") return "Finalizing results";
  const counted = progress.total > 0;
  if (progress.phase === "merge")
    return `Combining results${counted ? ` · ${progress.completed}/${progress.total} complete` : ""}`;
  if (!progress.label)
    return `${progress.phase.replaceAll("_", " ")}${counted ? ` · ${progress.completed}/${progress.total} profiles complete` : ""}`;
  return `${progress.label}${counted ? ` · ${progress.completed}/${progress.total} complete` : ""}`;
}

function etaText(
  progress: OptimizationProgress | undefined,
  isMulti: boolean,
): string | undefined {
  if (!progress || progress.phase === "complete") return undefined;
  if (typeof progress.eta_seconds === "number")
    return `≈ ${formatDuration(progress.eta_seconds)} left`;
  if (!isMulti || progress.eta_seconds !== null || progress.phase === "merge")
    return undefined;
  if (progress.search_eta_range_seconds)
    return formatSearchEta(progress.search_eta_range_seconds);
  return "Estimating time left";
}

function countsText(counts: ProgressLaneCounts): string {
  return [
    `${counts.complete} done`,
    `${counts.running} running`,
    ...(counts.pending > 0 ? [`${counts.pending} queued`] : []),
    ...(counts.collecting ? [`${counts.collecting} collecting`] : []),
  ].join(" · ");
}

function laneText(lane: ProgressLane, fraction: number | null): string {
  if (lane.status === "complete") return "Done";
  if (lane.status === "pending") return "Queued";
  return fraction === null ? "" : `${percent(fraction)}%`;
}

function StageIcon({ status }: { status: ProgressStage["status"] }) {
  if (status === "complete") return <Check size={13} aria-hidden="true" />;
  if (status === "active")
    return <Loader2 className="spinner" size={13} aria-hidden="true" />;
  return <Circle size={9} aria-hidden="true" />;
}

/** One search's pipeline; with several searches their stages overlap, so lanes replace it. */
function StageChecklist({ stages }: { stages: ProgressStage[] }) {
  return (
    <ol className="run-stages" aria-label="Optimization stages">
      {stages.map((stage) => (
        <li key={stage.id} data-status={stage.status}>
          <StageIcon status={stage.status} />
          <span>{stage.label}</span>
          {stage.status === "active" && stage.fraction > 0 && (
            <span className="numeric">{percent(stage.fraction)}%</span>
          )}
        </li>
      ))}
    </ol>
  );
}

function LaneRows({
  lanes,
  counts,
}: {
  lanes: ProgressLane[];
  counts?: ProgressLaneCounts;
}) {
  return (
    <div className="run-lane-group">
      {counts && (
        <p className="run-lane-counts numeric">{countsText(counts)}</p>
      )}
      {lanes.length > 0 && (
        <ul className="run-lanes" aria-label="Parallel searches">
          {lanes.map((lane, index) => {
            const fraction =
              lane.stage_fraction === undefined
                ? lane.fraction
                : lane.stage_fraction;
            return (
              <li
                key={lane.lane_id ?? `legacy-${index}-${lane.label}`}
                data-status={lane.status}
              >
                <span className="run-lane-label">
                  <span>{lane.label}</span>
                  {lane.status === "running" && lane.stage_label && (
                    <span className="run-lane-stage">{lane.stage_label}</span>
                  )}
                </span>
                <span
                  className="run-lane-bar"
                  data-indeterminate={fraction === null}
                  aria-hidden="true"
                >
                  <span
                    style={
                      fraction === null
                        ? undefined
                        : { width: `${percent(fraction)}%` }
                    }
                  />
                </span>
                <span className="numeric">{laneText(lane, fraction)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function RunStatus({ message, progress }: Props) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const elapsed = Math.max(
    elapsedSeconds,
    Math.floor(progress?.elapsed_seconds ?? 0),
  );
  const lanes = progress?.lanes ?? [];
  const counts = progress?.lane_counts;
  const isMulti = (progress?.total ?? 0) > 0 && (lanes.length > 0 || !!counts);
  const eta = etaText(progress, isMulti);
  const searchCounts = isMulti && progress ? progress : undefined;
  const barValue = searchCounts
    ? searchCounts.completed
    : progress?.fraction !== undefined
      ? percent(progress.fraction)
      : undefined;
  const barMax = searchCounts?.total ?? 100;
  const stages = progress?.stages ?? [];
  return (
    <div className="run-status">
      <div className="run-status-line">
        <Loader2 className="spinner" size={16} aria-hidden="true" />
        <span role="status" aria-label="Optimization progress">
          {progress ? statusText(progress) : message}
        </span>
        <span className="numeric run-status-time">
          {eta && <span className="run-eta">{eta} · </span>}
          {elapsed}s
        </span>
      </div>
      {barValue !== undefined && (
        <div
          className="run-progress"
          role="progressbar"
          aria-label={
            searchCounts ? "Searches completed" : "Optimization completion"
          }
          aria-valuemin={0}
          aria-valuemax={barMax}
          aria-valuenow={barValue}
        >
          <span style={{ width: `${(barValue / barMax) * 100}%` }} />
        </div>
      )}
      {isMulti ? (
        <LaneRows lanes={lanes} counts={counts} />
      ) : (
        stages.length > 0 && <StageChecklist stages={stages} />
      )}
    </div>
  );
}
