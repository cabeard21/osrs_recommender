import { useId, useLayoutEffect, useRef, useState } from "react";
import type {
  JointSolutionDTO,
  ObjectiveFrontierGroup,
  OptimizationReply,
} from "../api/contracts";
import { canonicalObjectives, objectiveValues } from "../api/objectives";
import { parseWildernessRisk, wildernessRiskCap } from "../api/wilderness";
import {
  createLabSnapshot,
  selectedLabSolution,
  storeLabSnapshot,
} from "../tradeoff-lab/snapshot";
import { ObjectiveScatter } from "./ObjectiveScatter";
import { ObjectiveSelectionSummary } from "./ObjectiveSelectionSummary";
import { ObjectiveTradeoffTable } from "./ObjectiveTradeoffTable";
import { tradeoffPoint, type TradeoffPoint } from "./objectiveTradeoff";
import {
  fetchObjectiveArchive,
  useObjectiveArchive,
} from "./useObjectiveArchive";
import { useRetainedObjectivePoints } from "./useRetainedObjectivePoints";

interface FrontierProps {
  result: OptimizationReply;
  swapLimit: number | null;
  selectedId: string;
  selectedSolution?: JointSolutionDTO | null;
  selectionRevision?: number;
  labOriginId?: string | null;
  onSelect: (
    id: string,
    raw: JointSolutionDTO,
    runId?: string,
    groupId?: string,
    selectionRevision?: number,
  ) => void;
}

interface ScopedFrontier extends FrontierProps {
  group: ObjectiveFrontierGroup;
  runId: string | undefined;
}

type Ordering = { sort: string; direction: "asc" | "desc" };
const DEFAULT_ORDER: Ordering = { sort: "dps", direction: "desc" };

export function ObjectiveFrontier(props: FrontierProps) {
  const { result, swapLimit } = props;
  const group = result.live?.result.objective_frontiers?.find(
    (candidate) => candidate.swap_limit === swapLimit,
  );
  if (!group || result.scenario.request.objectives === undefined) return null;
  const runId = result.live?.run_id ?? result.live?.result.run_id;
  return (
    <FrontierRun
      key={runId ?? result.fingerprint}
      {...props}
      group={group}
      runId={runId}
    />
  );
}

function FrontierRun(props: ScopedFrontier) {
  const definitions = props.result.live?.result.objective_definitions ?? [];
  const lossCap = wildernessRiskCap(props.result.scenario.request);
  const separateRisk =
    lossCap !== undefined &&
    !definitions.some((d) => d.kind === "wilderness_loss_gp");
  const sortOptions = [
    { id: "dps", label: "DPS" },
    ...definitions,
    { id: "purchase_cost_gp", label: "Purchase cost" },
    ...(separateRisk
      ? [{ id: "wilderness_loss_gp", label: "Wilderness risk" }]
      : []),
    { id: "maximum_actions", label: "Maximum actions" },
  ];
  const [preferredOrder, setOrdering] = useState(DEFAULT_ORDER);
  const ordering = sortOptions.some(
    (option) => option.id === preferredOrder.sort,
  )
    ? preferredOrder
    : DEFAULT_ORDER;
  const scope = JSON.stringify([
    props.group.id ?? props.group.group_id,
    props.swapLimit,
    definitions.map((definition) => definition.id),
  ]);
  return (
    <FrontierGroup
      key={scope}
      {...props}
      scope={scope}
      ordering={ordering}
      setOrdering={setOrdering}
      sortOptions={sortOptions}
      lossCap={lossCap}
      separateRisk={separateRisk}
    />
  );
}

