import { RoleWeightBreakdown } from "../components/RoleWeightBreakdown";
import { useState } from "react";
import { ArrowLeft, FlaskConical, Pin, X } from "lucide-react";
import { ColorScatter, PairwiseCharts, ParallelChart } from "./Charts";
import { SpatialChart } from "./SpatialChart";
import {
  example,
  METRICS,
  equipmentChanges,
  formatMetric,
  leaders,
  metricBounds,
  metricValue,
  metricLeader,
  metricDelta,
  normalizeMetric,
} from "./model";
import type { LabExample, LabMetric, LabPoint } from "./model";
import "./lab.css";

const views = [
  [
    "pairwise",
    "Linked pairwise charts",
    "Compare each pair without losing sight of the third objective.",
  ],
  [
    "color",
    "Color-coded scatter",
    "Three objectives in one compact, two-dimensional view.",
  ],
  [
    "parallel",
    "Parallel coordinates",
    "Follow a configuration across all three objective scales.",
  ],
  [
    "spatial",
    "Interactive 3D scatter",
    "Rotate the frontier to explore its shape and separate overlapping points.",
  ],
  [
    "compare",
    "Pinned comparisons",
    "Inspect the exact gains, losses, and equipment behind your shortlist.",
  ],
] as const;
const gp = (value: number) => `${value.toLocaleString()} GP`;

