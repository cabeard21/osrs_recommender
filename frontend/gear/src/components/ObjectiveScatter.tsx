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
  objective_values: Record<string, number | null>;
  purchase_cost_gp: number;
}
type Slot = "x" | "y" | "color";
type CostScale = "log" | "linear";
const runningCostId = "gp_per_damage";
const color = (value: number) =>
  `hsl(${205 - value * 165} 78% ${58 + value * 8}%)`;
const value = (point: Point, id: string): number =>
  id === "dps" ? point.score : (point.objective_values[id] ?? NaN);
const format = (number: number, axis: Axis) => {
  if (!Number.isFinite(number)) return "Unavailable";
  if (axis.unit === "probability") return `${(number * 100).toFixed(2)}%`;
  if (axis.unit === "GP") return `${number.toLocaleString()} GP`;
  if (axis.unit === "GP/damage") return `${number.toFixed(4)} GP/damage`;
  if (axis.unit === "percent") return `${number.toFixed(2)}%`;
  return number.toLocaleString("en-US", {
    minimumFractionDigits: axis.id === "dps" ? 3 : 0,
    maximumFractionDigits: axis.id === "dps" ? 3 : 2,
  });
};

function logarithmicTicks(max: number, logMax: number, gap: number) {
  const min = Math.max(Number.MIN_VALUE, Math.expm1(gap * logMax));
  const maxPower = Math.floor(Math.log10(max));
  const ticks = [0];
  let previous = 0;
  for (let power = Math.floor(Math.log10(min)); power <= maxPower; power++) {
    for (const multiplier of [1, 3]) {
      const tick = multiplier * 10 ** power;
      const fraction = Math.log1p(tick) / logMax;
      if (fraction - previous >= gap && 1 - fraction >= gap) {
        ticks.push(tick);
        previous = fraction;
      }
    }
  }
  const midpoint = Math.expm1(logMax / 2);
  if (ticks.length === 1 && midpoint > 0 && midpoint < max)
    ticks.push(midpoint);
  return [...ticks, max];
}

