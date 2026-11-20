import { useState } from "react";
import {
  atomicObjectives,
  canonicalObjectives,
  defenceStyles,
  legacyObjectives,
  objectiveLabel,
  quickObjectives,
  quickSelection,
  type AtomicObjective,
  type DefenceStyle,
  type Objective,
} from "../api/objectives";
import type { SecondaryPriority } from "../api/contracts";
import {
  deleteObjectivePreset,
  readObjectivePresets,
  saveObjectivePreset,
  type ObjectivePreset,
} from "../state/objectivePresets";

export function ObjectiveBuilder({
  objectives,
  legacyPriority,
  onChange,
  wilderness = false,
  wildernessControl = false,
  showHeading = true,
  mode = "fast",
}: {
  wilderness?: boolean;
  wildernessControl?: boolean;
  showHeading?: boolean;
  objectives?: Objective[];
  legacyPriority?: SecondaryPriority;
  onChange: (goals: Objective[]) => void;
  mode?: "fast" | "thorough";
}) {
  const goals = objectives ?? legacyObjectives(legacyPriority),
    quick = quickSelection(goals);
  const [advanced, setAdvanced] = useState(!quick.representable);
  const [replacement, setReplacement] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [presets, setPresets] = useState<ObjectivePreset[]>([]);
  const change = (next: Objective[]) => {
    if (!wilderness && next.some((o) => o.kind === "wilderness_loss_gp")) {
      setError("Enable Wilderness to use this objective.");
      return;
    }
    setError("");
    onChange(next);
  };
  const toggleStyle = (style: DefenceStyle) =>
    change(
      quickObjectives(
        defenceStyles.filter((s) =>
          s === style ? !quick.styles.includes(s) : quick.styles.includes(s),
        ),
        quick.others,
        quick.mode,
      ),
    );
  const toggleOther = (kind: AtomicObjective) =>
    change(
      quickObjectives(
        quick.styles,
        atomicObjectives
          .map(([id]) => id)
          .filter((id) =>
            id === kind
              ? !quick.others.includes(id)
              : quick.others.includes(id),
          ),
        quick.mode,
      ),
    );
  const count = (() => {
    try {
      return canonicalObjectives(goals).length;
    } catch {
      return goals.length;
    }
  })();
  return (
    <section aria-label="Tradeoff objectives" className="objective-builder">
      {showHeading && <h3>Tradeoff objectives</h3>}
      <p>
        DPS is always included. Choose the tradeoffs your gear should improve.
      </p>
      <div className="objective-shortcuts">
        <button type="button" onClick={() => change([])}>
          DPS only
        </button>
        <button
          type="button"
          onClick={() => change(legacyObjectives("melee_defence_roll"))}
        >
          Weakest melee defence
        </button>
        <button
          type="button"
          onClick={() => change(legacyObjectives("magic_ranged_defence_roll"))}
        >
          Magic + ranged defence
        </button>
      </div>
      {!advanced && quick.representable && (
        <>
          <fieldset>
            <legend>Defence rolls</legend>
            <div className="objective-checks">
              {defenceStyles.map((style) => (
                <label key={style}>
                  <input
                    type="checkbox"
                    checked={quick.styles.includes(style)}
                    onChange={() => toggleStyle(style)}
                  />
                  {style}
                </label>
              ))}
            </div>
            <label>
              Selected defence rolls
              <select
                value={quick.mode}
                onChange={(e) =>
                  change(
                    quickObjectives(
                      quick.styles,
                      quick.others,
                      e.target.value as typeof quick.mode,
                    ),
                  )
                }
              >
                <option value="minimum">Improve the weakest together</option>
                <option value="mean">Improve their average together</option>
                <option value="separate">Explore each independently</option>
              </select>
            </label>
          </fieldset>
          <fieldset>
            <legend>Other objectives</legend>
            <div className="objective-checks">
              {atomicObjectives
                .filter(
                  ([id]) =>
                    id !== "wilderness_loss_gp" ||
                    (wilderness && !wildernessControl),
                )
                .map(([id, label]) => (
                  <label key={id}>
                    <input
                      type="checkbox"
                      checked={quick.others.includes(id)}
                      onChange={() => toggleOther(id)}
                    />
                    {label}
                  </label>
                ))}
            </div>
            {wilderness && wildernessControl && (
              <p>Set the loss objective in Wilderness settings.</p>
            )}
          </fieldset>
        </>
      )}
      {!advanced && !quick.representable && (
        <p>Custom groups: {goals.map(objectiveLabel).join(" · ")}</p>
      )}
      <button
        type="button"
        aria-expanded={advanced}
        onClick={() => setAdvanced(!advanced)}
      >
        Edit objective groups
      </button>
      {advanced && (
        <div className="objective-groups">
          {goals.map((goal, index) => (
            <fieldset key={index}>
              <legend>
                {goal.kind === "defence_roll"
                  ? "Defence roll group"
                  : objectiveLabel(goal)}
              </legend>
              {goal.kind === "defence_roll" && (
                <>
                  <div className="objective-checks">
                    {defenceStyles.map((style) => (
                      <label key={style}>
                        <input
                          type="checkbox"
                          checked={goal.styles.includes(style)}
                          onChange={() =>
                            change(
                              goals.map((g, i) =>
                                i === index
                                  ? {
                                      ...goal,
                                      styles: defenceStyles.filter((s) =>
                                        s === style
                                          ? !goal.styles.includes(s)
                                          : goal.styles.includes(s),
                                      ),
                                    }
                                  : g,
                              ),
                            )
                          }
                        />
                        {style}
                      </label>
                    ))}
                  </div>
                  {!goal.styles.length && (
                    <p role="alert">
                      Choose at least one defence roll in this group.
                    </p>
                  )}
                  <label>
                    Combine these rolls
                    <select
                      value={goal.aggregation}
                      onChange={(e) =>
                        change(
                          goals.map((g, i) =>
                            i === index
                              ? {
                                  ...goal,
                                  aggregation: e.target.value as
                                    "minimum" | "mean",
                                }
                              : g,
                          ),
                        )
                      }
                    >
                      <option value="minimum">Improve the weakest</option>
                      <option value="mean">Improve the average</option>
                    </select>
                  </label>
                </>
              )}
              <button
                type="button"
                aria-label={
                  "Remove " +
                  (goal.kind === "defence_roll"
                    ? "defence group"
                    : objectiveLabel(goal))
                }
                onClick={() => change(goals.filter((_, i) => i !== index))}
              >
                Remove
              </button>
            </fieldset>
          ))}
          <div className="objective-shortcuts">
            <button
              type="button"
              onClick={() =>
                change([
                  ...goals,
                  {
                    kind: "defence_roll",
                    styles: ["stab"],
                    aggregation: "minimum",
                  },
                ])
              }
            >
              + Defence group
            </button>
            {atomicObjectives
              .filter(([id]) => wilderness || id !== "wilderness_loss_gp")
              .map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  disabled={goals.some((g) => g.kind === id)}
                  onClick={() => change([...goals, { kind: id }])}
                >
                  + {label}
                </button>
              ))}
          </div>
          {!quick.representable && (
            <button type="button" onClick={() => setReplacement(true)}>
              Replace with Quick select
            </button>
          )}
          {replacement && (
            <div role="group" aria-label="Replace custom objective groups">
              <p>Replace these custom groups with a fresh Quick selection?</p>
              <button
                type="button"
                onClick={() => {
                  change([]);
                  setAdvanced(false);
                  setReplacement(false);
                }}
              >
                Replace groups
              </button>
              <button type="button" onClick={() => setReplacement(false)}>
                Keep groups
              </button>
            </div>
          )}
        </div>
      )}
      <p aria-live="polite">
        {count + 1} search objective{count ? "s" : ""}, including DPS.{" "}
        {count
          ? (
              (mode === "thorough" ? 1500000 : 500000) * count
            ).toLocaleString() +
            " frontier expansions per concrete discipline/potion branch."
          : "Ordinary DPS search."}
      </p>
      <details
        onToggle={(e) => {
          if (e.currentTarget.open) {
            try {
              setPresets(readObjectivePresets());
            } catch (err) {
              setError((err as Error).message);
            }
          }
        }}
      >
        <summary>Objective presets</summary>
        <label>
          Preset name
          <input
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => {
            try {
              setPresets(saveObjectivePreset(name, goals));
              setError("");
            } catch (e) {
              setError((e as Error).message);
            }
          }}
        >
          Save objective preset
        </button>
        {presets.map((preset) => (
          <div key={preset.name} className="objective-shortcuts">
            <button
              type="button"
              onClick={() => {
                change(preset.objectives);
                setName(preset.name);
              }}
            >
              {preset.name}
            </button>
            <button
              type="button"
              aria-label={"Delete objective preset " + preset.name}
              onClick={() => {
                try {
                  setPresets(deleteObjectivePreset(preset.name));
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Delete
            </button>
          </div>
        ))}
      </details>
      {error && <p role="alert">{error}</p>}
      <style>
        {
          ".objective-builder fieldset{margin:.75rem 0;padding:.75rem;border:1px solid var(--border,#46515c);border-radius:.5rem;min-width:0}.objective-checks,.objective-shortcuts{display:flex;flex-wrap:wrap;gap:.5rem;margin:.5rem 0}.objective-checks label{display:flex;align-items:center;gap:.4rem;text-transform:capitalize}.objective-checks input{width:auto}.objective-builder select{max-width:100%}"
        }
      </style>
    </section>
  );
}
