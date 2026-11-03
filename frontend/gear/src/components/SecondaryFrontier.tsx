import type {
  SecondaryFrontierGroup,
  SecondaryPriority,
} from "../api/contracts";
import { secondaryPriorities } from "../api/secondaryPriorities";
export function SecondaryFrontier({
  group,
  selectedId,
  onSelect,
  priority,
}: {
  group?: SecondaryFrontierGroup;
  selectedId: string;
  onSelect: (id: string) => void;
  priority: SecondaryPriority;
}) {
  if (priority === "default" || !group) return null;
  const points = group.points;
  const label =
    secondaryPriorities.find(([id]) => id === priority)?.[1] ?? priority;
  const percent = priority === "accuracy" ? 100 : 1;
  const unit =
    priority === "accuracy" || priority === "magic_damage_bonus"
      ? " percentage points"
      : " bonus";
  const values = points.map((p) => p.solution.secondary_value ?? 0);
  const low = Math.min(...values, 0),
    high = Math.max(...values, 1);
  const active = points.find((p) => p.id === selectedId)?.solution;
  const maxLoss = Math.max(...points.map((p) => p.dps_loss_pct ?? 0), 1);
  return (
    <section className="panel" aria-label="Secondary tradeoffs">
      <style>{`.frontier-table { border-collapse: collapse; min-width: max-content; } .frontier-table th, .frontier-table td { padding: .4rem .6rem; text-align: left; white-space: nowrap; } .frontier-table tbody tr[aria-selected="true"] { background: #253040; }`}</style>
      <h2>Best-found tradeoff frontier</h2>
      <p>
        {label} versus DPS loss under the same swap limit. Bounded search does
        not establish the global frontier.
      </p>
      {priority === "balanced_defence" && (
        <p>
          Balanced defence is the mean of the five equipment defence bonuses; it
          does not measure damage reduction.
        </p>
      )}
      {priority === "magic_ranged_defence" && (
        <p>
          Magic &amp; ranged defence is the lower of the magic and ranged
          equipment defence bonuses; it does not measure damage reduction.
        </p>
      )}
      {(priority === "balanced_defence" ||
        priority === "magic_ranged_defence") &&
        active &&
        Object.entries(active.loadouts).map(([role, loadout]) => (
          <p key={role}>
            {role} defence bonuses:{" "}
            {(priority === "magic_ranged_defence"
              ? (["magic", "ranged"] as const)
              : (["stab", "slash", "crush", "ranged", "magic"] as const)
            )
              .map(
                (style) =>
                  `${style} ${loadout.performance.bonuses[`defence_${style}`] ?? 0}`,
              )
              .join(" / ")}
          </p>
        ))}
      {points.length <= 1 && (
        <p>No additional tradeoff found within the search limits.</p>
      )}
      {group.sampled && (
        <p>
          Showing a sample of the best-found frontier, including its endpoints.
        </p>
      )}
      {points.length > 0 && (
        <>
          <svg
            viewBox="0 0 500 190"
            style={{ width: "100%", maxHeight: 240 }}
            role="group"
            aria-label={`${label} against DPS loss; use the table to select a solution`}
          >
            <path d="M45 10 V155 H480" fill="none" stroke="currentColor" />
            <text x="220" y="185" fill="currentColor" fontSize="12">
              DPS loss (%)
            </text>
            <text x="50" y="14" fill="currentColor" fontSize="12">
              {label}
            </text>
            <text x="45" y="170" fill="currentColor" fontSize="10">
              0%
            </text>
            <text x="450" y="170" fill="currentColor" fontSize="10">
              {maxLoss.toFixed(1)}%
            </text>
            <text x="5" y="150" fill="currentColor" fontSize="10">
              {(low * percent).toFixed(0)}
            </text>
            <text x="5" y="30" fill="currentColor" fontSize="10">
              {(high * percent).toFixed(0)}
            </text>
            {points.map((p, i) => (
              <circle
                key={p.id}
                cx={45 + (430 * (p.dps_loss_pct ?? 0)) / maxLoss}
                cy={
                  150 -
                  (120 * ((p.solution.secondary_value ?? 0) - low)) /
                    (high - low || 1)
                }
                role="button"
                tabIndex={0}
                aria-label={`Select chart tradeoff ${i + 1}`}
                aria-pressed={p.id === selectedId}
                onClick={() => onSelect(p.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(p.id);
                  }
                }}
                r={p.id === selectedId ? 7 : 5}
                fill="currentColor"
              >
                <title>{`Tradeoff ${i + 1}: ${p.solution.score.toFixed(3)} DPS, ${((p.solution.secondary_value ?? 0) * percent).toFixed(2)} ${label}`}</title>
              </circle>
            ))}
          </svg>
          <div style={{ overflowX: "auto" }}>
            <table
              className="frontier-table"
              aria-label="DPS and secondary tradeoffs"
            >
              <thead>
                <tr>
                  <th>Choose</th>
                  <th>DPS</th>
                  <th>DPS loss</th>
                  <th>{label}</th>
                  <th>Gain</th>
                  <th>Cost (GP)</th>
                  <th>Swaps</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p, i) => (
                  <tr key={p.id}>
                    <td>
                      <button
                        aria-label={`Select tradeoff ${i + 1}`}
                        aria-pressed={selectedId === p.id}
                        onClick={() => onSelect(p.id)}
                      >
                        {i === 0 ? "Highest DPS" : `Tradeoff ${i + 1}`}
                      </button>
                    </td>
                    <td>{p.solution.score.toFixed(3)}</td>
                    <td>
                      {p.dps_loss.toFixed(3)} (
                      {p.dps_loss_pct === null
                        ? "percentage unavailable"
                        : `${p.dps_loss_pct.toFixed(2)}%`}
                      )
                    </td>
                    <td>
                      {((p.solution.secondary_value ?? 0) * percent).toFixed(2)}
                    </td>
                    <td>
                      {(p.secondary_gain * percent).toFixed(2)}
                      {unit}
                    </td>
                    <td>{p.solution.purchase_cost_gp.toLocaleString()}</td>
                    <td>{p.solution.maximum_actions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
