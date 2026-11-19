export const MAX_BUDGET_GP = 2_147_483_647;
export const SLIDER_MAX = 100;
export const BUDGET_PRESETS = ["1m", "10m", "100m", "1b"] as const;

const MIN_NONZERO_GP = 100_000;

function roundToTwoFigures(value: number): number {
  const magnitude = 10 ** (Math.floor(Math.log10(value)) - 1);
  return Math.round(value / magnitude) * magnitude;
}

/** OSRS budgets span several orders of magnitude, so the slider is logarithmic. */
export function sliderToBudget(
  position: number,
  minimum = MIN_NONZERO_GP,
): number {
  if (position <= 0) return 0;
  if (position >= SLIDER_MAX) return MAX_BUDGET_GP;
  const fraction = (position - 1) / (SLIDER_MAX - 1);
  const logRange = Math.log(MAX_BUDGET_GP / minimum);
  return Math.round(roundToTwoFigures(minimum * Math.exp(fraction * logRange)));
}

export function budgetToSlider(
  budget: number,
  minimum = MIN_NONZERO_GP,
): number {
  if (!(budget > 0)) return 0;
  if (budget <= minimum) return 1;
  const fraction =
    Math.log(budget / minimum) / Math.log(MAX_BUDGET_GP / minimum);
  return Math.min(SLIDER_MAX, Math.round(1 + fraction * (SLIDER_MAX - 1)));
}
