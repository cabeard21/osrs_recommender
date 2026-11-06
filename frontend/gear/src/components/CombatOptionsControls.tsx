import type {
  CombatOptionAvailability,
  CombatOptionSelection,
  GearContext,
  Role,
} from "../api/contracts";
import {
  availableCombatOptions,
  emptyCombatOptionGroups,
  emptyCombatOptions,
  selectOnlyCombatOptions,
  selectedCombatOptions,
  setCombatOptionEnabled,
  spellQuickPicks,
} from "../api/combatOptions";

type Field = keyof CombatOptionSelection;

const groups: { field: Field; label: string; noun: string }[] = [
  { field: "attack_types", label: "Attack types", noun: "attack types" },
  { field: "stances", label: "Stances", noun: "stances" },
  { field: "spells", label: "Spells and powered attacks", noun: "spells" },
];

const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && a.every((id) => b.includes(id));

function groupSummary(noun: string, selected: number, total: number) {
  return total > 0 && selected === total
    ? `All ${noun}`
    : `${selected}/${total} ${noun}`;
}

export function CombatOptionsControls({
  role,
  context,
  liveMode,
  onChange,
}: {
  role: Role;
  context: GearContext | null;
  liveMode: boolean;
  onChange: (patch: Partial<Role>) => void;
}) {
  const catalog = availableCombatOptions(role, context);
  const selected = selectedCombatOptions(role, context);
  const enabled = role.combatOptionOptimization !== false;
  const visibleGroups = groups.filter(
    ({ field }) =>
      field !== "spells" ||
      (role.autoDiscipline
        ? (role.allowedDisciplines ?? ["melee", "ranged", "magic"]).includes(
            "magic",
          )
        : role.style === "magic"),
  );
  const emptyGroups = emptyCombatOptionGroups(role, context);
  const eligible = (field: Field): CombatOptionAvailability[] =>
    catalog?.[field].filter((option) => option.available) ?? [];
  const summary =
    enabled && catalog && selected
      ? visibleGroups
          .map(({ field, noun }) =>
            groupSummary(noun, selected[field].length, eligible(field).length),
          )
          .join(" · ")
      : "";
  const selectAll = (field: Field) =>
    onChange({
      combatOptionDisabled: {
        ...(role.combatOptionDisabled ?? emptyCombatOptions()),
        [field]: [],
      },
      combatOptionExplicitlyEmpty: {
        ...role.combatOptionExplicitlyEmpty,
        [field]: false,
      },
    });
  const selectOnly = (field: Field, ids: string[]) =>
    onChange(selectOnlyCombatOptions(role, field, ids, context));
  const picks = spellQuickPicks(role, context);
  return (
    <details className="raised" aria-label={`${role.name} Combat Options`}>
      <summary>
        Combat Options
        {summary && <span className="option-count"> · {summary}</span>}
      </summary>
      <label className="check">
        <input
          type="checkbox"
          checked={role.autoDiscipline || enabled}
          disabled={role.autoDiscipline}
          onChange={(event) =>
            onChange({ combatOptionOptimization: event.target.checked })
          }
        />
        Optimize attack type, stance and spell with equipment
      </label>
      {!liveMode && (
        <p>
          Fixture mode records these controls; it does not calculate combat
          options.
        </p>
      )}
      {enabled && !catalog && liveMode && (
        <p role="status" className="notice">
          Synced combat options are unavailable. Refresh account context.
        </p>
      )}
      {enabled && catalog && selected && (
        <>
          {visibleGroups.map(({ field, label }) => {
            const isEmpty = emptyGroups.includes(field);
            const lower = label.toLowerCase();
            return (
              <fieldset key={field}>
                <legend>{label}</legend>
                {eligible(field).length > 1 && (
                  <div className="option-shortcuts">
                    <button
                      type="button"
                      aria-label={`Select All ${lower}`}
                      onClick={() => selectAll(field)}
                    >
                      All
                    </button>
                    <button
                      type="button"
                      aria-label={`Select none of the ${lower}`}
                      onClick={() => selectOnly(field, [])}
                    >
                      None
                    </button>
                    {field === "spells" &&
                      picks.map((pick) => (
                        <button
                          type="button"
                          key={pick.label}
                          aria-label={`Select only ${pick.label} spells`}
                          aria-pressed={sameSet(pick.ids, selected.spells)}
                          onClick={() => selectOnly(field, pick.ids)}
                        >
                          {pick.label}
                        </button>
                      ))}
                  </div>
                )}
                <div className="combat-option-list">
                  {catalog[field].map((option) => (
                    <label className="check" key={option.id}>
                      <input
                        type="checkbox"
                        disabled={!option.available}
                        aria-invalid={
                          (isEmpty && option.available) || undefined
                        }
                        checked={
                          option.available &&
                          selected[field].includes(option.id)
                        }
                        onChange={(event) => {
                          const updated = setCombatOptionEnabled(
                            role,
                            field,
                            option.id,
                            event.target.checked,
                            context,
                          );
                          onChange({
                            combatOptionDisabled: updated.combatOptionDisabled,
                            combatOptionExplicitlyEmpty:
                              updated.combatOptionExplicitlyEmpty,
                          });
                        }}
                      />
                      {option.name ?? option.id.replaceAll("_", " ")}
                      {option.reason && !option.available
                        ? ` · ${option.reason}`
                        : ""}
                    </label>
                  ))}
                </div>
              </fieldset>
            );
          })}
          <button
            type="button"
            onClick={() =>
              onChange({
                combatOptionOptimization: true,
                combatOptionDisabled: emptyCombatOptions(),
                combatOptionExplicitlyEmpty: {},
              })
            }
          >
            Reset to Defaults
          </button>
          {emptyGroups.length > 0 && (
            <p role="status" className="notice">
              No legal combat configuration can satisfy an empty selection.
              Enable at least one option in each group.
            </p>
          )}
        </>
      )}
    </details>
  );
}
