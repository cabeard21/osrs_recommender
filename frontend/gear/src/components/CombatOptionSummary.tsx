import type {
  CombatOption,
  CombatPerformance,
  PrayerDefinition,
  Preparation,
  Role,
} from "../api/contracts";
import { prayerDisplayName, prayerEffectText } from "./prayerFormat";

function PrayerSummary({
  ids,
  catalog,
}: {
  ids: readonly string[];
  catalog: readonly PrayerDefinition[];
}) {
  const effects = ids
    .map((id) => catalog.find((p) => p.id === id))
    .filter((p): p is PrayerDefinition => p !== undefined)
    .map(prayerEffectText)
    .filter(Boolean);
  return (
    <p aria-label="Active combat prayers">
      Prayers:{" "}
      {ids.length
        ? ids.map((id) => prayerDisplayName(id, catalog)).join(", ")
        : "None"}
      {effects.length > 0 && <small>{effects.join(" · ")}</small>}
    </p>
  );
}

export function CombatOptionSummary({
  option,
  role,
  weapon,
  performance,
  preparations = [],
  prayerIds,
  prayerCatalog = [],
  itemName,
}: {
  option?: CombatOption;
  role: Pick<
    Role,
    "style" | "attackType" | "stance" | "spell" | "combatOptions"
  >;
  weapon: string;
  performance?: CombatPerformance;
  preparations?: readonly Preparation[];
  prayerIds?: string[];
  prayerCatalog?: readonly PrayerDefinition[];
  itemName?: (id: number) => string;
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
    (option?.powered_attack ? "Built-in spell" : null) ??
    option?.spell ??
    (role.style === "magic" ? role.spell : null);
  const weakness = performance?.elemental_weakness;
  const hopper = performance?.aquanite_hopper;
  return (
    <>
      <p aria-label="Selected combat configuration">
        {weapon} · {attack} · {stance}
        {spell ? ` · ${spell.replaceAll("_", " ")}` : ""}
      </p>
      {preparations.map((p) => (
        <p className="notice" key={p.usable_item_id}>
          {p.message}
        </p>
      ))}
      {prayerIds && <PrayerSummary ids={prayerIds} catalog={prayerCatalog} />}
      {performance?.leafy_bonus && (
        <p aria-label="Leafy weapon effect">
          Leaf-bladed battleaxe: +17.5% damage against this leafy target
        </p>
      )}
      {performance?.seeking_arrow_bonus && (
        <p aria-label="Seeking arrow effect">
          Seeking broad arrows: accurate-hit minimum 3 before flat armour;
          misses remain 0
        </p>
      )}
      {performance?.slayer_effects?.map((effect) => (
        <p
          aria-label="Slayer task effect"
          key={`${effect.item_id}-${effect.kind}`}
        >
          Slayer task ·{" "}
          {itemName?.(effect.item_id) ?? `item #${effect.item_id}`}:{" "}
          {effect.kind === "magic_dart"
            ? `Magic Dart base max hit ${effect.base_max_hit}`
            : `+${Number(((effect.accuracy_numerator / effect.denominator - 1) * 100).toFixed(2))}% accuracy and damage`}
        </p>
      ))}
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
      {performance?.bolt_effect && (
        <>
          <p aria-label="Enchanted bolt effect">
            {hopper ? "Primary shot: " : ""}
            {performance.bolt_effect.family} bolt effect ·{" "}
            {(performance.bolt_effect.proc_chance * 100).toFixed(1)}% proc
            chance
            {` · ${(performance.bolt_effect.activation_probability * 100).toFixed(1)}% activation per shot`}
            {performance.bolt_effect.target_hitpoints != null
              ? ` · DPS at ${performance.bolt_effect.target_hitpoints} HP`
              : ""}
            {` · total max ${performance.bolt_effect.total_max_hit}`}
            {` · expected damage ${performance.bolt_effect.expected_damage_per_attack.toFixed(2)} per shot (${performance.bolt_effect.expected_damage_delta >= 0 ? "+" : ""}${performance.bolt_effect.expected_damage_delta.toFixed(2)} from effect)`}
            {` · ${performance.bolt_effect.diary_boosted ? "Kandarin Hard boost applied" : "Base proc rate"}`}
          </p>
          <p>
            Ordinary hit: max {performance.max_hit} ·{" "}
            {((performance.accuracy ?? 0) * 100).toFixed(1)}% accuracy
          </p>
        </>
      )}
      {hopper && (
        <>
          <p aria-label="Aquanite hopper effect">
            {hopper.approximate ? "Approximate " : ""}Aquanite hopper effect
            {` · ${(hopper.proc_chance * 100).toFixed(1)}% extra-shot chance`}
            {` · On activation: secondary max ${hopper.secondary_max_hit}, ${(hopper.secondary_accuracy * 100).toFixed(1)}% accuracy`}
            {` · +${hopper.expected_damage_delta.toFixed(2)} expected damage per attack`}
            {performance?.attack_interval != null &&
            performance.attack_interval > 0
              ? ` · +${(hopper.expected_damage_delta / performance.attack_interval).toFixed(3)} estimated DPS`
              : ""}
            {` · ${hopper.expected_ammunition_per_attack.toFixed(2)} expected bolts per attack`}
          </p>
          {hopper.assumptions.map((assumption) => (
            <p key={assumption}>{assumption}</p>
          ))}
        </>
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
      {performance?.tome_bonus && (
        <p aria-label="Elemental tome effect">
          {performance.tome_bonus.element[0].toUpperCase() +
            performance.tome_bonus.element.slice(1)}{" "}
          tome: +{performance.tome_bonus.damage_percent}% damage
          {performance.tome_bonus.accuracy_percent > 0 &&
            `; +${performance.tome_bonus.accuracy_percent}% attack roll`}
          {performance.tome_bonus.fire_pages &&
            `; ${performance.tome_bonus.fire_pages} pages; successful minimum hit ${performance.tome_bonus.minimum_hit}`}
        </p>
      )}
      {performance?.elemental_amulet_bonus && (
        <p aria-label="Elemental amulet effect">
          Elemental amulet effect: +
          {performance.elemental_amulet_bonus.base_max_hit_bonus} base max hit
          before damage and weakness bonuses
        </p>
      )}
      {performance && performance.limitations.length > 0 && (
        <details>
          <summary>Combat model limitations</summary>
          {performance.limitations.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </details>
      )}
    </>
  );
}
