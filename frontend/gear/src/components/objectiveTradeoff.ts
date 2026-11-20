import type { JointSolutionDTO } from "../api/contracts";
import type { ObjectiveDefinition } from "../api/objectives";

export interface TradeoffPoint {
  id: string;
  score: number;
  objective_values: Record<string, number | null>;
  purchase_cost_gp: number;
  wilderness_loss_gp?: number | null;
  maximum_actions: number;
}

export function tradeoffPoint(
  id: string,
  solution: JointSolutionDTO,
): TradeoffPoint {
  return {
    id,
    score: solution.score,
    objective_values: solution.objective_values ?? {},
    purchase_cost_gp: solution.purchase_cost_gp,
    wilderness_loss_gp: solution.wilderness_risk?.loss_gp,
    maximum_actions: solution.maximum_actions,
  };
}

export function formatTradeoffValue(
  value: number | null | undefined,
  definition?: ObjectiveDefinition,
) {
  if (value == null || !Number.isFinite(value)) return "Unavailable";
  if (definition?.unit === "probability") return (value * 100).toFixed(2) + "%";
  if (definition?.unit === "GP") return value.toLocaleString();
  if (definition?.unit === "percent") return value.toFixed(2) + "%";
  if (definition?.unit === "roll") return (value / 1000).toFixed(2) + "k";
  if (definition?.unit === "GP/damage") return value.toFixed(4);
  return value.toFixed(3);
}
