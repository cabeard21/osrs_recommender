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

function percent(fraction: number): number {
  return Math.round(Math.min(1, Math.max(0, fraction)) * 100);
}

/** Older servers send only a phase slug and profile counts. */
function statusText(progress: OptimizationProgress): string {
  const counted = progress.total > 0;
  if (!progress.label)
    return `${progress.phase.replaceAll("_", " ")}${counted ? ` · ${progress.completed}/${progress.total} profiles complete` : ""}`;
  return `${progress.label}${counted ? ` · ${progress.completed}/${progress.total} complete` : ""}`;
}

function laneText(lane: ProgressLane): string {
  if (lane.status === "complete") return "Done";
  if (lane.status === "pending") return "Queued";
  return `${percent(lane.fraction)}%`;
}

function countsText(counts: ProgressLaneCounts): string {
  return [
    `${counts.complete} done`,
    `${counts.running} running`,
    ...(counts.pending > 0 ? [`${counts.pending} queued`] : []),
  ].join(" · ");
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
          {lanes.map((lane) => (
            <li key={lane.label} data-status={lane.status}>
              <span className="run-lane-label">
                {lane.label}
                {lane.status === "running" && lane.stage_label && (
                  <span className="run-lane-stage">{lane.stage_label}</span>
                )}
              </span>
              <span className="run-lane-bar" aria-hidden="true">
                <span style={{ width: `${percent(lane.fraction)}%` }} />
              </span>
              <span className="numeric">{laneText(lane)}</span>
            </li>
          ))}
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
  const fraction = progress?.fraction;
  const eta = progress?.eta_seconds;
  const lanes = progress?.lanes ?? [];
  const counts = progress?.lane_counts;
  const isMulti = (progress?.total ?? 0) > 0 && (lanes.length > 0 || !!counts);
  const stages = progress?.stages ?? [];
  return (
    <div className="run-status">
      <div className="run-status-line">
        <Loader2 className="spinner" size={16} aria-hidden="true" />
        <span role="status" aria-label="Optimization progress">
          {progress ? statusText(progress) : message}
        </span>
        <span className="numeric run-status-time">
          {typeof eta === "number" && (
            <span className="run-eta">≈ {formatDuration(eta)} left · </span>
          )}
          {elapsed}s
        </span>
      </div>
      {fraction !== undefined && (
        <div
          className="run-progress"
          role="progressbar"
          aria-label="Optimization completion"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent(fraction)}
        >
          <span style={{ width: `${percent(fraction)}%` }} />
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