function plotScale(
  axis: Axis,
  maxValue: number,
  costScale: CostScale,
  tickGap = 0.1,
) {
  const isCost = axis.id === runningCostId;
  const logarithmic = isCost && costScale === "log";
  const max = isCost ? maxValue : maxValue || 1;
  const logMax = Math.log1p(max);
  const position = (value: number) => {
    if (max === 0) return 0;
    return logarithmic ? Math.log1p(value) / logMax : value / max;
  };
  const ticks =
    max === 0
      ? [0]
      : logarithmic
        ? logarithmicTicks(max, logMax, tickGap)
        : [0, max / 2, max].filter((tick, index) => index === 0 || tick > 0);
  const label = isCost
    ? `${axis.label} (GP/damage${logarithmic ? ", log scale" : ""})`
    : axis.label;
  const tickLabel = (tick: number) => {
    if (!isCost) return format(tick, axis);
    return tick.toLocaleString("en-US", {
      maximumSignificantDigits: 3,
      notation:
        tick > 0 && (tick < 0.001 || tick >= 1000) ? "scientific" : "standard",
    });
  };
  return { label, position, ticks, tickLabel };
}

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
  const [costScale, setCostScale] = useState<CostScale>("log");
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
  const scaleFor = (axis: Axis) =>
    plotScale(
      axis,
      Math.max(0, ...plotted.map((point) => value(point, axis.id))),
      costScale,
    );
  const xs = scaleFor(x);
  const ys = scaleFor(y);
  const plotX = (number: number) => 90 + xs.position(number) * 490;
  const plotY = (number: number) => 250 - ys.position(number) * 225;
  const colorValues = colorAxis
    ? plotted.map((point) => value(point, colorAxis.id)).filter(Number.isFinite)
    : [];
  const [colorMin, colorMax] = colorValues.length
    ? [Math.min(...colorValues), Math.max(...colorValues)]
    : [0, 1];
  const costColor =
    colorAxis?.id === runningCostId
      ? plotScale(colorAxis, colorMax, costScale, 0.2)
      : undefined;
  const colorLabel = costColor?.label ?? colorAxis?.label;
  const colorPosition =
    costColor?.position ??
    ((number: number) =>
      colorMin === colorMax
        ? 0.5
        : (number - colorMin) / (colorMax - colorMin));
  const legendWidth = costColor ? 380 : 260;
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
        {(x.id === runningCostId || y.id === runningCostId || costColor) && (
          <label>
            Running cost scale
            <select
              value={costScale}
              onChange={(event) =>
                setCostScale(event.target.value === "linear" ? "linear" : "log")
              }
            >
              <option value="log">Logarithmic</option>
              <option value="linear">Linear</option>
            </select>
          </label>
        )}
      </div>
      <svg
        className="objective-scatter-plot"
        viewBox="0 0 620 320"
        role="group"
        aria-label={`${xs.label} vs ${ys.label}${colorAxis ? `, colored by ${colorAxis.label}` : ""}`}
      >
        {xs.ticks.map((tick) => (
          <g key={tick} className="objective-scatter-grid">
            <line x1={plotX(tick)} x2={plotX(tick)} y1="25" y2="250" />
            <text x={plotX(tick)} y="275" textAnchor="middle">
              {xs.tickLabel(tick)}
            </text>
          </g>
        ))}
        {ys.ticks.map((tick) => (
          <g key={tick} className="objective-scatter-grid">
            <line x1="90" x2="580" y1={plotY(tick)} y2={plotY(tick)} />
            <text x="80" y={plotY(tick) + 4} textAnchor="end">
              {ys.tickLabel(tick)}
            </text>
          </g>
        ))}
        <text x="335" y="307" textAnchor="middle">
          {xs.label} →
        </text>
        <text x="17" y="137" transform="rotate(-90 17 137)" textAnchor="middle">
          {ys.label} →
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
                cx={plotX(value(point, x.id))}
                cy={plotY(value(point, y.id))}
                r={selected ? 7 : 4.5}
                fill={
                  colorAxis && Number.isFinite(value(point, colorAxis.id))
                    ? color(colorPosition(value(point, colorAxis.id)))
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
        <div
          className={`objective-scatter-legend${costColor ? " objective-scatter-legend-cost" : ""}`}
        >
          <span>{colorLabel}</span>
          {costColor && !colorValues.length ? (
            <span>Unavailable</span>
          ) : (
            <svg
              viewBox={`0 0 ${legendWidth} 48`}
              role="img"
              aria-label={`${colorLabel} color scale: ${format(costColor ? 0 : colorMin, colorAxis)} to ${format(colorMax, colorAxis)}`}
            >
              <defs>
                <linearGradient id={gradientId}>
                  {[0, 0.25, 0.5, 0.75, 1].map((t) => (
                    <stop
                      key={t}
                      offset={`${t * 100}%`}
                      stopColor={color(costColor && colorMax === 0 ? 0 : t)}
                    />
                  ))}
                </linearGradient>
              </defs>
              <rect
                x="4"
                y="2"
                width={legendWidth - 8}
                height="12"
                rx="3"
                fill={`url(#${gradientId})`}
              />
              {costColor ? (
                costColor.ticks.map((tick) => (
                  <text
                    key={tick}
                    x={4 + colorPosition(tick) * (legendWidth - 8)}
                    y="36"
                    textAnchor={
                      tick === 0
                        ? "start"
                        : tick === colorMax
                          ? "end"
                          : "middle"
                    }
                  >
                    {costColor.tickLabel(tick)}
                  </text>
                ))
              ) : (
                <>
                  <text x="4" y="36">
                    {format(colorMin, colorAxis)}
                  </text>
                  <text x="256" y="36" textAnchor="end">
                    {format(colorMax, colorAxis)}
                  </text>
                </>
              )}
            </svg>
          )}
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
