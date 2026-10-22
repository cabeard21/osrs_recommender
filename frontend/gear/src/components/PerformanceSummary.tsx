import type { Metrics } from "../api/contracts";
export function PerformanceSummary({
  metrics,
  title = "Illustrative combat telemetry",
}: {
  metrics: Metrics;
  title?: string;
}) {
  return (
    <section className="telemetry" aria-label={title}>
      <h3 className="eyebrow">{title}</h3>
      <div className="metrics">
        {[
          ["Effective DPS", metrics.dps.toFixed(2)],
          ["Max hit", metrics.maxHit],
          ["Accuracy", `${(metrics.accuracy * 100).toFixed(1)}%`],
          ["Interval", `${metrics.ticks} ticks`],
        ].map(([label, value]) => (
          <div key={label}>
            <span className="eyebrow">{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <p>Authored fixture numbers · no combat calculation</p>
    </section>
  );
}
