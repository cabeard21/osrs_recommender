import {
  slots,
  type JointSolutionDTO,
  type OptimizationReply,
} from "../api/contracts";
import type { ObjectiveDefinition } from "../api/objectives";
import { formatTradeoffValue } from "./objectiveTradeoff";
import { equipmentFor } from "./resultFormat";

type Loadout = JointSolutionDTO["loadouts"][string];

const readable = (label: string) => label.replaceAll("_", " ");
const capitalize = (label: string) =>
  label.charAt(0).toUpperCase() + label.slice(1);
const gp = (value: number) => `${value.toLocaleString()} GP`;

function combatOptions(loadout: Loadout) {
  const option = loadout.combat_option;
  return option
    ? [option.attack_type, option.stance, option.spell ?? option.powered_attack]
        .filter((part): part is string => Boolean(part))
        .map(readable)
        .join(" · ")
    : null;
}

function changedGear(
  before: Loadout,
  after: Loadout,
  itemName: (id: number | null) => string,
) {
  const initial = equipmentFor(before.equipment);
  const current = equipmentFor(after.equipment);
  return slots
    .filter((slot) => initial[slot] !== current[slot])
    .map((slot) => ({
      label: capitalize(slot),
      before: itemName(initial[slot]),
      after: itemName(current[slot]),
    }));
}

function viewSection(id: string) {
  const target = document.getElementById(id);
  target?.focus({ preventScroll: true });
  target?.scrollIntoView?.({ block: "start" });
}

interface Metric {
  label: string;
  current: number | null | undefined;
  starting: number | null | undefined;
  format: (value: number) => string;
}

function delta(metric: Metric) {
  if (metric.current == null || metric.starting == null) return "—";
  const difference = metric.current - metric.starting;
  return (
    (difference < 0 ? "−" : difference > 0 ? "+" : "") +
    metric.format(Math.abs(difference))
  );
}

export function ObjectiveSelectionSummary({
  result,
  selected,
  starting,
  definitions,
}: {
  result: OptimizationReply;
  selected: JointSolutionDTO;
  starting: JointSolutionDTO;
  definitions: ObjectiveDefinition[];
}) {
  const roles = result.scenario.request.roles ?? [];
  const itemName = (id: number | null) =>
    id === null
      ? "Empty"
      : (result.items?.find((item) => item.id === id)?.name ?? `Item #${id}`);
  const disciplines = Object.entries(selected.loadouts ?? {}).map(
    ([id, loadout]) => {
      const role = roles.find((entry) => entry.id === id);
      const style = loadout.discipline ?? role?.style;
      const name = style
        ? capitalize(style)
        : role?.utility
          ? "Utility"
          : "Unspecified";
      return roles.length > 1 ? `${role?.name ?? id} · ${name}` : name;
    },
  );
  const changes = Object.entries(selected.loadouts ?? {}).flatMap(
    ([id, after]) => {
      const before = starting.loadouts?.[id];
      if (!before) return [];
      const gear = changedGear(before, after, itemName);
      const previousCombat = combatOptions(before);
      const currentCombat = combatOptions(after);
      return [
        ...gear,
        ...(previousCombat !== currentCombat
          ? [
              {
                label: "Combat option",
                before: previousCombat ?? "Unavailable",
                after: currentCombat ?? "Unavailable",
              },
            ]
          : []),
      ].map((change) => ({
        ...change,
        key: `${id}-${change.label}`,
        label:
          roles.length > 1
            ? `${roles.find((role) => role.id === id)?.name ?? id} · ${change.label}`
            : change.label,
      }));
    },
  );
  const metrics: Metric[] = [
    {
      label: roles.length > 1 ? "Weighted DPS" : "DPS",
      current: selected.score,
      starting: starting.score,
      format: formatTradeoffValue,
    },
    {
      label: "Purchase cost",
      current: selected.purchase_cost_gp,
      starting: starting.purchase_cost_gp,
      format: gp,
    },
    ...definitions.map((definition) => ({
      label: definition.label,
      current: selected.objective_values?.[definition.id],
      starting: starting.objective_values?.[definition.id],
      format: (value: number) =>
        formatTradeoffValue(value, definition) +
        (definition.unit === "GP" || definition.unit === "GP/damage"
          ? ` ${definition.unit}`
          : ""),
    })),
  ];
  return (
    <section
      aria-label="Selected setup comparison"
      className="objective-selection-summary"
    >
      <div className="objective-selection-title">
        <h3>Selected setup</h3>
        <p>Compared with the starting setup</p>
      </div>
      <p
        className="objective-selection-disciplines"
        title={disciplines.join(" / ") || undefined}
      >
        {disciplines.join(" / ")}
      </p>
      <dl className="objective-selection-metrics">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>
              <strong>
                {metric.current == null
                  ? "Unavailable"
                  : metric.format(metric.current)}
              </strong>
              <span
                aria-label={`Change from the starting setup ${delta(metric)}`}
              >
                {delta(metric)}
              </span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="objective-visually-hidden" role="status">
        Selected setup at {formatTradeoffValue(selected.score)} DPS. Purchase
        cost {gp(selected.purchase_cost_gp)}.
      </p>
      <details>
        <summary>Gear and combat changes · {changes.length}</summary>
        {changes.length ? (
          <ul className="objective-selection-changes">
            {changes.map((change) => (
              <li key={change.key}>
                <strong>{change.label}</strong> {change.before} → {change.after}
              </li>
            ))}
          </ul>
        ) : (
          <p>Uses the starting gear and combat options.</p>
        )}
      </details>
      <div className="objective-shortcuts">
        <button type="button" onClick={() => viewSection("selected-outfit")}>
          View outfit
        </button>
        <button
          type="button"
          onClick={() => viewSection("selected-acquisition")}
        >
          View acquisition
        </button>
      </div>
    </section>
  );
}
