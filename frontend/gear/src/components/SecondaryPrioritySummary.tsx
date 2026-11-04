import type {
  JointSolutionDTO,
  OptimizationReply,
  PotionDefinition,
  PotionSummary,
} from "../api/contracts";
import { secondaryPriorities } from "../api/secondaryPriorities";
import {
  boostedSkillChanges,
  noPotionScore,
  potionDisplayName,
  potionGainText,
} from "./potionFormat";

function formatGp(gp: number): string {
  return `${gp.toLocaleString()} GP`;
}

function PotionResult({
  potions,
  skillOverrides,
  catalog,
  gain,
}: {
  potions: PotionSummary;
  skillOverrides: Record<string, number | undefined>;
  catalog: readonly PotionDefinition[];
  gain: string | null;
}) {
  const changes = boostedSkillChanges(potions.boosted_levels, {
    ...skillOverrides,
    ...potions.base_levels,
  });
  const resources = potions.resources ?? [];
  const isAnyPriced =
    potions.cost_per_application_gp != null ||
    resources.some((resource) => resource.cost_per_dose_gp != null);
  const hasDivine = potions.selected_ids.some((id) => id.startsWith("divine"));
  return (
    <section className="panel" aria-label="Selected potions">
      <h2>Combat potions</h2>
      <p>
        {potions.selected_ids
          .map((id) => potionDisplayName(id, catalog))
          .join(", ")}
      </p>
      {gain && (
        <p>
          <strong>{gain}</strong> compared with the best loadout found without
          potions.
        </p>
      )}
      <p>
        Boosted levels:{" "}
        {changes.length ? changes.join(" · ") : "no skill changes"}
      </p>
      {isAnyPriced ? (
        <>
          <p>
            {potions.cost_per_application_gp == null
              ? "Application price unavailable"
              : `${formatGp(potions.cost_per_application_gp)} per complete application`}
            . Separate from equipment budget and attack-resource GP/hour.
          </p>
          {resources.map((resource) => (
            <p key={resource.name}>
              {resource.name}:{" "}
              {resource.cost_per_dose_gp == null
                ? "price unavailable"
                : `${formatGp(resource.cost_per_dose_gp)} per dose`}
            </p>
          ))}
        </>
      ) : (
        <p>Potion prices unavailable.</p>
      )}
      <p>
        Fresh boost only: no decay, duration benefit, drinking downtime or
        survival benefit is modeled.
        {hasDivine ? " Divine potions consume HP when drunk." : ""}
      </p>
    </section>
  );
}

export function SecondaryPrioritySummary({
  result,
  solution,
  potionCatalog = [],
}: {
  result: OptimizationReply;
  solution?: JointSolutionDTO | null;
  potionCatalog?: readonly PotionDefinition[];
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
        <PotionResult
          potions={selected.potions}
          skillOverrides={result.scenario.request.skill_overrides}
          catalog={potionCatalog}
          gain={potionGainText(
            selected.score,
            noPotionScore(result.live?.result.search),
            result.scenario.request.roles.length > 1 ? "weighted DPS" : "DPS",
          )}
        />
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
