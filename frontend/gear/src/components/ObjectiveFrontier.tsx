import { useEffect, useMemo, useRef, useState } from "react";
import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";
import {
  canonicalObjectives,
  objectiveValues,
  type ObjectiveDefinition,
} from "../api/objectives";

interface Point {
  id: string;
  score: number;
  objective_values: Record<string, number>;
  purchase_cost_gp: number;
  maximum_actions: number;
}
interface Page {
  points: Point[];
  total: number;
  next_cursor: string | null;
}
function format(value: number | undefined, definition?: ObjectiveDefinition) {
  if (value === undefined || !Number.isFinite(value)) return "Unavailable";
  if (definition?.unit === "probability") return (value * 100).toFixed(2) + "%";
  if (definition?.unit === "percent") return value.toFixed(2) + "%";
  if (definition?.unit === "roll") return (value / 1000).toFixed(2) + "k";
  return value.toFixed(3);
}
async function get(path: string, signal?: AbortSignal) {
  const response = await fetch("/ui-api/gear/optimization-runs/" + path, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (response.status === 410)
    throw new Error(
      "This optimization session has expired. Run optimization again to browse its tradeoffs.",
    );
  if (!response.ok)
    throw new Error(
      "Unable to load objective results (" + response.status + ").",
    );
  return response.json();
}
export function ObjectiveFrontier({
  result,
  swapLimit,
  selectedId,
  onSelect,
}: {
  result: OptimizationReply;
  swapLimit: number | null;
  selectedId: string;
  onSelect: (id: string, raw: JointSolutionDTO) => void;
}) {
  const definitions = result.live?.result.objective_definitions ?? [];
  const group = result.live?.result.objective_frontiers?.find(
    (g) => g.swap_limit === swapLimit,
  );
  const runId = result.live?.run_id ?? result.live?.result.run_id;
  const groupId = group?.id ?? group?.group_id;
  const selectionVersion = useRef(0);
  useEffect(() => {
    selectionVersion.current += 1;
  }, [result, groupId]);
  const [x, setX] = useState("dps"),
    [y, setY] = useState(definitions[0]?.id ?? "dps");
  const [sort, setSort] = useState("dps"),
    [direction, setDirection] = useState("desc");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const [page, setPage] = useState<Page | null>(null),
    [error, setError] = useState("");
  const [loading, setLoading] = useState(false),
    [selecting, setSelecting] = useState(false);
  const samples = useMemo(
    () =>
      (group?.points ?? []).map((p) => ({
        id: p.id,
        score: p.solution.score,
        objective_values: p.solution.objective_values ?? {},
        purchase_cost_gp: p.solution.purchase_cost_gp,
        maximum_actions: p.solution.maximum_actions,
      })),
    [group],
  );
  useEffect(() => {
    setCursors([null]);
    setPage(null);
  }, [runId, groupId, sort, direction]);
  useEffect(() => {
    if (!runId || !groupId) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const query = new URLSearchParams({ sort, direction, limit: "50" });
    if (cursor) query.set("cursor", cursor);
    get(
      encodeURIComponent(runId) +
        "/frontiers/" +
        encodeURIComponent(groupId) +
        "/points?" +
        query,
      controller.signal,
    )
      .then((data: Page) => {
        if (
          !Array.isArray(data.points) ||
          !Number.isSafeInteger(data.total) ||
          data.total < 0 ||
          (data.next_cursor !== null && typeof data.next_cursor !== "string")
        )
          throw new Error("Invalid objective result page.");
        for (const point of data.points) {
          if (typeof point.id !== "string" || !Number.isFinite(point.score))
            throw new Error("Invalid objective result point.");
          objectiveValues(
            point.objective_values,
            canonicalObjectives(result.scenario.request.objectives ?? []),
          );
        }
        if (!controller.signal.aborted) setPage(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId, groupId, sort, direction, cursor, result]);
  const choose = async (id: string) => {
    const version = ++selectionVersion.current;
    setSelecting(true);
    setError("");
    try {
      const existing = group?.points.find((point) => point.id === id);
      const raw =
        existing?.solution ??
        (
          await get(
            encodeURIComponent(runId!) + "/solutions/" + encodeURIComponent(id),
          )
        ).solution;
      objectiveValues(
        raw.objective_values,
        canonicalObjectives(result.scenario.request.objectives ?? []),
      );
      if (version === selectionVersion.current) onSelect(id, raw);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSelecting(false);
    }
  };
  if (!group || result.scenario.request.objectives === undefined) return null;
  const rows = page?.points ?? samples;
  const axes = [{ id: "dps", label: "DPS" }, ...definitions];
  const selected = result.solutions.find(
    (solution) => solution.id === selectedId,
  )?.live;
  const displayed =
    samples.some((p) => p.id === selectedId) || !selected
      ? samples
      : [
          ...samples,
          {
            id: selectedId,
            score: selected.score,
            objective_values: selected.objective_values ?? {},
            purchase_cost_gp: selected.purchase_cost_gp,
            maximum_actions: selected.maximum_actions,
          },
        ];
  const value = (point: Point, id: string) =>
    id === "dps" ? point.score : point.objective_values[id];
  const activeX = axes.some((a) => a.id === x) ? x : "dps";
  const activeY = axes.some((a) => a.id === y)
    ? y
    : (definitions[0]?.id ?? "dps");
  const bounds = (id: string) => {
    const values = displayed.map((p) => value(p, id)).filter(Number.isFinite);
    return [Math.min(...values), Math.max(...values)];
  };
  const [xmin, xmax] = bounds(activeX),
    [ymin, ymax] = bounds(activeY);
  const coordinate = (v: number, low: number, high: number) =>
    high === low ? 0.5 : (v - low) / (high - low);
  const xDefinition = definitions.find((d) => d.id === activeX),
    yDefinition = definitions.find((d) => d.id === activeY);
  return (
    <section className="panel" aria-label="Objective tradeoffs">
      <h2>Best-found objective tradeoffs</h2>
      <p>
        {page?.total ?? group.total_count ?? samples.length} distinct tradeoffs.
        All objectives are maximized together; each row is one complete
        configuration.
      </p>
      <div className="objective-shortcuts" aria-label="Objective endpoints">
        {axes.map((axis) => {
          const best = samples.reduce<Point | undefined>(
            (previous, point) =>
              !previous || value(point, axis.id) > value(previous, axis.id)
                ? point
                : previous,
            undefined,
          );
          return (
            best && (
              <button
                key={axis.id}
                type="button"
                disabled={selecting}
                onClick={() => void choose(best.id)}
              >
                Highest {axis.label}
              </button>
            )
          );
        })}
      </div>
      {definitions.length > 0 && (
        <>
          <div className="objective-shortcuts">
            <label>
              Horizontal axis
              <select value={activeX} onChange={(e) => setX(e.target.value)}>
                {axes.map((axis) => (
                  <option key={axis.id} value={axis.id}>
                    {axis.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Vertical axis
              <select value={activeY} onChange={(e) => setY(e.target.value)}>
                {axes.map((axis) => (
                  <option key={axis.id} value={axis.id}>
                    {axis.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p>
            Chart shows {samples.length} representative points
            {group.sampled ? " from the full table" : ""}. A point can appear
            worse on these axes while improving another objective.
          </p>
          <svg
            viewBox="0 0 520 240"
            role="img"
            aria-label="Selected objective projection"
            style={{ width: "100%", maxWidth: 800 }}
          >
            <line x1="65" x2="495" y1="195" y2="195" stroke="currentColor" />
            <line x1="65" x2="65" y1="20" y2="195" stroke="currentColor" />
            <text x="65" y="217" fill="currentColor" fontSize="11">
              {format(xmin, xDefinition)}
            </text>
            <text
              x="495"
              y="217"
              textAnchor="end"
              fill="currentColor"
              fontSize="11"
            >
              {format(xmax, xDefinition)}
            </text>
            <text
              x="58"
              y="195"
              textAnchor="end"
              fill="currentColor"
              fontSize="11"
            >
              {format(ymin, yDefinition)}
            </text>
            <text
              x="58"
              y="30"
              textAnchor="end"
              fill="currentColor"
              fontSize="11"
            >
              {format(ymax, yDefinition)}
            </text>
            {displayed.map((point) => (
              <circle
                key={point.id}
                cx={65 + coordinate(value(point, activeX), xmin, xmax) * 430}
                cy={195 - coordinate(value(point, activeY), ymin, ymax) * 175}
                r={point.id === selectedId ? 6 : 4}
                fill="currentColor"
                opacity={point.id === selectedId ? 1 : 0.55}
                role="button"
                tabIndex={0}
                aria-label={
                  "Select tradeoff " +
                  point.id +
                  ", " +
                  format(value(point, activeX), xDefinition) +
                  " by " +
                  format(value(point, activeY), yDefinition)
                }
                onClick={() => void choose(point.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    void choose(point.id);
                  }
                }}
              />
            ))}
          </svg>
        </>
      )}
      <div className="objective-shortcuts">
        <label>
          Sort tradeoffs
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {axes.map((axis) => (
              <option key={axis.id} value={axis.id}>
                {axis.label}
              </option>
            ))}
            <option value="purchase_cost_gp">Purchase cost</option>
            <option value="maximum_actions">Maximum actions</option>
          </select>
        </label>
        <label>
          Sort direction
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
          >
            <option value="desc">Highest first</option>
            <option value="asc">Lowest first</option>
          </select>
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      <div style={{ overflowX: "auto" }}>
        <table aria-label="All objective tradeoffs" aria-busy={loading}>
          <thead>
            <tr>
              <th>Configuration</th>
              <th>DPS</th>
              {definitions.map((def) => (
                <th key={def.id}>
                  {def.label}
                  {def.unit === "roll"
                    ? " (roll)"
                    : def.unit === "probability"
                      ? " (%)"
                      : def.kind === "magic_damage_bonus"
                        ? " (%)"
                        : ""}
                </th>
              ))}
              <th>Cost (GP)</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((point, index) => (
              <tr key={point.id} aria-selected={selectedId === point.id}>
                <td>
                  <button
                    type="button"
                    disabled={selecting}
                    aria-pressed={selectedId === point.id}
                    onClick={() => void choose(point.id)}
                  >
                    Select setup {(cursors.length - 1) * 50 + index + 1}
                  </button>
                </td>
                <td>{format(point.score)}</td>
                {definitions.map((def) => (
                  <td key={def.id}>
                    {format(point.objective_values[def.id], def)}
                  </td>
                ))}
                <td>{point.purchase_cost_gp.toLocaleString()}</td>
                <td>{point.maximum_actions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {runId && (
        <div className="objective-shortcuts">
          <button
            type="button"
            disabled={loading || cursors.length < 2}
            onClick={() => setCursors(cursors.slice(0, -1))}
          >
            Previous page
          </button>
          <span aria-live="polite">Page {cursors.length}</span>
          <button
            type="button"
            disabled={loading || !page?.next_cursor}
            onClick={() =>
              page?.next_cursor && setCursors([...cursors, page.next_cursor])
            }
          >
            Next page
          </button>
        </div>
      )}
    </section>
  );
}
