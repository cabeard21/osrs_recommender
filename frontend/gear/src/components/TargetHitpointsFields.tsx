import { useId } from "react";
import type { CombatTarget, Role } from "../api/contracts";
import { targetFieldErrors } from "../state/setupValidation";
import { FieldError, fieldProps } from "./FieldError";

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
  const fieldPrefix = useId();
  const errors = targetFieldErrors(target, inputs);
  const hpSummary =
    errors.hitpoints || errors.current_hitpoints
      ? "Check hitpoints"
      : target.current_hitpoints != null
        ? `${target.current_hitpoints} current HP`
        : target.hitpoints != null
          ? `${target.hitpoints} base HP`
          : null;
  return (
    <details className="control-help">
      <summary>
        Target hitpoints
        {hpSummary && <small> · {hpSummary}</small>}
      </summary>
      {(["hitpoints", "current_hitpoints"] as const).map((field) => (
        <div key={field}>
          <label>
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
              {...fieldProps(`${fieldPrefix}-${field}`, errors[field])}
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
          <FieldError id={`${fieldPrefix}-${field}`} message={errors[field]} />
        </div>
      ))}
      <p>
        Ruby bolt DPS is evaluated at current HP, defaulting to base HP. It is
        not an average over a kill.
      </p>
    </details>
  );
}
