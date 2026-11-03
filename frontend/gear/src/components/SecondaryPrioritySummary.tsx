import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";
import { secondaryPriorities } from "../api/secondaryPriorities";

export function SecondaryPrioritySummary({
  result,
  solution,
}: {
  result: OptimizationReply;
  solution?: JointSolutionDTO | null;
}) {
  const priority = result.scenario.request.secondary_priority ?? "default";
  const priorityLabel = secondaryPriorities.find(
    ([value]) => value === priority,
  )?.[1];
  const selected = solution ?? result.live?.result.selected_solution;
  const secondaryValue = selected?.secondary_value;
  return (
    <details
      className="panel result-explanation"
      aria-label="Secondary optimization priority"
    >
      <summary>Secondary priority</summary>
      <p>
        Secondary priority: {priorityLabel} ·{" "}
        {priority === "default"
          ? "inventory / cost / actions / identity ordering"
          : result.source === "fixture"
            ? "not measured in authored fixture"
            : typeof secondaryValue === "number"
              ? priority === "accuracy"
                ? `${(secondaryValue * 100).toFixed(2)}% hit chance`
                : `${secondaryValue.toFixed(2)}${priority === "magic_damage_bonus" ? "%" : " bonus"}`
              : "no feasible measurement"}
        .
      </p>
      <p>
        Weighted ordinary-attack DPS remains the primary objective. Secondary
        priorities break exact DPS ties for the initial selection; the tradeoff
        frontier also explores DPS sacrifices. Bounded search does not guarantee
        the best secondary value.
      </p>
      {priority !== "default" && (
        <p>
          {priority === "balanced_defence"
            ? "Balanced defence is the mean of the five equipment defence bonuses. "
            : priority === "magic_ranged_defence"
              ? "Magic & ranged defence is the mean of the magic and ranged equipment defence bonuses; it does not measure damage reduction. "
              : ""}
          Multi-style values use normalized active-time weights across scored
          roles; utility roles do not contribute.
        </p>
      )}
      {priority === "magic_ranged_defence" &&
        result.source !== "fixture" &&
        selected &&
        Object.entries(selected.loadouts).map(([role, loadout]) => (
          <p key={role}>
            {role} defence bonuses: magic{" "}
            {loadout.performance.bonuses.defence_magic ?? 0} / ranged{" "}
            {loadout.performance.bonuses.defence_ranged ?? 0}
          </p>
        ))}
    </details>
  );
}
