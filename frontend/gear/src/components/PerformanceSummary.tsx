import type { Metrics } from "../api/contracts";
import { formatInterval } from "./resultFormat";
export function PerformanceSummary({
  metrics,
  title = "Illustrative combat telemetry",
  live = false,
}: {
  metrics: Metrics;
  title?: string;
  live?: boolean;
}) {
  return (
    <section className="telemetry" aria-label={title}>
      <h3 className="eyebrow">{title}</h3>
      <div className="metrics">
        {[
          [live ? "Calculated DPS" : "Effective DPS", metrics.dps.toFixed(2)],
          ["Max hit", metrics.maxHit],
          ["Accuracy", `${(metrics.accuracy * 100).toFixed(1)}%`],
          [
            "Interval",
            metrics.seconds !== undefined
              ? formatInterval(metrics.seconds)
              : `${metrics.ticks} ticks`,
          ],
        ].map(([label, value]) => (
          <div key={label}>
            <span className="eyebrow">{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <p>
        {live
          ? "Calculated for ordinary attacks"
          : "Authored fixture numbers · no combat calculation"}
      </p>
    </section>
  );
}
