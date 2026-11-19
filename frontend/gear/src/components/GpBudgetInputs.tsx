import {
  BUDGET_PRESETS,
  SLIDER_MAX,
  budgetToSlider,
  sliderToBudget,
} from "../state/budget";
import { parseGp } from "../state/scenario";
import { FieldError, fieldProps } from "./FieldError";

export function GpBudgetInputs({
  name,
  label,
  sliderLabel,
  value,
  error,
  onChange,
  minimum,
  presets = false,
}: {
  name: string;
  label: string;
  sliderLabel: string;
  value: string;
  error?: string;
  onChange: (value: string) => void;
  minimum?: number;
  presets?: boolean;
}) {
  const gp = error ? 0 : Number(parseGp(value));
  return (
    <>
      <label>
        {label}
        <input
          inputMode="numeric"
          placeholder="10m, 500k or 12345"
          data-run-on-enter
          value={value}
          {...fieldProps(name, error)}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      <FieldError id={name} message={error} />
      {!error && gp > 0 && (
        <span className="numeric">{gp.toLocaleString()} GP</span>
      )}
      <input
        aria-label={sliderLabel}
        aria-valuetext={`${gp.toLocaleString()} GP`}
        type="range"
        min="0"
        max={SLIDER_MAX}
        step="1"
        value={budgetToSlider(gp, minimum)}
        onChange={(e) =>
          onChange(String(sliderToBudget(Number(e.target.value), minimum)))
        }
      />
      {presets && (
        <div
          className="budget-presets"
          role="group"
          aria-label="Budget presets"
        >
          {BUDGET_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={value === preset}
              onClick={() => onChange(preset)}
            >
              {preset}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
