import type {
  CombatOptionSelection,
  GearContext,
  Role,
} from "../api/contracts";
import {
  availableCombatOptions,
  emptyCombatOptions,
  selectedCombatOptions,
  setCombatOptionEnabled,
} from "../api/combatOptions";

const groups: { field: keyof CombatOptionSelection; label: string }[] = [
  { field: "attack_types", label: "Attack types" },
  { field: "stances", label: "Stances" },
  { field: "spells", label: "Spells and powered attacks" },
];

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
  return (
    <details className="raised" aria-label={`${role.name} Combat Options`}>
      <summary>Combat Options</summary>
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
          {visibleGroups.map(({ field, label }) => (
            <fieldset key={field}>
              <legend>{label}</legend>
              <button
                type="button"
                onClick={() =>
                  onChange({
                    combatOptionDisabled: {
                      ...(role.combatOptionDisabled ?? emptyCombatOptions()),
                      [field]: [],
                    },
                    combatOptionExplicitlyEmpty: {
                      ...role.combatOptionExplicitlyEmpty,
                      [field]: false,
                    },
                  })
                }
              >
                Select All {label.toLowerCase()}
              </button>
              <div className="combat-option-list">
                {catalog[field].map((option) => (
                  <label className="check" key={option.id}>
                    <input
                      type="checkbox"
                      disabled={!option.available}
                      checked={
                        option.available && selected[field].includes(option.id)
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
                    {option.id.replaceAll("_", " ")}
                    {option.reason && !option.available
                      ? ` · ${option.reason}`
                      : ""}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
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
          {visibleGroups.some(({ field }) => selected[field].length === 0) && (
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
