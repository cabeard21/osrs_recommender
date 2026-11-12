import type { CombatTarget, Role } from "../api/contracts";

/** Static hitpoints for HP-dependent bolt damage, shared by all target editors. */
export function TargetHitpointsFields({
  target,
  inputs = {},
  fixedBase = false,
  onChange,
}: {
  target: CombatTarget;
  inputs?: Record<string, string>;
  fixedBase?: boolean;
  onChange: (patch: Partial<Role>) => void;
}) {
  return (
    <div>
      {(["hitpoints", "current_hitpoints"] as const).map((field) => (
        <label key={field}>
          {field === "hitpoints"
            ? "Target base hitpoints"
            : "Target current hitpoints"}
          <input
            type="number"
            min="1"
            max="1000000"
            readOnly={field === "hitpoints" && fixedBase}
            placeholder={
              field === "current_hitpoints"
                ? String(target.hitpoints ?? "Unknown")
                : "Unknown"
            }
            value={inputs[field] ?? target[field] ?? ""}
            onChange={(event) =>
              onChange({
                combatTarget: {
                  ...target,
                  [field]: event.target.value.trim()
                    ? Number(event.target.value)
                    : null,
                },
                targetInputs: { ...inputs, [field]: event.target.value },
              })
            }
          />
        </label>
      ))}
      <p>
        Ruby bolt DPS is evaluated at current HP, defaulting to base HP. It is
        not an average over a kill.
      </p>
    </div>
  );
}
