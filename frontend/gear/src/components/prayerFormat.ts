import type {
  PrayerDefinition,
  PrayerModifiers,
  PrayerPolicy,
} from "../api/contracts";

export type PrayerStyle = "Melee" | "Ranged" | "Magic" | "Defence";

const STYLE_ORDER: readonly PrayerStyle[] = [
  "Melee",
  "Ranged",
  "Magic",
  "Defence",
];

const GROUP_STYLES: Readonly<Record<string, PrayerStyle>> = {
  attack: "Melee",
  strength: "Melee",
  ranged: "Ranged",
  magic: "Magic",
  defence: "Defence",
};

/** Percentage modifiers shown to the user, in display order. */
const EFFECT_LABELS: readonly [keyof PrayerModifiers, string][] = [
  ["attack", "Attack"],
  ["strength", "Strength"],
  ["ranged_accuracy", "Ranged accuracy"],
  ["ranged_strength", "Ranged strength"],
  ["magic_accuracy", "Magic accuracy"],
  ["magic_damage", "Magic damage"],
  ["defence", "Defence"],
];

function boost(modifiers: PrayerModifiers, key: keyof PrayerModifiers): number {
  return key === "magic_damage" ? modifiers[key] : modifiers[key] - 100;
}

/** The combat style a prayer boosts; defence-only prayers are "Defence". */
export function prayerStyle(prayer: PrayerDefinition): PrayerStyle {
  const mods = prayer.modifiers;
  if (!mods) return GROUP_STYLES[prayer.group ?? ""] ?? "Defence";
  if (mods.attack > 100 || mods.strength > 100) return "Melee";
  if (mods.ranged_accuracy > 100 || mods.ranged_strength > 100) return "Ranged";
  if (mods.magic_accuracy > 100 || mods.magic_damage > 0) return "Magic";
  return "Defence";
}

/** "Attack +20% · Strength +23% · Defence +25%", or "" when unknown. */
export function prayerEffectText(prayer: PrayerDefinition): string {
  const mods = prayer.modifiers;
  if (!mods) return "";
  return EFFECT_LABELS.filter(([key]) => boost(mods, key) > 0)
    .map(([key, label]) => `${label} +${boost(mods, key)}%`)
    .join(" · ");
}

/** Catalog grouped by style, preserving catalog order within each group. */
export function groupPrayers(
  catalog: readonly PrayerDefinition[],
): [PrayerStyle, PrayerDefinition[]][] {
  return STYLE_ORDER.map(
    (style) =>
      [style, catalog.filter((p) => prayerStyle(p) === style)] as [
        PrayerStyle,
        PrayerDefinition[],
      ],
  ).filter(([, rows]) => rows.length > 0);
}

export function isPrayerAvailable(prayer: PrayerDefinition): boolean {
  return prayer.availability === "satisfied";
}

/** One-click allow-lists for optimize mode, limited to available prayers. */
export function prayerQuickSelections(
  catalog: readonly PrayerDefinition[],
): [string, string[]][] {
  const available = catalog.filter(isPrayerAvailable);
  const byStyle = (["Melee", "Ranged", "Magic"] as const)
    .map(
      (style) =>
        [
          style,
          available.filter((p) => prayerStyle(p) === style).map((p) => p.id),
        ] as [string, string[]],
    )
    .filter(([, ids]) => ids.length > 0);
  return [
    ["All available", available.map((p) => p.id)],
    ...byStyle,
    ["None", []],
  ];
}

/** "Knight waves unlock is unknown; Prayer level 70 required". */
export function prayerReasonText(reasons: readonly string[] | undefined) {
  const text = (reasons ?? [])
    .map((reason) => reason.replaceAll("_", " "))
    .map((reason) => reason.charAt(0).toUpperCase() + reason.slice(1))
    .join("; ");
  return text || "Availability unknown";
}

/** The first selected prayer that cannot be active alongside `prayer`. */
export function conflictingPrayer(
  prayer: PrayerDefinition,
  selected: readonly PrayerDefinition[],
): PrayerDefinition | undefined {
  return selected.find(
    (other) =>
      other.id !== prayer.id &&
      (other.conflicts?.includes(prayer.id) ||
        prayer.conflicts?.includes(other.id)),
  );
}

/** Catalog name for a prayer id; title-cases the id when the catalog lacks it. */
export function prayerDisplayName(
  id: string,
  catalog: readonly PrayerDefinition[],
): string {
  return (
    catalog.find((p) => p.id === id)?.name ??
    id
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  );
}

/** Collapsed-panel summary: "Off", "Optimize · 3 allowed", "Fixed · Piety". */
export function prayerPolicySummary(
  policy: PrayerPolicy | undefined,
  catalog: readonly PrayerDefinition[],
): string {
  if (!policy || policy.mode === "disabled") return "Off";
  if (policy.mode === "optimize") {
    return `Optimize · ${policy.allowed_ids.length} allowed`;
  }
  return policy.selected_ids.length
    ? `Fixed · ${policy.selected_ids.map((id) => prayerDisplayName(id, catalog)).join(", ")}`
    : "Fixed · none selected";
}
