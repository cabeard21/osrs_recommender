import type {
  JointSolutionDTO,
  RunningCostFrontierGroup,
  RunningCost,
} from "../api/contracts";

const number = (value: number | null | undefined, digits = 2) =>
  value == null
    ? "Unavailable"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
function CostDetails({ cost }: { cost?: RunningCost }) {
  if (!cost) return <p>Running cost unavailable for this result.</p>;
  return (
    <div>
      <p>
        {number(cost.gp_per_damage, 4)} GP/damage · {number(cost.gp_per_attack)}{" "}
        GP/attack · {number(cost.gp_per_hour)} GP/hour
      </p>
      {cost.status === "unavailable" && (
        <p role="status">
          Cost comparison incomplete:{" "}
          {cost.reasons.join(" ") || "Consumption or prices unavailable."}
        </p>
      )}
      {cost.resources.map((r, index) => (
        <p key={`${r.item_id}-${index}`}>
          {r.name}:{" "}
          {r.supplied_quantity > 0
            ? `${r.supplied_quantity} supplied by ${r.supplied_by ?? "equipment"}; `
            : ""}
          {r.consumed_quantity} consumed per attack
          {r.consumed_quantity > 0
            ? ` at ${number(r.unit_price_gp)} GP each (${r.price_layer})`
            : ""}
        </p>
      ))}
    </div>
  );
}
export function RunningCostFrontier({
  group,
  selectedId,
  selected,
  onSelect,
  itemName,
}: {
  group?: RunningCostFrontierGroup;
  selectedId: string;
  selected?: JointSolutionDTO | null;
  onSelect: (id: string) => void;
  itemName: (id: number) => string;
}) {
  if (!group && !selected?.running_cost) return null;
  const points = group?.points ?? [];
  const numeric = points.filter(
    (p) => p.solution.running_cost?.gp_per_damage != null,
  );
  const maxDps = Math.max(...numeric.map((p) => p.solution.score), 1);
  const maxCost = Math.max(
    ...numeric.map((p) => p.solution.running_cost!.gp_per_damage!),
    0.01,
  );
  return (
    <section className="panel" aria-label="Running cost tradeoffs">
      <style>{`.running-cost-table { border-collapse: collapse; min-width: max-content; } .running-cost-table th, .running-cost-table td { padding: .4rem .6rem; text-align: left; white-space: nowrap; } .running-cost-table tr[aria-selected="true"] { background: #253040; }`}</style>
      <h2>DPS and running cost</h2>
      <p>
        Best-found DPS versus GP per damage. Lower GP per damage is more
        efficient. Continuous attacks; equipment purchases are separate.
      </p>
      {group?.sampled && (
        <p>Showing a sample including the frontier endpoints.</p>
      )}
      {group?.baseline_solution?.running_cost?.status === "unavailable" && (
        <p>
          Highest-DPS baseline: {number(group.baseline_dps, 3)} DPS. Running
          cost unavailable; numerical comparison coverage is incomplete.
        </p>
      )}
      {points.length < 2 && (
        <p>No additional cost tradeoff found within the search limits.</p>
      )}
      {numeric.length > 0 && (
        <svg
          viewBox="0 0 500 190"
          role="group"
          aria-label="DPS against GP per damage; use the table to select"
          style={{ width: "100%", maxHeight: 240 }}
        >
          <path d="M45 15 V155 H480" stroke="currentColor" fill="none" />
          <text x="225" y="185" fill="currentColor" fontSize="12">
            DPS
          </text>
          <text x="50" y="14" fill="currentColor" fontSize="12">
            GP per damage (lower is better)
          </text>
          <text x="45" y="170" fill="currentColor" fontSize="10">
            0
          </text>
          <text x="450" y="170" fill="currentColor" fontSize="10">
            {number(maxDps, 2)}
          </text>
          <text x="2" y="30" fill="currentColor" fontSize="10">
            {number(maxCost, 2)}
          </text>
          {numeric.map((p, i) => (
            <circle
              key={p.id}
              cx={45 + (430 * p.solution.score) / maxDps}
              cy={
                150 - (120 * p.solution.running_cost!.gp_per_damage!) / maxCost
              }
              r={p.id === selectedId ? 7 : 5}
              fill="currentColor"
              role="button"
              tabIndex={0}
              aria-label={`Select cost chart tradeoff ${i + 1}`}
              aria-pressed={p.id === selectedId}
              onClick={() => onSelect(p.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(p.id);
                }
              }}
            >
              <title>
                {number(p.solution.score, 3)} DPS,{" "}
                {number(p.solution.running_cost!.gp_per_damage, 4)} GP/damage
              </title>
            </circle>
          ))}
        </svg>
      )}
      {points.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table
            className="running-cost-table"
            aria-label="DPS and running cost comparisons"
          >
            <thead>
              <tr>
                <th>Choose</th>
                <th>Attack / staff</th>
                <th>DPS</th>
                <th>DPS loss</th>
                <th>GP/damage</th>
                <th>GP/attack</th>
                <th>GP/hour</th>
                <th>Gear purchase GP</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={p.id} aria-selected={p.id === selectedId}>
                  <td>
                    <button
                      aria-label={`Select cost tradeoff ${i + 1}`}
                      aria-pressed={p.id === selectedId}
                      onClick={() => onSelect(p.id)}
                    >
                      {i === 0
                        ? p.solution.score === group?.baseline_dps
                          ? "Highest DPS"
                          : "Highest priced DPS"
                        : "Tradeoff " + (i + 1)}
                    </button>
                  </td>
                  <td>
                    {Object.entries(p.solution.loadouts).map(([role, l]) => (
                      <div key={role}>
                        {(
                          l.combat_option?.powered_attack ??
                          l.combat_option?.spell ??
                          l.discipline ??
                          "Attack"
                        ).replaceAll("_", " ")}{" "}
                        ·{" "}
                        {l.equipment.weapon
                          ? itemName(l.equipment.weapon)
                          : "Unarmed"}
                      </div>
                    ))}
                  </td>
                  <td>{number(p.solution.score, 3)}</td>
                  <td>{number(p.dps_loss_pct)}%</td>
                  <td>{number(p.solution.running_cost?.gp_per_damage, 4)}</td>
                  <td>{number(p.solution.running_cost?.gp_per_attack)}</td>
                  <td>{number(p.solution.running_cost?.gp_per_hour)}</td>
                  <td>{number(p.solution.purchase_cost_gp, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && (
        <div>
          <h3>Selected setup resource costs</h3>
          <CostDetails cost={selected.running_cost} />
          {Object.entries(selected.loadouts).map(([role, l]) => (
            <details key={role} open>
              <summary>{role} resources</summary>
              <CostDetails cost={l.running_cost} />
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