function Metrics({
  point,
  baseline,
  metrics,
}: {
  point: LabPoint;
  baseline: LabPoint;
  metrics: LabMetric[];
}) {
  return (
    <dl className="lab-metrics">
      {metrics.map((m) => (
        <div key={m.key}>
          <dt>{m.shortLabel}</dt>
          <dd>{formatMetric(m.key, metricValue(point, m.key), m)}</dd>
          <dd
            className={
              metricValue(point, m.key) > metricValue(baseline, m.key)
                ? m.direction === "minimize"
                  ? "lab-loss"
                  : "lab-gain"
                : metricValue(point, m.key) < metricValue(baseline, m.key)
                  ? m.direction === "minimize"
                    ? "lab-gain"
                    : "lab-loss"
                  : "lab-muted"
            }
          >
            {metricDelta(
              m.key,
              metricValue(point, m.key),
              metricValue(baseline, m.key),
              m,
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function EquipmentDiff({
  point,
  baseline,
  baselineLabel,
}: {
  point: LabPoint;
  baseline: LabPoint;
  baselineLabel: string;
}) {
  const changes = equipmentChanges(point, baseline);
  return (
    <>
      <h4>Equipment changes vs {baselineLabel}</h4>
      {changes.length ? (
        <ul className="lab-equipment-diff">
          {changes.map((change) => (
            <li key={change.slot}>
              <span>{change.slot}</span>
              <del>{change.from}</del>
              <strong>{change.to}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="lab-note">Same equipment as the {baselineLabel}.</p>
      )}
      <p className="lab-note">
        Potions: {point.potions.join(", ") || "None"}. Attack:{" "}
        {point.attackType}, {point.stance}.
      </p>
    </>
  );
}

function ApplyLabSetup({
  point,
  apply,
}: {
  point: LabPoint;
  apply: (pointId: string) => Promise<void>;
}) {
  const [status, setStatus] = useState<{
    kind: "sending" | "applied" | "failed";
    message: string;
  } | null>(null);
  async function useSetup() {
    setStatus({ kind: "sending", message: `Sending ${point.label}…` });
    try {
      await apply(point.id);
      setStatus({
        kind: "applied",
        message: `${point.label} selected in the original Gear optimizer tab.`,
      });
    } catch (cause) {
      setStatus({
        kind: "failed",
        message:
          cause instanceof Error
            ? cause.message
            : "The optimizer could not select this setup. Reopen the Lab and try again.",
      });
    }
  }
  return (
    <div className="lab-return">
      <button
        type="button"
        className="lab-use-setup"
        disabled={status?.kind === "sending"}
        onClick={() => void useSetup()}
      >
        Use this setup in Gear optimizer
      </button>
      {status && (
        <p
          className={
            status.kind === "failed" ? "lab-note lab-loss" : "lab-note"
          }
          role={status.kind === "failed" ? "alert" : "status"}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}

function LabBack({ checkOrigin }: { checkOrigin: () => Promise<void> }) {
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState("");

  async function backToResults() {
    setChecking(true);
    setMessage("");
    try {
      await checkOrigin();
      window.close();
      // This guidance stays visible if the browser refuses to close the tab.
      setMessage(
        "Switch to the original Gear optimizer tab to see your results.",
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="lab-back-action">
      <button
        type="button"
        disabled={checking}
        onClick={() => void backToResults()}
      >
        <ArrowLeft size={16} aria-hidden="true" />
        Back to Gear results
      </button>
      {message && <p role="status">{message}</p>}
    </div>
  );
}

export default function TradeoffLab({
  data = example,
  gearHref = "/gear",
  onBackToResults,
  onUseSetup,
}: {
  data?: LabExample;
  gearHref?: string;
  onBackToResults?: () => Promise<void>;
  onUseSetup?: (pointId: string) => Promise<void>;
}) {
  const metrics = data.metrics ?? METRICS;
  const baselineLabel = data.sourceDescription
    ? "original selection"
    : "export selection";
  const [projectionKeys, setProjectionKeys] = useState(() =>
    metrics.slice(0, 3).map((m) => m.key),
  );
  const projected = projectionKeys
    .map((key) => metrics.find((m) => m.key === key))
    .filter((m): m is LabMetric => !!m);
  const baseline = data.points.find((point) => point.id === data.selectedId)!;
  const [selectedId, setSelectedId] = useState(baseline.id);
  const [lightestFirst, setLightestFirst] = useState(false);
  const tablePoints = lightestFirst
    ? [...data.points].sort(
        (a, b) =>
          metricValue(a, "carried_weight_kg") -
          metricValue(b, "carried_weight_kg"),
      )
    : data.points;
  const [pins, setPins] = useState<string[]>(() =>
    leaders(data.points, metrics)
      .slice(0, 4)
      .map((point) => point.id),
  );
  const selected = data.points.find((point) => point.id === selectedId)!;
  const sampleCount =
    data.sampleCount ??
    data.points.filter((point) => point.id !== data.selectedId).length;
  const props = {
    points: data.points,
    selectedId,
    onSelect: setSelectedId,
    metrics: projected,
  };
  const pinned = pins.includes(selectedId);
  const pin = () =>
    setPins((previous) =>
      previous.includes(selectedId)
        ? previous
        : [...previous, selectedId].slice(0, 4),
    );
  return (
    <main className="tradeoff-lab">
      <header className="lab-header">
        {onBackToResults ? (
          <LabBack checkOrigin={onBackToResults} />
        ) : data.sourceDescription ? (
          <div className="lab-back-action">
            <p>
              Switch to the original Gear optimizer tab to see your results.
            </p>
            <a href={gearHref}>Open Gear optimizer</a>
          </div>
        ) : (
          <a className="lab-back" href={gearHref}>
            <ArrowLeft size={16} /> Gear optimizer
          </a>
        )}
        <div className="lab-eyebrow">
          <FlaskConical size={15} />{" "}
          {data.sourceDescription ? "Optimization explorer" : "Example setup"}
        </div>
        <h1>
          Tradeoff lab<span>One frontier. Five perspectives.</span>
        </h1>
        <p>
          Explore the same saved configurations in every view. Selecting a point
          highlights that loadout throughout the page.
        </p>
        <div className="lab-scenario">
          <strong>{data.target}</strong>
          {!data.sourceDescription && <span>Melee · accurate stance</span>}
          <span>{gp(data.budgetGp)} budget</span>
          <time dateTime={data.evaluatedAt}>
            Evaluated {new Date(data.evaluatedAt).toLocaleString()}
          </time>
        </div>
        <p className="lab-note">
          {data.sampled
            ? `${sampleCount} representative frontier points of ${data.totalCount}`
            : `${data.totalCount} saved frontier points`}
          {data.sourceDescription ? ". " : ", plus the export selection. "}
          {data.scope}.{" "}
          {data.sourceDescription ?? "Saved results from temp.txt"}; no
          optimization is run here.
        </p>
      </header>
      {metrics.length > 3 && (
        <fieldset className="lab-projections">
          <legend>Objectives shown in charts</legend>
          <p className="lab-note">
            Choose three objectives to visualize. Every objective remains in the
            table and comparisons.
          </p>
          <div className="lab-controls">
            {projected.map((metric, index) => (
              <label key={index}>
                Chart objective {index + 1}
                <select
                  value={metric.key}
                  onChange={(event) =>
                    setProjectionKeys((previous) =>
                      previous.map((key, i) =>
                        i === index
                          ? event.target.value
                          : key === event.target.value
                            ? previous[index]
                            : key,
                      ),
                    )
                  }
                >
                  {metrics.map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.shortLabel}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <nav className="lab-jump" aria-label="Visualization options">
        {views.map(([id, title], i) => (
          <a href={`#lab-${id}`} key={id}>
            <span>0{i + 1}</span>
            {title}
          </a>
        ))}
      </nav>
      <div className="lab-workspace">
        <div className="lab-views">
          {views.map(([id, title, description], i) => (
            <section
              key={id}
              id={`lab-${id}`}
              className="lab-section"
              aria-labelledby={`lab-title-${id}`}
            >
              <header className="lab-section-heading">
                <span className="lab-index">0{i + 1}</span>
                <div>
                  <h2 id={`lab-title-${id}`}>{title}</h2>
                  <p>{description}</p>
                </div>
                {id === "color" && (
                  <span className="lab-recommended">Default view</span>
                )}
              </header>
              {id === "pairwise" && <PairwiseCharts {...props} />}
              {id === "color" && <ColorScatter {...props} />}
              {id === "parallel" && <ParallelChart {...props} />}
              {id === "spatial" && <SpatialChart {...props} />}
              {id === "compare" && (
                <>
                  <div className="lab-controls">
                    <button
                      type="button"
                      onClick={pin}
                      disabled={pinned || pins.length >= 4}
                    >
                      <Pin size={14} />
                      Pin selected
                    </button>
                    <button
                      type="button"
                      onClick={() => setPins([])}
                      disabled={!pins.length}
                    >
                      Clear pins
                    </button>
                    <span>
                      {pins.length}/4 pinned · deltas vs {baselineLabel}
                    </span>
                  </div>
                  {!pins.length && (
                    <p>
                      Pin up to four configurations to compare their metrics and
                      equipment.
                    </p>
                  )}
                  <div className="lab-comparisons">
                    {pins.map((id) => {
                      const point = data.points.find((p) => p.id === id)!;
                      return (
                        <article
                          key={id}
                          aria-label={`Compare ${point.label}`}
                          className={
                            selectedId === id
                              ? "lab-comparison is-selected"
                              : "lab-comparison"
                          }
                        >
                          <header>
                            <button
                              className="lab-text-button"
                              type="button"
                              onClick={() => setSelectedId(id)}
                            >
                              {point.label}
                            </button>
                            <button
                              type="button"
                              aria-label={`Unpin ${point.label}`}
                              onClick={() =>
                                setPins((previous) =>
                                  previous.filter((p) => p !== id),
                                )
                              }
                            >
                              <X size={14} />
                            </button>
                          </header>
                          <Metrics
                            point={point}
                            baseline={baseline}
                            metrics={metrics}
                          />
                          {metrics.map((m) => (
                            <div className="lab-bar-row" key={m.key}>
                              <span>{m.shortLabel}</span>
                              <div className="lab-bar-track">
                                <span
                                  style={{
                                    width: `${!Number.isFinite(metricValue(point, m.key)) ? 0 : normalizeMetric(metricValue(point, m.key), metricBounds(data.points, m.key)) * 100}%`,
                                  }}
                                />
                              </div>
                            </div>
                          ))}
                          <p className="lab-cost">
                            Purchase cost <strong>{gp(point.costGp)}</strong>
                          </p>
                          {point.carriedWeight && (
                            <RoleWeightBreakdown
                              weight={point.carriedWeight}
                              roleName={(id) => data.roleNames?.[id] ?? id}
                            />
                          )}
                          <EquipmentDiff
                            point={point}
                            baseline={baseline}
                            baselineLabel={baselineLabel}
                          />
                        </article>
                      );
                    })}
                  </div>
                  <p className="lab-note">
                    Bar lengths use the saved minimum and maximum for each
                    metric; they are not percentages of combat effectiveness.
                  </p>
                </>
              )}
            </section>
          ))}
          <details className="lab-section lab-table-section">
            <summary>Browse saved configurations</summary>
            <p className="lab-note">
              All configurations included in this view.{" "}
              {data.sampled
                ? "These are representative points from the complete frontier."
                : "This view contains the complete saved frontier."}
            </p>
            {metrics.some((m) => m.key === "carried_weight_kg") && (
              <label>
                <input
                  type="checkbox"
                  checked={lightestFirst}
                  onChange={(e) => setLightestFirst(e.target.checked)}
                />
                Lightest first
              </label>
            )}
            <div className="lab-table-scroll">
              <table
                aria-label={
                  data.sourceDescription
                    ? "Saved configurations"
                    : "Saved example configurations"
                }
              >
                <thead>
                  <tr>
                    <th>Configuration</th>
                    {metrics.map((metric) => (
                      <th key={metric.key}>{metric.shortLabel}</th>
                    ))}
                    <th>Purchase cost</th>
                  </tr>
                </thead>
                <tbody>
                  {tablePoints.map((point) => (
                    <tr
                      key={point.id}
                      className={point.id === selectedId ? "is-selected" : ""}
                    >
                      <td>
                        <button
                          type="button"
                          aria-pressed={point.id === selectedId}
                          onClick={() => setSelectedId(point.id)}
                        >
                          {point.label}
                        </button>
                      </td>
                      {metrics.map((metric) => (
                        <td key={metric.key}>
                          {formatMetric(
                            metric.key,
                            metricValue(point, metric.key),
                            metric,
                          )}
                        </td>
                      ))}
                      <td>{gp(point.costGp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
        <aside className="lab-inspector" aria-label="Selected configuration">
          <div className="lab-eyebrow">Selected across all views</div>
          <h2>{selected.label}</h2>
          <Metrics point={selected} baseline={baseline} metrics={metrics} />
          <p className="lab-note">Differences vs the {baselineLabel}.</p>
          <p className="lab-cost">
            Purchase cost <strong>{gp(selected.costGp)}</strong>
          </p>
          {onUseSetup && <ApplyLabSetup point={selected} apply={onUseSetup} />}
          <button
            type="button"
            className="lab-pin"
            aria-label="Pin selected configuration"
            onClick={pin}
            disabled={pinned || pins.length >= 4}
          >
            <Pin size={15} />
            {pinned
              ? "Pinned for comparison"
              : pins.length >= 4
                ? "Four pins selected"
                : "Pin for comparison"}
          </button>
          <div className="lab-endpoints">
            <span>Jump to an objective leader</span>
            {metrics.map((metric) => {
              const leader = metricLeader(
                data.points,
                metric.key,
                metric.direction,
              );
              if (!leader) return null;
              return (
                <button
                  type="button"
                  key={metric.key}
                  onClick={() => setSelectedId(leader.id)}
                >
                  {metric.key === "carried_weight_kg"
                    ? "Lightest setup"
                    : metric.direction === "minimize"
                      ? "Lowest " + metric.shortLabel
                      : "Highest " + metric.shortLabel}
                </button>
              );
            })}
            <button type="button" onClick={() => setSelectedId(baseline.id)}>
              {data.sourceDescription
                ? "Original selection"
                : "Original export selection"}
            </button>
          </div>
          {selected.carriedWeight && (
            <RoleWeightBreakdown
              weight={selected.carriedWeight}
              roleName={(id) => data.roleNames?.[id] ?? id}
            />
          )}
          <EquipmentDiff
            point={selected}
            baseline={baseline}
            baselineLabel={baselineLabel}
          />
          <details>
            <summary>Full equipment</summary>
            <dl className="lab-full-equipment">
              {selected.equipment.map((item) => (
                <div key={item.slot}>
                  <dt>{item.slot}</dt>
                  <dd>{item.name}</dd>
                </div>
              ))}
            </dl>
          </details>
        </aside>
      </div>
      <footer className="lab-footer">
        A point can look worse in one projection while improving the hidden
        objective. All views keep the same saved configurations.
      </footer>
    </main>
  );
}
