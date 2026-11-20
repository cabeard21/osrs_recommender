import type { ObjectiveDefinition } from "../api/objectives";
import { formatTradeoffValue, type TradeoffPoint } from "./objectiveTradeoff";

function columnLabel(definition: ObjectiveDefinition) {
  switch (definition.unit) {
    case "roll":
      return `${definition.label} (roll)`;
    case "probability":
    case "percent":
      return `${definition.label} (%)`;
    case "GP":
    case "GP/damage":
      return `${definition.label} (${definition.unit})`;
    default:
      return definition.label;
  }
}

export function ObjectiveTradeoffTable({
  rows,
  definitions,
  showRisk,
  selectedId,
  loading,
  selecting,
  onSelect,
}: {
  rows: { point: TradeoffPoint; label: string }[];
  definitions: ObjectiveDefinition[];
  showRisk: boolean;
  selectedId: string;
  loading: boolean;
  selecting: boolean;
  onSelect: (id: string) => void;
}) {
  const columns = [
    {
      key: "dps",
      label: "DPS",
      read: (point: TradeoffPoint) => formatTradeoffValue(point.score),
    },
    ...definitions.map((definition) => ({
      key: definition.id,
      label: columnLabel(definition),
      read: (point: TradeoffPoint) =>
        formatTradeoffValue(point.objective_values[definition.id], definition),
    })),
    {
      key: "cost",
      label: "Cost (GP)",
      read: (point: TradeoffPoint) => point.purchase_cost_gp.toLocaleString(),
    },
    ...(showRisk
      ? [
          {
            key: "risk",
            label: "Risk (GP)",
            read: (point: TradeoffPoint) =>
              point.wilderness_loss_gp?.toLocaleString() ?? "Unavailable",
          },
        ]
      : []),
    {
      key: "actions",
      label: "Actions",
      read: (point: TradeoffPoint) => point.maximum_actions,
    },
  ];
  return (
    <div className="objective-table-wrap">
      <table
        className="objective-tradeoff-table"
        role="table"
        aria-label="All objective tradeoffs"
        aria-busy={loading}
      >
        <thead className="objective-table-heading" role="rowgroup">
          <tr role="row">
            <th role="columnheader" scope="col">
              Configuration
            </th>
            {columns.map(({ key, label }) => (
              <th role="columnheader" scope="col" key={key}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody role="rowgroup">
          {rows.map(({ point, label }) => (
            <tr
              role="row"
              key={point.id}
              aria-selected={selectedId === point.id}
            >
              <td role="cell">
                <button
                  type="button"
                  disabled={selecting}
                  aria-pressed={selectedId === point.id}
                  onClick={() => onSelect(point.id)}
                >
                  {label}
                </button>
              </td>
              {columns.map((column) => (
                <td role="cell" key={column.key}>
                  <span
                    aria-hidden="true"
                    className="objective-mobile-cell-label"
                  >
                    {column.label}
                  </span>
                  {column.read(point)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
