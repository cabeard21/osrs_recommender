import type { Draft } from "../api/contracts";
import { EQUIPMENT_ACCESS_LABELS } from "../components/resultFormat";
import { parseGp } from "./scenario";

export interface SubmittedSummary {
  fire_tome_pages?: Draft["fireTomePages"];
  include_untradeables?: boolean;
  budget_gp: number;
  mode: Draft["mode"];
  optimization_mode?: string;
  target: { name: string; defence: number };
  roles: unknown[];
}

/** Human-readable draft differences; the result's own context is compared separately. */
export function describeDraftChanges(
  draft: Draft,
  submitted: SubmittedSummary,
): string[] {
  const changes: string[] = [];
  for (const role of draft.roles) {
    const previous = submitted.roles.find(
      (value) =>
        value !== null &&
        typeof value === "object" &&
        "id" in value &&
        value.id === role.id,
    ) as { onSlayerTask?: boolean; markOfDarkness?: boolean } | undefined;
    if (
      previous &&
      (previous.onSlayerTask ?? false) !== (role.onSlayerTask ?? false)
    )
      changes.push(
        `${role.name} Slayer task: ${previous.onSlayerTask ? "on" : "off"} → ${role.onSlayerTask ? "on" : "off"}`,
      );
    if (
      previous &&
      (previous.markOfDarkness ?? false) !== (role.markOfDarkness ?? false)
    )
      changes.push(
        `${role.name} Mark of Darkness: ${previous.markOfDarkness ? "on" : "off"} → ${role.markOfDarkness ? "on" : "off"}`,
      );
  }
  if (
    (draft.fireTomePages ?? "burnt") !== (submitted.fire_tome_pages ?? "burnt")
  )
    changes.push(
      `Tome of Fire pages: ${submitted.fire_tome_pages ?? "burnt"} → ${draft.fireTomePages ?? "burnt"}`,
    );
  if (
    (draft.includeUntradeables ?? false) !==
    (submitted.include_untradeables ?? false)
  )
    changes.push(
      `Unowned untradeables: ${submitted.include_untradeables ? "considered" : "excluded"} → ${draft.includeUntradeables ? "considered" : "excluded"}`,
    );
  const budget = Number(parseGp(draft.budget));
  if (Number.isFinite(budget) && budget !== submitted.budget_gp)
    changes.push(
      `Budget: ${submitted.budget_gp.toLocaleString("en-US")} → ${budget.toLocaleString("en-US")} GP`,
    );
  const isSingleTarget = submitted.roles.length === 1;
  if (isSingleTarget && draft.target !== submitted.target.name)
    changes.push(`Target: ${submitted.target.name} → ${draft.target}`);
  if (isSingleTarget && Number(draft.defence) !== submitted.target.defence)
    changes.push(
      `Target defence: ${submitted.target.defence} → ${draft.defence}`,
    );
  if (draft.mode !== submitted.mode)
    changes.push(
      `Equipment access: ${EQUIPMENT_ACCESS_LABELS[submitted.mode]} → ${EQUIPMENT_ACCESS_LABELS[draft.mode]}`,
    );
  const draftOptimization = draft.optimizationMode ?? "fast";
  const submittedOptimization = submitted.optimization_mode ?? "fast";
  if (draftOptimization !== submittedOptimization)
    changes.push(
      `Optimization mode: ${submittedOptimization} → ${draftOptimization}`,
    );
  return changes;
}
