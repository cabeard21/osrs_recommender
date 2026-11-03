import type { CombatOption, CombatPerformance, Role } from "../api/contracts";

export function CombatOptionSummary({
  option,
  role,
  weapon,
  performance,
}: {
  option?: CombatOption;
  role: Pick<
    Role,
    "style" | "attackType" | "stance" | "spell" | "combatOptions"
  >;
  weapon: string;
  performance?: CombatPerformance;
}) {
  if (!option && role.combatOptions) {
    return (
      <p className="notice">
        Selected combat option unavailable in this result.
      </p>
    );
  }
  const attack =
    option?.attack_type ??
    (role.style === "melee" ? role.attackType : role.style);
  const stance = option?.stance ?? role.stance;
  const spell =
    option?.powered_attack ??
    option?.spell ??
    (role.style === "magic" ? role.spell : null);
  const weakness = performance?.elemental_weakness;
  return (
    <>
      <p aria-label="Selected combat configuration">
        {weapon} · {attack} · {stance}
        {spell ? ` · ${spell.replaceAll("_", " ")}` : ""}
      </p>
      {performance?.hitsplats && performance.hitsplats.length > 1 && (
        <p aria-label="Hitsplat details">
          {performance.hitsplats
            .map(
              (hit, index) =>
                `Hit ${index + 1}: max ${hit.max_hit}, ${(hit.accuracy * 100).toFixed(1)}% accuracy`,
            )
            .join("; ")}
        </p>
      )}
      {weakness && (
        <p aria-label="Elemental weakness effect">
          {weakness.element
            ? `${weakness.element[0].toUpperCase()}${weakness.element.slice(1)} weakness ${weakness.percent}%`
            : "No elemental weakness"}
          {weakness.applied
            ? ` applied · +${weakness.max_hit_bonus} max hit · +${weakness.attack_roll_bonus} attack roll`
            : ` · ${weakness.reason ?? "Weakness not applied."}`}
        </p>
      )}
    </>
  );
}
