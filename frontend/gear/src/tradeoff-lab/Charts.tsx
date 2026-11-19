import { useId, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  METRICS,
  formatMetric,
  metricBounds,
  metricValue,
  normalizeMetric,
} from "./model";
import type { LabMetric, LabPoint, MetricKey } from "./model";

export interface ChartProps {
  points: LabPoint[];
  selectedId: string;
  onSelect: (id: string) => void;
  metrics?: LabMetric[];
}

const label = (key: MetricKey, metrics: LabMetric[]) =>
  metrics.find((m) => m.key === key)!.shortLabel;
const color = (value: number) =>
  `hsl(${205 - value * 165} 78% ${58 + value * 8}%)`;
const activate = (event: KeyboardEvent<SVGElement>, select: () => void) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    select();
  }
};
export const pointDescription = (
  point: LabPoint,
  metrics: LabMetric[] = METRICS,
) =>
  `${point.label}: ${metrics.map((m) => `${formatMetric(m.key, metricValue(point, m.key), m)} ${m.shortLabel}`).join(" / ")} / ${point.costGp.toLocaleString()} GP`;

function Scatter({
  points,
  selectedId,
  onSelect,
  x,
  y,
  colorBy,
  prefix,
  metrics = METRICS,
}: ChartProps & {
  x: MetricKey;
  y: MetricKey;
  colorBy?: MetricKey;
  prefix: string;
}) {
  const definition = (key: string) => metrics.find((m) => m.key === key);
  const xb = metricBounds(points, x),
    yb = metricBounds(points, y);
  const cb = colorBy
    ? metricBounds(points, colorBy)
    : ([0, 1] as [number, number]);
  const sorted = points
    .filter((p) =>
      [x, y, ...(colorBy ? [colorBy] : [])].every((key) =>
        Number.isFinite(metricValue(p, key)),
      ),
    )
    .sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId));
  const ticks = [0, 0.5, 1];
  return (
    <svg
      className="lab-chart"
      viewBox="0 0 500 285"
      role="group"
      aria-label={`${label(x, metrics)} vs ${label(y, metrics)}${colorBy ? `, colored by ${label(colorBy, metrics)}` : ""}`}
    >
      {ticks.map((t) => (
        <g key={t} className="lab-grid">
          <line x1={74 + t * 398} x2={74 + t * 398} y1="24" y2="225" />
          <line x1="74" x2="472" y1={225 - t * 201} y2={225 - t * 201} />
          <text x={74 + t * 398} y="246" textAnchor="middle">
            {formatMetric(x, xb[0] + t * (xb[1] - xb[0]), definition(x))}
          </text>
          <text x="64" y={229 - t * 201} textAnchor="end">
            {formatMetric(y, yb[0] + t * (yb[1] - yb[0]), definition(y))}
          </text>
        </g>
      ))}
      <text x="273" y="276" textAnchor="middle" className="lab-axis">
        {label(x, metrics)} →
      </text>
      <text
        x="15"
        y="125"
        transform="rotate(-90 15 125)"
        textAnchor="middle"
        className="lab-axis"
      >
        {label(y, metrics)} →
      </text>
      {sorted.map((point) => {
        const selected = selectedId === point.id;
        return (
          <circle
            key={point.id}
            className="lab-point"
            cx={74 + normalizeMetric(metricValue(point, x), xb) * 398}
            cy={225 - normalizeMetric(metricValue(point, y), yb) * 201}
            r={selected ? 7 : 4}
            fill={
              colorBy
                ? color(normalizeMetric(metricValue(point, colorBy), cb))
                : selected
                  ? "#f0bf5c"
                  : "#7bd0ff"
            }
            stroke={selected ? "#fff" : "transparent"}
            strokeWidth={selected ? 2 : 0}
            opacity={selected ? 1 : 0.7}
            role="button"
            tabIndex={0}
            aria-label={`${prefix} select ${point.label}`}
            aria-pressed={selected}
            onClick={() => onSelect(point.id)}
            onKeyDown={(e) => activate(e, () => onSelect(point.id))}
          >
            <title>{pointDescription(point, metrics)}</title>
          </circle>
        );
      })}
    </svg>
  );
}

export function PairwiseCharts(props: ChartProps) {
  const metrics = props.metrics ?? METRICS;
  const pairs = metrics.flatMap((x, i) =>
    metrics.slice(i + 1).map((y) => [x.key, y.key]),
  );
  if (!pairs.length)
    return <p className="lab-note">A pairwise view requires two objectives.</p>;
  return (
    <div className="lab-pairs">
      {pairs.map(([x, y]) => (
        <figure key={x + y}>
          <figcaption>
            {label(x, metrics)} <span>vs</span> {label(y, metrics)}
          </figcaption>
          <Scatter
            {...props}
            x={x}
            y={y}
            prefix={`${label(x, metrics)} vs ${label(y, metrics)}`}
          />
        </figure>
      ))}
    </div>
  );
}

