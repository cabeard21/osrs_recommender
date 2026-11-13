import { useEffect, useRef, useState } from "react";
import type {
  GearClient,
  JointSolutionDTO,
  OptimizationReply,
  PotionTimeline,
  PotionTimelineMeasurement,
} from "../api/contracts";
import { secondaryPriorities } from "../api/secondaryPriorities";

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
const number = (value: number | null, percent = false) =>
  value === null
    ? "Unavailable"
    : percent
      ? `${(value * 100).toFixed(2)}%`
      : value.toFixed(3);

function StepChart({
  samples,
  baseline,
  field,
  label,
  percent,
  active,
  onSelect,
  divine,
  boosts,
}: {
  samples: PotionTimelineMeasurement[];
  baseline: number | null;
  field: "dps" | "secondary_value";
  label: string;
  percent: boolean;
  active: number;
  onSelect: (index: number) => void;
  divine: boolean;
  boosts: string[];
}) {
  const values = samples
    .map((s) => s[field])
    .filter((v): v is number => v !== null);
  const plotted = baseline === null ? values : [...values, baseline];
  const minimum = plotted.length ? Math.min(...plotted) : 0;
  const maximum = plotted.length ? Math.max(...plotted) : 1;
  const padding =
    maximum > minimum
      ? (maximum - minimum) * 0.12
      : Math.max(Math.abs(maximum) * 0.05, percent ? 0.0001 : 0.001);
  const relative = baseline !== null && baseline !== 0;
  const low = relative
    ? baseline
    : minimum >= 0
      ? Math.max(0, minimum - padding)
      : minimum - padding;
  const high = samples[0]?.[field] ?? maximum;
  const end = samples.at(-1)?.time_seconds || 1;
  const x = (t: number) => 70 + (t / end) * 500;
  const y = (v: number) =>
    high === low ? 155 : 155 - ((v - low) / (high - low)) * 120;
  const axisValue = (value: number) => {
    if (!relative) return number(value, percent);
    const gain = Number(
      (((value - baseline) / Math.abs(baseline)) * 100).toFixed(2),
    );
    return `${gain > 0 ? "+" : ""}${gain.toFixed(2)}%`;
  };
  let path = "";
  samples.forEach((s, i) => {
    const value = s[field],
      previous = samples[i - 1]?.[field];
    if (previous != null) path += ` H${x(s.time_seconds)}`;
    if (value !== null)
      path +=
        previous == null
          ? ` M${x(s.time_seconds)},${y(value)}`
          : ` V${y(value)}`;
  });
  return (
    <figure style={{ margin: "1rem 0" }}>
      <figcaption>{label}</figcaption>
      <small>
        {relative
          ? "Y-axis: % above unboosted baseline"
          : "Percentage gain unavailable (baseline is zero or unavailable); showing absolute values."}
      </small>
      <svg
        viewBox="0 0 600 200"
        role="img"
        aria-label={`${label} over time`}
        style={{ width: "100%", maxHeight: 260 }}
      >
        <path d="M70 25 V155 H570" fill="none" stroke="currentColor" />
        {divine && end >= 300 && (
          <g>
            <path
              d={`M${x(300)} 25 V155`}
              stroke="#93b5db"
              strokeDasharray="3 3"
            />
            <text x={x(300) - 80} y="20" fill="currentColor" fontSize="11">
              Divine expiry · 5:00
            </text>
          </g>
        )}
        {[...new Set([low, (low + high) / 2, high])].map((value) => (
          <g key={value}>
            <path
              d={`M70 ${y(value)} H570`}
              stroke="currentColor"
              opacity=".12"
            />
            <text
              x="64"
              y={y(value) + 4}
              textAnchor="end"
              fill="currentColor"
              fontSize="11"
            >
              {axisValue(value)}
            </text>
          </g>
        ))}
        <text x="70" y="178" fill="currentColor" fontSize="11">
          0:00
        </text>
        <text x="535" y="178" fill="currentColor" fontSize="11">
          {clock(end)}
        </text>
        <text x="240" y="195" fill="currentColor" fontSize="11">
          Time since application
        </text>
        {baseline !== null && (
          <path
            d={`M70 ${y(baseline)} H570`}
            stroke="currentColor"
            strokeDasharray="5 5"
            opacity=".5"
          />
        )}
        <path d={path} stroke="#dfb86c" strokeWidth="2.5" fill="none" />
        <path
          d={`M${x(samples[active]?.time_seconds ?? 0)} 25 V155`}
          stroke="currentColor"
          opacity=".35"
        />
        {samples.map(
          (s, i) =>
            s[field] !== null && (
              <circle
                key={s.time_seconds}
                cx={x(s.time_seconds)}
                cy={y(s[field]!)}
                r={active === i ? 5 : 3}
                fill="#dfb86c"
                onMouseEnter={() => onSelect(i)}
                onClick={() => onSelect(i)}
              >
                <title>
                  {clock(s.time_seconds)}: {number(s[field], percent)} ·{" "}
                  {boosts[i]}
                </title>
              </circle>
            ),
        )}
      </svg>
      <p>
        {clock(samples[active]?.time_seconds ?? 0)} · {boosts[active]}
      </p>
      <small>
        Dashed line: Same gear, unboosted · {number(baseline, percent)}
        {relative ? " (0% gain)" : ""}
      </small>
      {values.length === samples.length &&
        values.length > 0 &&
        values.every((v) => v === values[0]) && (
          <p>This metric stays constant for the selected configuration.</p>
        )}
    </figure>
  );
}

