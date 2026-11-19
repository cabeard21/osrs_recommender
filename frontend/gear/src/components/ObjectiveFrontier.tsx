import { useEffect, useMemo, useRef, useState } from "react";
import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";
import { ObjectiveScatter } from "./ObjectiveScatter";
import { useRetainedObjectivePoints } from "./useRetainedObjectivePoints";
import {
  parseWildernessRisk,
  riskWithinBudget,
  wildernessRiskCap,
} from "../api/wilderness";
import {
  createLabSnapshot,
  selectedLabSolution,
  storeLabSnapshot,
} from "../tradeoff-lab/snapshot";
import {
  canonicalObjectives,
  objectiveValues,
  type ObjectiveDefinition,
} from "../api/objectives";

interface Point {
  id: string;
  score: number;
  objective_values: Record<string, number | null>;
  purchase_cost_gp: number;
  wilderness_loss_gp?: number | null;
  maximum_actions: number;
}
interface Page {
  points: Point[];
  total: number;
  next_cursor: string | null;
}
function format(
  value: number | null | undefined,
  definition?: ObjectiveDefinition,
) {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  if (definition?.unit === "probability") return (value * 100).toFixed(2) + "%";
  if (definition?.unit === "GP") return value.toLocaleString();
  if (definition?.unit === "percent") return value.toFixed(2) + "%";
  if (definition?.unit === "roll") return (value / 1000).toFixed(2) + "k";
  if (definition?.unit === "GP/damage") return value.toFixed(4);
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
  const lossCap = wildernessRiskCap(result.scenario.request);
  const wilderness = lossCap !== undefined;
  const separateRisk =
    wilderness && !definitions.some((d) => d.kind === "wilderness_loss_gp");
  const group = result.live?.result.objective_frontiers?.find(
    (g) => g.swap_limit === swapLimit,
  );
  const runId = result.live?.run_id ?? result.live?.result.run_id;
  const groupId = group?.id ?? group?.group_id;
  const selectionVersion = useRef(0);
  useEffect(() => {
    selectionVersion.current += 1;
  }, [result, groupId]);
  const [preferredSort, setSort] = useState("dps"),
    [direction, setDirection] = useState("desc");
  const sort =
    !wilderness && preferredSort === "wilderness_loss_gp"
      ? "dps"
      : preferredSort;
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
        wilderness_loss_gp: p.solution.wilderness_risk?.loss_gp,
        maximum_actions: p.solution.maximum_actions,
      })),
    [group],
  );
  const axes = [{ id: "dps", label: "DPS" }, ...definitions];
  const scope = JSON.stringify([
    runId,
    groupId,
    swapLimit,
    axes.map((axis) => axis.id),
  ]);
  const selected =
    selectedLabSolution(result, selectedId) ??
    group?.points.find((point) => point.id === selectedId)?.solution;
  const retained = useRetainedObjectivePoints<Point>(
    scope,
    selected
      ? {
          id: selectedId,
          score: selected.score,
          objective_values: selected.objective_values ?? {},
          purchase_cost_gp: selected.purchase_cost_gp,
          wilderness_loss_gp: selected.wilderness_risk?.loss_gp,
          maximum_actions: selected.maximum_actions,
        }
      : undefined,
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
          if (
            lossCap !== undefined &&
            (!riskWithinBudget(point.wilderness_loss_gp, lossCap) ||
              (point.objective_values.wilderness_loss_gp !== undefined &&
                point.objective_values.wilderness_loss_gp !==
                  point.wilderness_loss_gp))
          )
            throw new Error("Invalid Wilderness risk in objective result.");
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
  }, [runId, groupId, sort, direction, cursor, result, lossCap]);
  const choose = async (id: string) => {
    const version = ++selectionVersion.current;
    setSelecting(true);
    setError("");
    try {
      const existing = group?.points.find((point) => point.id === id);
      const baseline =
        group?.baseline_solution_id === id
          ? group.baseline_solution
          : undefined;
      const known = selectedLabSolution(result, id);
      const raw =
        existing?.solution ??
        baseline ??
        known ??
        (
          await get(
            encodeURIComponent(runId!) + "/solutions/" + encodeURIComponent(id),
          )
        ).solution;
      objectiveValues(
        raw.objective_values,
        canonicalObjectives(result.scenario.request.objectives ?? []),
        id === group?.baseline_solution_id || !!known,
      );
      parseWildernessRisk(
        raw.wilderness_risk,
        result.scenario.request,
        true,
        raw.objective_values,
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
  const tableRows = [
    ...retained
      .map((point, index) => ({
        point,
        label: index === 0 ? "Starting setup" : `Viewed setup ${index}`,
      }))
      .filter(({ point }) => !rows.some((row) => row.id === point.id)),
    ...rows.map((point, index) => ({
      point,
      label: `Select setup ${(cursors.length - 1) * 50 + index + 1}`,
    })),
  ];
  const value = (point: Point, id: string) =>
    id === "dps" ? point.score : (point.objective_values[id] ?? NaN);
  const openLab = (event: React.MouseEvent<HTMLAnchorElement>) => {
    try {
      const token = storeLabSnapshot(
        createLabSnapshot(result, group, selectedId),
      );
      const url = new URL(location.href);
      url.search = new URLSearchParams({
        view: "tradeoff-lab",
        session: token,
      }).toString();
      url.hash = "";
      event.currentTarget.href = url.toString();
    } catch (failure) {
      event.preventDefault();
      setError((failure as Error).message);
    }
  };
  return (
    <section className="panel" aria-label="Objective tradeoffs">
      <h2>Best-found objective tradeoffs</h2>
      <p>
        {page?.total ?? group.total_count ?? samples.length} distinct tradeoffs.
        Each row is one complete configuration.
      </p>
      {definitions.some((d) => d.kind === "gp_per_damage") &&
        !samples.length && (
          <p>
            No priced setup with known GP/damage was found within this DPS
            range.
          </p>
        )}
      <div className="objective-shortcuts" aria-label="Objective endpoints">
        {axes.map((axis) => {
          const minimize =
            definitions.find((d) => d.id === axis.id)?.direction === "minimize";
          const best = samples.reduce<Point | undefined>(
            (previous, point) =>
              !previous ||
              (minimize
                ? value(point, axis.id) < value(previous, axis.id)
                : value(point, axis.id) > value(previous, axis.id))
                ? point
                : previous,
            undefined,
          );
          const id =
            axis.id === "dps"
              ? (group.baseline_solution_id ?? best?.id)
              : best?.id;
          return (
            id && (
              <button
                key={axis.id}
                type="button"
                disabled={selecting}
                onClick={() => void choose(id)}
              >
                {minimize
                  ? axis.id === "gp_per_damage"
                    ? "Lowest GP/damage"
                    : "Lowest Wilderness loss"
                  : "Highest " + axis.label}
              </button>
            )
          );
        })}
      </div>
      <a
        className="objective-lab-link"
        href="?view=tradeoff-lab"
        target="_blank"
        rel="noopener noreferrer"
        onClick={openLab}
        onAuxClick={openLab}
        onContextMenu={openLab}
      >
        Open full tradeoff lab ↗
      </a>
      {definitions.length > 0 && (
        <>
          <p>
            {group.sampled && "The chart uses a sample from the full table. "}A
            point can appear worse on these axes while improving another
            objective.
          </p>
          <ObjectiveScatter
            key={scope}
            axes={axes}
            points={[
              ...samples,
              ...retained.filter(
                (point) => !samples.some((p) => p.id === point.id),
              ),
            ]}
            selectedId={selectedId}
            disabled={selecting}
            onSelect={(id) => void choose(id)}
          />
        </>
      )}
      <div className="objective-shortcuts">
        <label>
          Sort tradeoffs
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setDirection(
                definitions.find((d) => d.id === e.target.value)?.direction ===
                  "minimize"
                  ? "asc"
                  : "desc",
              );
            }}
          >
            {axes.map((axis) => (
              <option key={axis.id} value={axis.id}>
                {axis.label}
              </option>
            ))}
            <option value="purchase_cost_gp">Purchase cost</option>
            {separateRisk && (
              <option value="wilderness_loss_gp">Wilderness risk</option>
            )}
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
                        : def.unit === "GP"
                          ? " (GP)"
                          : def.unit === "GP/damage"
                            ? " (GP/damage)"
                            : ""}
                </th>
              ))}
              <th>Cost (GP)</th>
              {separateRisk && <th>Risk (GP)</th>}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map(({ point, label }) => (
              <tr key={point.id} aria-selected={selectedId === point.id}>
                <td>
                  <button
                    type="button"
                    disabled={selecting}
                    aria-pressed={selectedId === point.id}
                    onClick={() => void choose(point.id)}
                  >
                    {label}
                  </button>
                </td>
                <td>{format(point.score)}</td>
                {definitions.map((def) => (
                  <td key={def.id}>
                    {format(point.objective_values[def.id], def)}
                  </td>
                ))}
                <td>{point.purchase_cost_gp.toLocaleString()}</td>
                {separateRisk && (
                  <td>
                    {point.wilderness_loss_gp?.toLocaleString() ??
                      "Unavailable"}
                  </td>
                )}
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