export function ColorScatter(props: ChartProps) {
  const metrics = props.metrics ?? METRICS;
  const [requestedColor, setColorBy] = useState<MetricKey>(
    metrics[2]?.key ?? "",
  );
  const colorBy =
    metrics.length >= 3
      ? metrics.some((m) => m.key === requestedColor)
        ? requestedColor
        : metrics[2].key
      : undefined;
  const definition = metrics.find((m) => m.key === colorBy);
  const gradientId = useId().replaceAll(":", "");
  const [x, y] = metrics.filter((m) => m.key !== colorBy).map((m) => m.key);
  const bounds = metricBounds(props.points, colorBy ?? "dps");
  if (!x || !y)
    return <p className="lab-note">A scatter plot requires two objectives.</p>;
  return (
    <div className="lab-color-layout">
      <Scatter {...props} x={x} y={y} colorBy={colorBy} prefix="Color" />
      {colorBy && (
        <div className="lab-color-key">
          <label>
            Color represents
            <select
              value={colorBy}
              onChange={(e) => setColorBy(e.target.value as MetricKey)}
            >
              {metrics.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.shortLabel}
                </option>
              ))}
            </select>
          </label>
          <svg
            viewBox="0 0 240 48"
            role="img"
            aria-label={`${label(colorBy, metrics)} color scale: ${bounds.map((b) => formatMetric(colorBy, b, definition)).join(" to ")}`}
          >
            <defs>
              <linearGradient id={gradientId}>
                {[0, 0.25, 0.5, 0.75, 1].map((t) => (
                  <stop key={t} offset={`${t * 100}%`} stopColor={color(t)} />
                ))}
              </linearGradient>
            </defs>
            <rect
              x="3"
              y="2"
              width="234"
              height="12"
              rx="3"
              fill={`url(#${gradientId})`}
            />
            <text x="3" y="36" className="lab-axis">
              {formatMetric(colorBy, bounds[0], definition)}
            </text>
            <text x="237" y="36" textAnchor="end" className="lab-axis">
              {formatMetric(colorBy, bounds[1], definition)}
            </text>
          </svg>
          <p>
            Axes automatically use the other two objectives. Tap a point to read
            its exact values.
          </p>
        </div>
      )}
    </div>
  );
}

export function ParallelChart({
  points,
  selectedId,
  onSelect,
  metrics = METRICS,
}: ChartProps) {
  const bounds = metrics.map((m) => metricBounds(points, m.key));
  const path = (point: LabPoint) =>
    metrics
      .map(
        (m, i) =>
          `${i ? "L" : "M"}${100 + i * (500 / Math.max(1, metrics.length - 1))},${255 - normalizeMetric(metricValue(point, m.key), bounds[i]) * 207}`,
      )
      .join(" ");
  return (
    <>
      <svg
        className="lab-chart"
        viewBox="0 0 700 300"
        role="group"
        aria-label={`${metrics.length} objective parallel coordinates`}
      >
        {metrics.map((m, i) => (
          <g key={m.key} className="lab-grid">
            <line
              x1={100 + i * (500 / Math.max(1, metrics.length - 1))}
              x2={100 + i * (500 / Math.max(1, metrics.length - 1))}
              y1="48"
              y2="255"
            />
            <text
              x={100 + i * (500 / Math.max(1, metrics.length - 1))}
              y="20"
              textAnchor="middle"
              className="lab-axis"
            >
              {m.shortLabel}
            </text>
            {[0, 0.5, 1].map((t) => (
              <text
                key={t}
                x={88 + i * (500 / Math.max(1, metrics.length - 1))}
                y={259 - t * 207}
                textAnchor="end"
              >
                {formatMetric(
                  m.key,
                  bounds[i][0] + t * (bounds[i][1] - bounds[i][0]),
                  m,
                )}
              </text>
            ))}
          </g>
        ))}
        {points
          .filter((p) =>
            metrics.every((m) => Number.isFinite(metricValue(p, m.key))),
          )
          .sort(
            (a, b) => Number(a.id === selectedId) - Number(b.id === selectedId),
          )
          .map((point) => (
            <path
              key={point.id}
              d={path(point)}
              fill="none"
              stroke={point.id === selectedId ? "#f0bf5c" : "#7bd0ff"}
              strokeWidth={point.id === selectedId ? 3.5 : 1.5}
              opacity={point.id === selectedId ? 1 : 0.16}
              className="lab-point lab-parallel-line"
              role="button"
              tabIndex={0}
              aria-pressed={point.id === selectedId}
              aria-label={`Parallel select ${point.label}`}
              onClick={() => onSelect(point.id)}
              onKeyDown={(e) => activate(e, () => onSelect(point.id))}
            >
              <title>{pointDescription(point, metrics)}</title>
            </path>
          ))}
      </svg>
      <p className="lab-note">
        Each line is one loadout. Each axis uses its own observed range.
        {metrics.some((m) => m.key === "gp_per_damage") &&
          " Lower GP/damage is more efficient."}
      </p>
    </>
  );
}