function FrontierGroup({
  result,
  swapLimit,
  selectedId,
  selectedSolution,
  selectionRevision,
  labOriginId,
  onSelect,
  group,
  runId,
  scope,
  ordering,
  setOrdering,
  sortOptions,
  lossCap,
  separateRisk,
}: ScopedFrontier & {
  scope: string;
  ordering: Ordering;
  setOrdering: (ordering: Ordering) => void;
  sortOptions: { id: string; label: string }[];
  lossCap: number | null | undefined;
  separateRisk: boolean;
}) {
  const groupId = group.id ?? group.group_id;
  const definitions = result.live?.result.objective_definitions ?? [];
  const axes = [{ id: "dps", label: "DPS" }, ...definitions];
  const goals = result.scenario.request.objectives ?? [];
  const archive = useObjectiveArchive(
    runId,
    groupId,
    ordering.sort,
    ordering.direction,
    JSON.stringify(goals),
    lossCap,
  );
  const [phoneView, setPhoneView] = useState<"setups" | "chart">("setups");
  const viewId = useId();
  const [localError, setLocalError] = useState("");
  const [selecting, setSelecting] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  useLayoutEffect(() => {
    setSelecting(false);
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [selectionRevision]);
  const samples = group.points.map((point) =>
    tradeoffPoint(point.id, point.solution),
  );
  const selected =
    selectedSolution ??
    selectedLabSolution(result, selectedId) ??
    group.points.find((point) => point.id === selectedId)?.solution ??
    (selectedId === group.baseline_solution_id
      ? group.baseline_solution
      : null);
  const retained = useRetainedObjectivePoints(
    scope,
    selected
      ? { ...tradeoffPoint(selectedId, selected), solution: selected }
      : undefined,
  );

  async function choose(id: string) {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setSelecting(true);
    setLocalError("");
    try {
      const known =
        selectedLabSolution(result, id) ??
        retained.find((point) => point.id === id)?.solution;
      const baseline =
        group.baseline_solution_id === id ? group.baseline_solution : null;
      let solution =
        group.points.find((point) => point.id === id)?.solution ??
        baseline ??
        known;
      if (!solution) {
        if (!runId) throw new Error("This setup is unavailable.");
        const detail = await fetchObjectiveArchive(
          `${encodeURIComponent(runId)}/solutions/${encodeURIComponent(id)}`,
          controller.signal,
        );
        solution = (detail as { solution?: JointSolutionDTO } | null)?.solution;
      }
      if (controller.signal.aborted) return;
      if (!solution) throw new Error("This setup is unavailable.");
      objectiveValues(
        solution.objective_values,
        canonicalObjectives(goals),
        id === group.baseline_solution_id || Boolean(known),
      );
      parseWildernessRisk(
        solution.wilderness_risk,
        result.scenario.request,
        true,
        solution.objective_values,
      );
      onSelect(id, solution, runId, groupId, selectionRevision);
    } catch (error) {
      if (!controller.signal.aborted) setLocalError((error as Error).message);
    } finally {
      if (!controller.signal.aborted && controllerRef.current === controller) {
        controllerRef.current = null;
        setSelecting(false);
      }
    }
  }

  function openLab(event: React.MouseEvent<HTMLAnchorElement>) {
    try {
      const token = storeLabSnapshot(
        createLabSnapshot(result, group, selectedId),
        undefined,
        labOriginId && runId && groupId
          ? {
              originId: labOriginId,
              workspace:
                (result.scenario.request.roles?.length ?? 1) > 1
                  ? "multi"
                  : "single",
              runId,
              groupId,
              swapLimit,
            }
          : undefined,
      );
      const url = new URL(location.href);
      url.search = new URLSearchParams({
        view: "tradeoff-lab",
        session: token,
      }).toString();
      url.hash = "";
      event.currentTarget.href = url.toString();
      setLocalError("");
    } catch (error) {
      event.preventDefault();
      setLocalError((error as Error).message);
    }
  }

  const pageRows = archive.page?.points ?? samples;
  const starting = retained[0];
  const rows = [
    ...retained.flatMap((point, index) =>
      index === 0 || !pageRows.some((row) => row.id === point.id)
        ? [
            {
              point,
              label: index === 0 ? "Starting setup" : `Viewed setup ${index}`,
            },
          ]
        : [],
    ),
    ...pageRows.flatMap((point, index) =>
      point.id === starting?.id
        ? []
        : [{ point, label: `Select setup ${archive.offset + index + 1}` }],
    ),
  ];
  return (
    <section
      className="panel objective-frontier"
      aria-label="Objective tradeoffs"
    >
      <h2>Best-found objective tradeoffs</h2>
      <p>
        {archive.page?.total ?? group.total_count ?? samples.length} distinct
        tradeoffs. Each row is one complete configuration.
      </p>
      {definitions.some((definition) => definition.kind === "gp_per_damage") &&
        !samples.length && (
          <p>
            No priced setup with known GP/damage was found within this DPS
            range.
          </p>
        )}
      {selected && starting && (
        <ObjectiveSelectionSummary
          result={result}
          selected={selected}
          starting={starting.solution}
          definitions={definitions}
        />
      )}
      <div className="objective-shortcuts" aria-label="Objective endpoints">
        {axes.map((axis) => {
          const direction = "direction" in axis ? axis.direction : undefined;
          const best = bestPoint(samples, axis.id, direction === "minimize");
          const id =
            axis.id === "dps" ? (group.baseline_solution_id ?? best) : best;
          if (!id) return null;
          const label = endpointLabel(
            axis.id,
            axis.label,
            direction === "minimize",
          );
          return (
            <button
              key={axis.id}
              type="button"
              disabled={selecting}
              onClick={() => void choose(id)}
            >
              {label}
            </button>
          );
        })}
        <a
          className="objective-lab-link"
          href="?view=tradeoff-lab"
          target="_blank"
          rel="noopener noreferrer"
          onClick={openLab}
          onAuxClick={openLab}
          onContextMenu={openLab}
        >
          Explore this run
        </a>
      </div>
      {(localError || archive.error) && (
        <p role="alert">{localError || archive.error}</p>
      )}
      {definitions.length > 0 && (
        <>
          <div
            className="objective-phone-views"
            role="group"
            aria-label="Tradeoff view"
          >
            <button
              type="button"
              aria-controls={`${viewId}-setups`}
              aria-pressed={phoneView === "setups"}
              onClick={() => setPhoneView("setups")}
            >
              Setups
            </button>
            <button
              type="button"
              aria-controls={`${viewId}-chart`}
              aria-pressed={phoneView === "chart"}
              onClick={() => setPhoneView("chart")}
            >
              Chart
            </button>
          </div>
          <div
            id={`${viewId}-chart`}
            className="objective-frontier-chart"
            data-phone-active={phoneView === "chart"}
          >
            <p>
              {group.sampled &&
                "The chart uses a sample from the full setup list. "}
              A point can appear worse on these axes while improving another
              objective.
            </p>
            <ObjectiveScatter
              axes={axes}
              points={[
                ...samples,
                ...retained.filter(
                  (point) => !samples.some((sample) => sample.id === point.id),
                ),
              ]}
              selectedId={selectedId}
              disabled={selecting}
              onSelect={(id) => void choose(id)}
            />
          </div>
        </>
      )}
      <div
        id={`${viewId}-setups`}
        className="objective-frontier-archive"
        data-phone-active={phoneView === "setups" || definitions.length === 0}
      >
        <div className="objective-shortcuts">
          <label>
            Sort tradeoffs
            <select
              value={ordering.sort}
              onChange={(event) => {
                const sort = event.target.value;
                const minimize = definitions.some(
                  (definition) =>
                    definition.id === sort &&
                    definition.direction === "minimize",
                );
                setOrdering({ sort, direction: minimize ? "asc" : "desc" });
              }}
            >
              {sortOptions.map(({ id, label }) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Sort direction
            <select
              value={ordering.direction}
              onChange={(event) =>
                setOrdering({
                  sort: ordering.sort,
                  direction: event.target.value === "asc" ? "asc" : "desc",
                })
              }
            >
              <option value="desc">Highest first</option>
              <option value="asc">Lowest first</option>
            </select>
          </label>
        </div>
        <ObjectiveTradeoffTable
          rows={rows}
          definitions={definitions}
          showRisk={separateRisk}
          selectedId={selectedId}
          loading={archive.loading}
          selecting={selecting}
          onSelect={(id) => void choose(id)}
        />
        {runId && groupId && (
          <div className="objective-shortcuts">
            <button
              type="button"
              disabled={archive.loading || archive.pageNumber < 2}
              onClick={archive.previous}
            >
              Previous page
            </button>
            <span aria-live="polite">Page {archive.pageNumber}</span>
            <button
              type="button"
              disabled={archive.loading || !archive.page?.next_cursor}
              onClick={() => {
                const next = archive.page?.next_cursor;
                if (next) archive.next(next);
              }}
            >
              Next page
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function bestPoint(points: TradeoffPoint[], axis: string, minimize: boolean) {
  let best: { id: string; value: number } | undefined;
  for (const point of points) {
    const value = axis === "dps" ? point.score : point.objective_values[axis];
    if (value == null || !Number.isFinite(value)) continue;
    if (!best || (minimize ? value < best.value : value > best.value))
      best = { id: point.id, value };
  }
  return best?.id;
}

function endpointLabel(id: string, label: string, minimize: boolean) {
  if (!minimize) return `Highest ${label}`;
  if (id === "gp_per_damage") return "Lowest GP/damage";
  if (id === "wilderness_loss_gp") return "Lowest Wilderness loss";
  return `Lowest ${label}`;
}
