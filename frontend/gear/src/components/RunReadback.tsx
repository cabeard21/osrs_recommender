import type { Draft, Role } from "../api/contracts";
import { legacyObjectives, objectiveLabel } from "../api/objectives";
import { fixedTrip, limitTripLoss } from "../api/wilderness";
import { useGear } from "../state/GearProvider";
import { draftFieldErrors, parseGp } from "../state/scenario";
import { effectiveRoleTarget } from "./RoleTargetEditor";
import { EQUIPMENT_ACCESS_LABELS } from "./resultFormat";

export function roleDiscipline(role: Role): string {
  if (role.utility) return "Utility";
  if (role.autoDiscipline) {
    const allowed = role.allowedDisciplines ?? ["melee", "ranged", "magic"];
    return `Auto (${allowed.join(", ") || "choose styles"})`;
  }
  return role.style.charAt(0).toUpperCase() + role.style.slice(1);
}

export function objectiveSummary(draft: Draft) {
  const goals = draft.objectives ?? legacyObjectives(draft.secondaryPriority);
  return goals.length
    ? ["DPS", ...goals.map(objectiveLabel)].join(" + ")
    : "DPS only";
}

export function RunReadback() {
  const { current, state } = useGear();
  const draft = current.draft;
  const errors = draftFieldErrors(draft);
  const targets = Array.from(
    new Set(
      draft.roles
        .filter((role) => !role.utility)
        .map((role) => effectiveRoleTarget(role, draft).name),
    ),
  );
  const single = state.mode === "single";
  const cap = draft.wilderness
    ? fixedTrip(draft) && !limitTripLoss(draft)
      ? "No loss cap"
      : errors.wildernessRiskBudget
        ? "Check loss cap"
        : `${Number(parseGp(draft.wildernessRiskBudget ?? "0")).toLocaleString()} GP loss cap`
    : null;

  return (
    <p className="run-readback" aria-label="Next run settings">
      {[
        targets.filter(Boolean).join(" / ") || "Choose a target",
        single && draft.roles[0]
          ? roleDiscipline(draft.roles[0])
          : `${draft.roles.length} configurations`,
        errors.budget
          ? "Check budget"
          : `${Number(parseGp(draft.budget)).toLocaleString()} GP`,
        EQUIPMENT_ACCESS_LABELS[draft.mode],
        objectiveSummary(draft),
        draft.optimizationMode === "thorough" ? "Thorough" : "Fast",
        !single &&
          `${draft.maxActions || "—"} actions · ${draft.supplies || "—"} reserved supply slots`,
        cap,
      ]
        .filter(Boolean)
        .join(" · ")}
    </p>
  );
}
