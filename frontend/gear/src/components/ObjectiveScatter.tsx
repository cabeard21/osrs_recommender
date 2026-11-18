import { useId, useState } from "react";
import "../styles/objective-scatter.css";

interface Axis {
  id: string;
  label: string;
  unit?: string;
}
interface Point {
  id: string;
  score: number;
  objective_values: Record<string, number>;
  purchase_cost_gp: number;
}
type Slot = "x" | "y" | "color";
const color = (value: number) =>
  `hsl(${205 - value * 165} 78% ${58 + value * 8}%)`;
const value = (point: Point, id: string): number =>
  id === "dps" ? point.score : point.objective_values[id];
const format = (number: number, axis: Axis) => {
  if (!Number.isFinite(number)) return "Unavailable";
  if (axis.unit === "probability") return `${(number * 100).toFixed(2)}%`;
  if (axis.unit === "percent") return `${number.toFixed(2)}%`;
  return number.toLocaleString("en-US", {
    minimumFractionDigits: axis.id === "dps" ? 3 : 0,
    maximumFractionDigits: axis.id === "dps" ? 3 : 2,
  });
};
export function ObjectiveScatter({
  axes,
  points,
  selectedId,
  onSelect,
  disabled = false,
}: {
  axes: Axis[];
  points: Point[];
  selectedId: string;
  onSelect: (id: string) => void;
  disabled?: boolean;
}) {
  const [chosen, setChosen] = useState({
    x: axes[0]?.id ?? "dps",
    y: axes[1]?.id ?? "dps",
    color: axes[2]?.id ?? "",
  });
  const gradientId = useId().replaceAll(":", "");
  const x = axes.find((a) => a.id === chosen.x) ?? axes[0];
  const y =
    axes.find((a) => a.id === chosen.y && a.id !== x.id) ??
    axes.find((a) => a.id !== x.id);
  const colorAxis = axes.find(
    (a) => a.id === chosen.color && a.id !== x.id && a.id !== y?.id,
  );
  const update = (slot: Slot, id: string) => {
    const current = { x: x.id, y: y?.id ?? "", color: colorAxis?.id ?? "" };
    const duplicate = (Object.keys(current) as Slot[]).find(
      (key) => key !== slot && current[key] === id,
    );
    const replacement =
      current[slot] ||
      axes.find(
        (axis) => axis.id !== id && !Object.values(current).includes(axis.id),
      )?.id ||
      "";
    setChosen({
      ...current,
      ...(duplicate && id ? { [duplicate]: replacement } : {}),
      [slot]: id,
    });
  };
  const available = y
    ? points.filter(
        (point) =>
          Number.isFinite(value(point, x.id)) &&
          Number.isFinite(value(point, y.id)),
      )
    : [];
  if (!y || !available.length)
    return <p>No chart values are available for these objectives.</p>;
  const plotted = available.filter(
    (point) => value(point, x.id) >= 0 && value(point, y.id) >= 0,
  );
  const axisBounds = (axis: Axis): [number, number] => [
    0,
    Math.max(0, ...plotted.map((point) => value(point, axis.id))) || 1,
  ];
  const colorBounds = (axis: Axis): [number, number] => {
    const values = plotted
      .map((point) => value(point, axis.id))
      .filter(Number.isFinite);
    return values.length ? [Math.min(...values), Math.max(...values)] : [0, 1];
  };
  const xb = axisBounds(x),
    yb = axisBounds(y),
    cb = colorAxis ? colorBounds(colorAxis) : [0, 1];
  const normalized = (number: number, range: number[]) =>
    range[0] === range[1] ? 0.5 : (number - range[0]) / (range[1] - range[0]);
  return (
    <div className="objective-scatter">
      <div className="objective-shortcuts">
        {(
          [
            ["x", "Horizontal axis"],
            ["y", "Vertical axis"],
            ...(axes.length > 2 ? [["color", "Color represents"]] : []),
          ] as [Slot, string][]
        ).map(([slot, label]) => (
          <label key={slot}>
            {label}
            <select
              value={
                slot === "x"
                  ? x.id
                  : slot === "y"
                    ? y.id
                    : (colorAxis?.id ?? "")
              }
              onChange={(event) => update(slot, event.target.value)}
            >
              {slot === "color" && <option value="">None</option>}
              {axes.map((axis) => (
                <option value={axis.id} key={axis.id}>
                  {axis.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <svg
        className="objective-scatter-plot"
        viewBox="0 0 620 320"
        role="group"
        aria-label={`${x.label} vs ${y.label}${colorAxis ? `, colored by ${colorAxis.label}` : ""}`}
      >
        {[0, 0.5, 1].map((t) => (
          <g key={t} className="objective-scatter-grid">
            <line x1={90 + t * 490} x2={90 + t * 490} y1="25" y2="250" />
            <line x1="90" x2="580" y1={250 - t * 225} y2={250 - t * 225} />
            <text x={90 + t * 490} y="275" textAnchor="middle">
              {format(xb[0] + t * (xb[1] - xb[0]), x)}
            </text>
            <text x="80" y={254 - t * 225} textAnchor="end">
              {format(yb[0] + t * (yb[1] - yb[0]), y)}
            </text>
          </g>
        ))}
        <text x="335" y="307" textAnchor="middle">
          {x.label} →
        </text>
        <text x="17" y="137" transform="rotate(-90 17 137)" textAnchor="middle">
          {y.label} →
        </text>
        {[...plotted]
          .sort(
            (a, b) => Number(a.id === selectedId) - Number(b.id === selectedId),
          )
          .map((point) => {
            const selected = point.id === selectedId;
            const details = axes
              .map(
                (axis) =>
                  `${axis.label}: ${format(value(point, axis.id), axis)}`,
              )
              .join("; ");
            return (
              <circle
                key={point.id}
                cx={90 + normalized(value(point, x.id), xb) * 490}
                cy={250 - normalized(value(point, y.id), yb) * 225}
                r={selected ? 7 : 4.5}
                fill={
                  colorAxis && Number.isFinite(value(point, colorAxis.id))
                    ? color(normalized(value(point, colorAxis.id), cb))
                    : "#7bd0ff"
                }
                stroke={selected ? "#fff" : "#10131a"}
                strokeWidth={selected ? 2.5 : 0.6}
                opacity={selected ? 1 : 0.8}
                role="button"
                tabIndex={disabled ? -1 : 0}
                aria-disabled={disabled}
                aria-pressed={selected}
                aria-label={`Select tradeoff ${point.id}, ${details}`}
                onClick={() => !disabled && onSelect(point.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    if (!disabled) onSelect(point.id);
                  }
                }}
              >
                <title>
                  {details}; Purchase cost:{" "}
                  {point.purchase_cost_gp.toLocaleString("en-US")} GP
                </title>
              </circle>
            );
          })}
      </svg>
      {colorAxis && plotted.length > 0 && (
        <div className="objective-scatter-legend">
          <span>{colorAxis.label}</span>
          <svg
            viewBox="0 0 260 48"
            role="img"
            aria-label={`${colorAxis.label} color scale: ${format(cb[0], colorAxis)} to ${format(cb[1], colorAxis)}`}
          >
            <defs>
              <linearGradient id={gradientId}>
                {[0, 0.25, 0.5, 0.75, 1].map((t) => (
                  <stop key={t} offset={`${t * 100}%`} stopColor={color(t)} />
                ))}
              </linearGradient>
            </defs>
            <rect
              x="4"
              y="2"
              width="252"
              height="12"
              rx="3"
              fill={`url(#${gradientId})`}
            />
            <text x="4" y="36">
              {format(cb[0], colorAxis)}
            </text>
            <text x="256" y="36" textAnchor="end">
              {format(cb[1], colorAxis)}
            </text>
          </svg>
        </div>
      )}
      {plotted.length > 0 && (
        <p className="objective-scatter-hint">
          Select a point to inspect its configuration. The selected point has a
          white outline.
        </p>
      )}
      {plotted.length < available.length && (
        <p className="objective-scatter-hint">
          Use the table below for configurations with a negative value on either
          axis.
        </p>
      )}
    </div>
  );
}
