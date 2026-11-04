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
    <>
      {selected?.potions && selected.potions.selected_ids.length > 0 && (
        <section className="panel" aria-label="Selected potions">
          <h2>Combat potions</h2>
          <p>
            {selected.potions.selected_ids
              .map((id) => id.replaceAll("_", " "))
              .join(", ")}
          </p>
          <p>
            Freshly boosted levels:{" "}
            {Object.entries(selected.potions.boosted_levels)
              .map(
                ([skill, level]) =>
                  `${skill} ${selected.potions?.base_levels?.[skill] ?? result.scenario.request.skill_overrides[skill] ?? "base"} → ${level}`,
              )
              .join(" · ")}
          </p>
          <p>
            {selected.potions.cost_per_application_gp == null
              ? "Potion price unavailable"
              : `${selected.potions.cost_per_application_gp.toLocaleString()} GP per complete application`}
            . Separate from equipment budget and attack-resource GP/hour.
          </p>
          {selected.potions.resources?.map((resource) => (
            <p key={resource.name}>
              {resource.name}:{" "}
              {resource.cost_per_dose_gp == null
                ? "price unavailable"
                : `${resource.cost_per_dose_gp.toLocaleString()} GP per dose`}
            </p>
          ))}
          <p>
            No decay, duration benefit, drinking downtime or survival benefit is
            modeled. Divine potions consume HP when drunk.
          </p>
        </section>
      )}
      <details
        className="panel result-explanation"
        aria-label="Tradeoff metric explanation"
      >
        <summary>Tradeoff metric</summary>
        <p>
          Tradeoff metric: {priorityLabel} ·{" "}
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
          The frontier explores DPS and the selected metric as equal objectives.
          The initial selection has the highest DPS found. Bounded search does
          not guarantee either global optimum or a complete frontier.
        </p>
        {priority !== "default" && (
          <p>
            {priority === "balanced_defence"
              ? "Balanced defence is the mean of the five equipment defence bonuses. "
              : priority === "magic_ranged_defence"
                ? "Magic & ranged defence is the lower of the magic and ranged equipment defence bonuses; it does not measure damage reduction. "
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
    </>
  );
}
