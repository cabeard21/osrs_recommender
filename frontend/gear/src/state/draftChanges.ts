import type { Draft, WildernessPolicy } from "../api/contracts";
import {
  DEFAULT_WILDERNESS_SPELL_CASTS,
  MAX_WILDERNESS_SPELL_CASTS,
  wildernessMayUseMagic,
  fixedTrip,
  limitTripLoss,
  wildernessRiskCap,
} from "../api/wilderness";
import { EQUIPMENT_ACCESS_LABELS } from "../components/resultFormat";
import { MAX_BUDGET_GP } from "./budget";
import { parseGp } from "./scenario";

export interface SubmittedSummary {
  objectives?: Draft["objectives"];
  fire_tome_pages?: Draft["fireTomePages"];
  include_untradeables?: boolean;
  budget_gp: number;
  wilderness?: WildernessPolicy;
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
    ) as
      | {
          onSlayerTask?: boolean;
          markOfDarkness?: boolean;
          safeSpotting?: boolean;
          fightDurationSeconds?: string;
        }
      | undefined;
    if (
      previous &&
      (previous.safeSpotting ?? false) !== (role.safeSpotting ?? false)
    )
      changes.push(
        `${role.name} safe spotting changed to ${role.safeSpotting ? "on" : "off"}`,
      );
    if (
      previous &&
      (previous.fightDurationSeconds ?? "60") !==
        (role.fightDurationSeconds ?? "60")
    )
      changes.push(
        `${role.name} status duration changed to ${role.fightDurationSeconds ?? "60"} seconds`,
      );
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
  const submittedBudget =
    submitted.wilderness &&
    !fixedTrip(submitted) &&
    submitted.wilderness.attacks_per_setup == null &&
    submitted.wilderness.max_loss_gp == null
      ? MAX_BUDGET_GP
      : submitted.budget_gp;
  if (Number.isFinite(budget) && budget !== submittedBudget)
    changes.push(
      `Budget: ${submittedBudget.toLocaleString("en-US")} → ${budget.toLocaleString("en-US")} GP`,
    );
  const maxLoss =
    fixedTrip(draft) && !limitTripLoss(draft)
      ? null
      : Number(parseGp(draft.wildernessRiskBudget ?? "0"));
  const submittedLossCap = wildernessRiskCap(submitted);
  if (
    draft.wilderness &&
    submittedLossCap !== undefined &&
    (maxLoss === null || Number.isFinite(maxLoss)) &&
    maxLoss !== submittedLossCap
  )
    changes.push(
      `Max gear loss: ${submittedLossCap?.toLocaleString("en-US") ?? "No cap"} → ${maxLoss?.toLocaleString("en-US") ?? "No cap"} GP`,
    );
  const casts = Number(
    draft.wildernessSpellCasts ?? DEFAULT_WILDERNESS_SPELL_CASTS,
  );
  const submittedCasts =
    submitted.wilderness?.attacks_per_setup ??
    submitted.wilderness?.spell_casts;
  if (
    draft.wilderness &&
    (fixedTrip(draft) || wildernessMayUseMagic(draft.roles)) &&
    submittedCasts != null &&
    Number.isSafeInteger(casts) &&
    casts >= 1 &&
    casts <= MAX_WILDERNESS_SPELL_CASTS &&
    casts !== submittedCasts
  )
    changes.push(
      `${fixedTrip(draft) ? "Attacks per combat setup" : "Casts per Magic setup"} changed from ${submittedCasts.toLocaleString("en-US")} to ${casts.toLocaleString("en-US")}`,
    );
  if (Boolean(draft.wilderness) !== Boolean(submitted.wilderness))
    changes.push(`Wilderness ${draft.wilderness ? "enabled" : "disabled"}`);
  else if (
    draft.wilderness?.depth !== submitted.wilderness?.depth ||
    draft.wilderness?.skulled !== submitted.wilderness?.skulled ||
    draft.wilderness?.protect_item !== submitted.wilderness?.protect_item
  )
    changes.push("Wilderness death settings changed");
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