export function PotionTimelinePanel({
  result,
  solution,
  client,
  outdated = false,
}: {
  result: OptimizationReply;
  solution: JointSolutionDTO;
  client?: GearClient;
  outdated?: boolean;
}) {
  const cache = useRef(new Map<string, PotionTimeline>());
  const [state, setState] = useState<{
    key: string;
    data?: PotionTimeline;
    error?: string;
  }>({ key: "" });
  const [retry, setRetry] = useState(0),
    [active, setActive] = useState(0),
    [role, setRole] = useState("");
  const key = JSON.stringify([
    result.snapshotId,
    result.catalogVersion,
    result.modelVersion,
    result.scenario,
    solution,
  ]);
  useEffect(() => {
    if (!client?.potionTimeline || outdated) return;
    const controller = new AbortController();
    setActive(0);
    setRole("");
    const existing = cache.current.get(key);
    if (existing) {
      setState({ key, data: existing });
      return;
    }
    setState({ key });
    client
      .potionTimeline(result, solution, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        if (cache.current.size >= 16)
          cache.current.delete(cache.current.keys().next().value!);
        cache.current.set(key, data);
        setState({ key, data });
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setState({ key, error: error.message });
      });
    return () => controller.abort();
    // The serialized key captures all result and configuration inputs.
  }, [key, client, outdated, retry]);
  if (outdated)
    return (
      <p>Rerun optimization to show potion decay for the current settings.</p>
    );
  if (!client?.potionTimeline)
    return (
      <p>Potion decay graphs are unavailable for this saved or demo result.</p>
    );
  if (state.key !== key || (!state.data && !state.error))
    return <p role="status">Calculating potion decay…</p>;
  if (state.error)
    return (
      <div role="status">
        <p>{state.error}</p>
        <button type="button" onClick={() => setRetry(retry + 1)}>
          Retry graph
        </button>
      </div>
    );
  const data = state.data!;
  const project = (s: PotionTimelineMeasurement) =>
    role
      ? {
          ...s,
          dps: s.roles[role]?.dps ?? null,
          secondary_value: s.roles[role]?.secondary_value ?? null,
        }
      : s;
  const samples = data.samples.map(project),
    baseline = project(data.baseline);
  const current = samples[active] ?? samples[0];
  const boostSkills = (
    [
      ["attack", "Atk"],
      ["strength", "Str"],
      ["defence", "Def"],
      ["ranged", "Rng"],
      ["magic", "Mag"],
    ] as const
  ).filter(([skill]) => samples[0].levels[skill] > baseline.levels[skill]);
  const boosts = samples.map(
    (sample) =>
      boostSkills
        .map(
          ([skill, name]) =>
            `+${sample.levels[skill] - baseline.levels[skill]} ${name}`,
        )
        .join(" · ") || "No stat boosts",
  );
  const priority = data.secondary_priority;
  const label =
    secondaryPriorities.find(([id]) => id === priority)?.[1] ?? priority;
  const percent = priority === "accuracy";
  const divine =
    solution.potions?.selected_ids.some((id) => id.startsWith("divine_")) ??
    false;
  const unit =
    priority === "magic_damage_bonus"
      ? "%"
      : priority.endsWith("_defence_roll")
        ? " roll"
        : priority === "accuracy"
          ? ""
          : " bonus";
  const reasons = (s: PotionTimelineMeasurement) =>
    Object.entries(s.roles)
      .filter(([id]) => !role || role === id)
      .flatMap(([, value]) => value.reasons)
      .join(" · ");
  return (
    <div aria-label="Potion decay preview">
      <h3>Performance as potions wear off</h3>
      <p>
        One application at 0:00; first ordinary stat drop assumed at 1:00, then
        every minute. The live timer may start partway through a minute. Gear,
        attacks and prayers stay fixed. Divine boosts expire at 5:00. No
        Preserve or redosing. Recommendations use fresh boosts.
      </p>
      {Object.keys(data.baseline.roles).length > 1 && (
        <label>
          Graph configuration{" "}
          <select
            aria-label="Graph configuration"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="">Weighted total</option>
            {Object.keys(data.baseline.roles).map((id) => (
              <option key={id} value={id}>
                {result.scenario.request.roles.find((r) => r.id === id)?.name ??
                  id}
              </option>
            ))}
          </select>
        </label>
      )}
      <StepChart
        boosts={boosts}
        divine={divine}
        samples={samples}
        baseline={baseline.dps}
        field="dps"
        label={
          role || Object.keys(data.baseline.roles).length === 1
            ? "DPS"
            : "Weighted DPS"
        }
        percent={false}
        active={active}
        onSelect={setActive}
      />
      {priority !== "default" && (
        <StepChart
          boosts={boosts}
          divine={divine}
          samples={samples}
          baseline={baseline.secondary_value}
          field="secondary_value"
          label={label + (priority === "accuracy" ? "" : ` (${unit.trim()})`)}
          percent={percent}
          active={active}
          onSelect={setActive}
        />
      )}
      <label>
        Inspect time{" "}
        <select
          aria-label="Inspect time"
          value={active}
          onChange={(e) => setActive(Number(e.target.value))}
        >
          {samples.map((s, i) => (
            <option key={s.time_seconds} value={i}>
              {clock(s.time_seconds)}
              {s.time_seconds === 300 &&
              solution.potions?.selected_ids.some((id) =>
                id.startsWith("divine_"),
              )
                ? " · Divine expiry"
                : ""}
            </option>
          ))}
        </select>
      </label>
      {current && (
        <div aria-live="polite">
          <p>Remaining boosts: {boosts[active]}</p>
          <p>
            {clock(current.time_seconds)} · DPS {number(current.dps)}
            {current.dps !== null && samples[0].dps !== null
              ? ` (${(current.dps - samples[0].dps).toFixed(3)} from fresh)`
              : ""}
            {priority !== "default"
              ? ` · ${label} ${number(current.secondary_value, percent)}${unit}`
              : ""}
            {priority !== "default" &&
            current.secondary_value !== null &&
            samples[0].secondary_value !== null
              ? ` (${((current.secondary_value - samples[0].secondary_value) * (percent ? 100 : 1)).toFixed(3)}${percent ? " percentage points" : unit} from fresh)`
              : ""}
          </p>
          <p>
            Levels:{" "}
            {Object.entries(current.levels)
              .filter(([skill]) => !skill.startsWith("_"))
              .map(([skill, level]) => `${skill} ${level}`)
              .join(" · ")}
          </p>
          {reasons(current) && <p>{reasons(current)}</p>}
        </div>
      )}
      {baseline.dps === null && (
        <p>Same gear, unboosted attack unavailable: {reasons(data.baseline)}</p>
      )}
      <details>
        <summary>Values at each change</summary>
        <div style={{ overflowX: "auto" }}>
          <table aria-label="Potion decay values">
            <thead>
              <tr>
                <th>Time</th>
                <th>DPS</th>
                <th>Stat boosts</th>
                {priority !== "default" && <th>{label}</th>}
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((s, i) => (
                <tr key={s.time_seconds}>
                  <td>{clock(s.time_seconds)}</td>
                  <td>{number(s.dps)}</td>
                  <td>{boosts[i]}</td>
                  {priority !== "default" && (
                    <td>
                      {number(s.secondary_value, percent)}
                      {unit}
                    </td>
                  )}
                  <td>{reasons(s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
