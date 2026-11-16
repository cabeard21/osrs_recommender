import { useRef, useState } from "react";
import {
  formatMetric,
  metricBounds,
  metricValue,
  METRICS,
  normalizeMetric,
  project3d,
  type LabPoint,
  type LabMetric,
} from "./model";

type Props = {
  points: LabPoint[];
  selectedId: string;
  onSelect: (id: string) => void;
  metrics?: LabMetric[];
};
type Vertex = { x: number; y: number; z: number };
const INITIAL_CAMERA = { yaw: 35, pitch: 25, zoom: 1 };
const AXIS_ENDS: Vertex[] = [
  { x: 1, y: -1, z: -1 },
  { x: -1, y: 1, z: -1 },
  { x: -1, y: -1, z: 1 },
];
const VERTICES: Vertex[] = [-1, 1].flatMap((x) =>
  [-1, 1].flatMap((y) => [-1, 1].map((z) => ({ x, y, z }))),
);
const EDGES = VERTICES.flatMap((from, index) =>
  VERTICES.slice(index + 1)
    .filter(
      (to) =>
        [from.x !== to.x, from.y !== to.y, from.z !== to.z].filter(Boolean)
          .length === 1,
    )
    .map((to) => ({ from, to })),
);
const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

export function SpatialChart({
  points,
  selectedId,
  onSelect,
  metrics = METRICS,
}: Props) {
  const [camera, setCamera] = useState(INITIAL_CAMERA);
  const drag = useRef<{
    x: number;
    y: number;
    yaw: number;
    pitch: number;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  const axes = metrics
    .slice(0, 3)
    .map((metric, i) => ({ ...metric, end: AXIS_ENDS[i] }));
  const bounds = axes.map((metric) => metricBounds(points, metric.key));
  const project = (vertex: Vertex) => {
    const projected = project3d(vertex, camera.yaw, camera.pitch);
    return {
      x: 300 + projected.x * 80 * camera.zoom,
      y: 175 - projected.y * 80 * camera.zoom,
      depth: projected.depth,
    };
  };
  const origin = project({ x: -1, y: -1, z: -1 });
  const plotted = (axes.length === 3 ? points : [])
    .map((point) => ({
      point,
      ...project({
        x: normalizeMetric(metricValue(point, axes[0].key), bounds[0]) * 2 - 1,
        y: normalizeMetric(metricValue(point, axes[1].key), bounds[1]) * 2 - 1,
        z: normalizeMetric(metricValue(point, axes[2].key), bounds[2]) * 2 - 1,
      }),
    }))
    .sort((a, b) => a.depth - b.depth);
  const zoom = (change: number) =>
    setCamera((previous) => ({
      ...previous,
      zoom: clamp(Math.round((previous.zoom + change) * 10) / 10, 0.6, 1.3),
    }));

  if (axes.length < 3)
    return (
      <p className="lab-note">
        A 3D view requires three objectives. This result has fewer than three.
      </p>
    );
  return (
    <div className="lab-spatial">
      <p className="lab-note">
        Drag to rotate. Select a point to inspect the same loadout in every
        view. Rotation controls also work with a keyboard.
      </p>
      <svg
        className="lab-chart"
        viewBox="0 0 600 350"
        role="group"
        aria-label="Interactive 3D tradeoff chart"
        style={{ touchAction: "none", cursor: "grab" }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          suppressClick.current = false;
          drag.current = {
            x: event.clientX,
            y: event.clientY,
            yaw: camera.yaw,
            pitch: camera.pitch,
            moved: false,
          };
        }}
        onPointerMove={(event) => {
          const start = drag.current;
          if (!start) return;
          const dx = event.clientX - start.x;
          const dy = event.clientY - start.y;
          if (Math.hypot(dx, dy) < 4 && !start.moved) return;
          // Capturing on pointer-down would retarget ordinary point clicks to
          // the SVG. Capture only once the gesture has become a camera drag.
          if (!start.moved)
            event.currentTarget.setPointerCapture?.(event.pointerId);
          drag.current = { ...start, moved: true };
          setCamera((previous) => ({
            ...previous,
            yaw: ((((start.yaw + dx * 0.5 + 180) % 360) + 360) % 360) - 180,
            pitch: clamp(start.pitch + dy * 0.5, -80, 80),
          }));
        }}
        onPointerUp={() => {
          suppressClick.current = drag.current?.moved ?? false;
          drag.current = null;
        }}
        onPointerCancel={() => {
          suppressClick.current = true;
          drag.current = null;
        }}
      >
        {EDGES.map(({ from, to }, index) => {
          const a = project(from),
            b = project(to);
          return (
            <line
              key={index}
              className="lab-grid"
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#394456"
              opacity={0.6}
            />
          );
        })}
        {axes.map((axis) => {
          const end = project(axis.end);
          return (
            <g key={axis.key} className="lab-axis">
              <line
                x1={origin.x}
                y1={origin.y}
                x2={end.x}
                y2={end.y}
                stroke="#a6b3c7"
                strokeWidth={1.5}
              />
              <text
                x={clamp(end.x, 55, 545)}
                y={clamp(end.y + 17, 18, 340)}
                textAnchor="middle"
                fill="#e0e2ec"
                fontSize={12}
                stroke="#10131a"
                strokeWidth={4}
                paintOrder="stroke"
              >
                {axis.shortLabel}
              </text>
            </g>
          );
        })}
        {plotted.map(({ point, x, y }) => {
          const selected = point.id === selectedId;
          return (
            <circle
              key={point.id}
              className="lab-point"
              cx={x}
              cy={y}
              r={selected ? 7 : 4.5}
              fill={selected ? "#f0bf5c" : "#7bd0ff"}
              fillOpacity={selected ? 1 : 0.7}
              stroke={selected ? "#fff5db" : "#10131a"}
              strokeWidth={selected ? 2 : 0.8}
              role="button"
              tabIndex={0}
              aria-label={`3D select ${point.label}`}
              aria-pressed={selected}
              onClick={() => {
                if (!suppressClick.current) onSelect(point.id);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(point.id);
                }
              }}
            >
              <title>
                {`${point.label}: ${axes.map((axis) => `${formatMetric(axis.key, metricValue(point, axis.key), axis)} ${axis.shortLabel}`).join("; ")}; ${point.costGp.toLocaleString("en-US")} GP`}
              </title>
            </circle>
          );
        })}
      </svg>
      <div className="lab-controls lab-spatial-ranges">
        {axes.map((axis, i) => (
          <span key={axis.key}>
            {axis.shortLabel}: {formatMetric(axis.key, bounds[i][0], axis)}–
            {formatMetric(axis.key, bounds[i][1], axis)}
          </span>
        ))}
      </div>
      <div className="lab-controls">
        <label>
          Rotation {Math.round(camera.yaw)}°
          <input
            aria-label="3D rotation"
            type="range"
            min={-180}
            max={180}
            value={camera.yaw}
            onChange={(event) =>
              setCamera((previous) => ({
                ...previous,
                yaw: Number(event.target.value),
              }))
            }
          />
        </label>
        <label>
          Tilt {Math.round(camera.pitch)}°
          <input
            aria-label="3D tilt"
            type="range"
            min={-80}
            max={80}
            value={camera.pitch}
            onChange={(event) =>
              setCamera((previous) => ({
                ...previous,
                pitch: Number(event.target.value),
              }))
            }
          />
        </label>
        <button
          type="button"
          onClick={() => zoom(-0.1)}
          disabled={camera.zoom <= 0.6}
        >
          Zoom out
        </button>
        <output aria-label="3D zoom">{Math.round(camera.zoom * 100)}%</output>
        <button
          type="button"
          onClick={() => zoom(0.1)}
          disabled={camera.zoom >= 1.3}
        >
          Zoom in
        </button>
        <button type="button" onClick={() => setCamera(INITIAL_CAMERA)}>
          Reset camera
        </button>
      </div>
    </div>
  );
}
