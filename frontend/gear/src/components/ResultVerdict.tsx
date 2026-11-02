import type { OptimizationDTO } from "../api/contracts";

const signed = (value: number, digits: number) =>
  `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;

function gainLabel(dps: number, reference: number, name: string) {
  const gain = dps - reference;
  if (Math.abs(gain) < 0.005) return `Same as ${name}`;
  const percent =
    reference > 0 ? ` (${signed((gain / reference) * 100, 1)}%)` : "";
  return `${signed(gain, 2)}${percent} vs ${name}`;
}

export function ResultVerdict({
  dps,
  baseline,
  previousDps,
  isAttackStyleOptimized = false,
}: {
  dps: number;
  baseline?: OptimizationDTO["baseline"];
  previousDps?: number;
  isAttackStyleOptimized?: boolean;
}) {
  const baselineDps =
    baseline?.status === "available"
      ? (baseline.performance?.dps ?? null)
      : null;
  return (
    <div className="verdict">
      <strong className="verdict-dps numeric">{dps.toFixed(2)} DPS</strong>
      {baselineDps !== null ? (
        <span className={dps >= baselineDps ? "green" : "gold"}>
          {gainLabel(dps, baselineDps, "current gear")}
        </span>
      ) : (
        baseline && (
          <span className="verdict-note">
            Comparison with current gear unavailable:{" "}
            {baseline.reasons.join(" ") || "no evaluation returned."}
          </span>
        )
      )}
      {previousDps !== undefined && (
        <span className="verdict-note">
          {gainLabel(dps, previousDps, "previous run")}
        </span>
      )}
      {baselineDps !== null && isAttackStyleOptimized && (
        <small className="verdict-caveat">
          Current gear uses your configured attack style; this setup uses its
          best style, so the gain can include both.
        </small>
      )}
    </div>
  );
}
