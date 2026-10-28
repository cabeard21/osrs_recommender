import type { CombatOption, Role } from "../api/contracts";

export function CombatOptionSummary({
  option,
  role,
  weapon,
}: {
  option?: CombatOption;
  role: Pick<Role, "style" | "attackType" | "stance" | "spell" | "combatOptions">;
  weapon: string;
}) {
  if (!option && role.combatOptions) {
    return <p className="notice">Selected combat option unavailable in this result.</p>;
  }
  const attack = option?.attack_type ?? (role.style === "melee" ? role.attackType : role.style);
  const stance = option?.stance ?? role.stance;
  const spell = option?.powered_attack ?? option?.spell ?? (role.style === "magic" ? role.spell : null);
  return (
    <p aria-label="Selected combat configuration">
      {weapon} · {attack} · {stance}{spell ? ` · ${spell.replaceAll("_", " ")}` : ""}
    </p>
  );
}
