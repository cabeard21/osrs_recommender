import type { PotionDefinition } from "../api/contracts";

export type PotionGroup = "Regular" | "Super" | "Divine";

const GROUP_ORDER: readonly PotionGroup[] = ["Regular", "Super", "Divine"];
const SKILL_ORDER = [
  "attack",
  "strength",
  "defence",
  "ranged",
  "magic",
  "hitpoints",
];

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Catalog name for a potion id; humanizes the id when the catalog lacks it. */
export function potionDisplayName(
  id: string,
  catalog: readonly PotionDefinition[],
): string {
  return (
    catalog.find((potion) => potion.id === id)?.name ??
    capitalize(id.replaceAll("_", " "))
  );
}

/** "Attack 75 → 85" for each skill the potions actually raise. */
export function boostedSkillChanges(
  boosted: Readonly<Record<string, number>>,
  base: Readonly<Record<string, number | undefined>>,
): string[] {
  const rank = (skill: string) => {
    const index = SKILL_ORDER.indexOf(skill);
    return index === -1 ? SKILL_ORDER.length : index;
  };
  return Object.entries(boosted)
    .filter(([skill, level]) => base[skill] !== level)
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(
      ([skill, level]) =>
        `${capitalize(skill)} ${base[skill] ?? "base"} → ${level}`,
    );
}

function groupOf(potion: PotionDefinition): PotionGroup {
  const name = potion.name.toLowerCase();
  if (name.startsWith("divine")) return "Divine";
  if (name.startsWith("super")) return "Super";
  return "Regular";
}

/** Preset allow-lists offered as one-click shortcuts. */
export function potionQuickSelections(
  catalog: readonly PotionDefinition[],
): [string, string[]][] {
  const idsIn = (...groups: PotionGroup[]) =>
    catalog
      .filter((potion) => groups.includes(groupOf(potion)))
      .map((potion) => potion.id);
  return [
    ["All", catalog.map((potion) => potion.id)],
    ["Supers only", idsIn("Super")],
    ["No divines", idsIn("Regular", "Super")],
    ["None", []],
  ];
}

/**
 * Best score found without potions, read from the optimizer's free-form search
 * metadata. Uses the highest swap limit, matching the default selection.
 */
export function noPotionScore(
  search: Readonly<Record<string, unknown>> | undefined,
): number | null {
  const selection = search?.potion_selection as
    { no_potion_score_by_swap_limit?: unknown } | undefined;
  const scores = selection?.no_potion_score_by_swap_limit;
  if (!Array.isArray(scores) || scores.length === 0) return null;
  const last: unknown = scores[scores.length - 1];
  return typeof last === "number" && Number.isFinite(last) ? last : null;
}

/** "+3.21 DPS (+12.4%)" for the potion gain, or null when unmeasurable. */
export function potionGainText(
  score: number | undefined,
  baseline: number | null,
  unit: string,
): string | null {
  if (score === undefined || baseline === null) return null;
  const gain = score - baseline;
  const sign = gain >= 0 ? "+" : "−";
  const percent =
    baseline > 0
      ? ` (${sign}${Math.abs((100 * gain) / baseline).toFixed(1)}%)`
      : "";
  return `${sign}${Math.abs(gain).toFixed(2)} ${unit}${percent}`;
}

/** Catalog grouped by family, preserving catalog order within each group. */
export function groupPotions(
  catalog: readonly PotionDefinition[],
): [PotionGroup, PotionDefinition[]][] {
  return GROUP_ORDER.map(
    (group) =>
      [group, catalog.filter((potion) => groupOf(potion) === group)] as [
        PotionGroup,
        PotionDefinition[],
      ],
  ).filter(([, rows]) => rows.length > 0);
}
