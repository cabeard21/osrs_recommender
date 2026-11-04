import type { CombatTarget } from "../api/contracts";

export interface NpcEntrySummary {
  key: string;
  name: string;
  variant: string;
  combat_level: number;
  support_status: string;
}

/**
 * "Goblin · Level 13": drops "Standard" and "supported", and never repeats the
 * level when the variant already starts with it ("Level 2 (armed)").
 */
export function npcEntryLabel(entry: NpcEntrySummary): string {
  const level = `Level ${entry.combat_level}`;
  const variant =
    entry.variant && entry.variant !== "Standard" ? entry.variant : "";
  const startsWithLevel = variant === level || variant.startsWith(`${level} `);
  const parts = startsWithLevel
    ? [entry.name, variant]
    : [entry.name, ...(variant ? [variant] : []), level];
  if (entry.support_status !== "supported")
    parts.push(entry.support_status.replaceAll("_", " "));
  return parts.join(" · ");
}

/** Keeps the catalog's name order (relevance) but lists each name's variants by level. */
export function sortNpcEntries<T extends NpcEntrySummary>(entries: T[]): T[] {
  const nameRank = new Map<string, number>();
  entries.forEach((entry) => {
    if (!nameRank.has(entry.name)) nameRank.set(entry.name, nameRank.size);
  });
  return [...entries].sort(
    (a, b) =>
      nameRank.get(a.name)! - nameRank.get(b.name)! ||
      a.combat_level - b.combat_level,
  );
}

const BONUS_ORDER = ["stab", "slash", "crush", "magic", "ranged"];

/** One-line stat summary; every bonus is labelled as a defence bonus. */
export function npcStatSummary(target: CombatTarget): string {
  return npcStatLines(target).join(" · ");
}

/** The stat summary split into short lines: levels, defence bonuses, weakness. */
export function npcStatLines(target: CombatTarget): string[] {
  const bonuses = BONUS_ORDER.map(
    (key) => `${key} ${target.bonuses[key] ?? 0}`,
  ).join(" / ");
  const rangedBonus = target.bonuses.ranged ?? 0;
  const ranged = (["light", "standard", "heavy"] as const)
    .map((kind) => [kind, target[`ranged_${kind}`]] as const)
    .filter(([, value]) => value !== undefined && value !== null);
  // The light/standard/heavy split only adds information when it differs.
  const rangedDiffers = ranged.some(([, value]) => value !== rangedBonus);
  const parts = [
    `Defence ${target.defence_level} · Magic ${target.magic_level}`,
    `Defence bonuses: ${bonuses}${
      rangedDiffers
        ? ` (ranged ${ranged.map(([kind, value]) => `${kind} ${value}`).join(" / ")})`
        : ""
    }`,
  ];
  if (target.weakness_element)
    parts.push(
      `Weak to ${target.weakness_element} (${target.weakness_percent ?? 0}%)`,
    );
  return parts;
}

/** Readable labels for the NPC stat override inputs, keyed by target field. */
export const NPC_OVERRIDE_LABELS: Readonly<Record<string, string>> = {
  defence_level: "Defence level",
  magic_level: "Magic level",
  weakness_percent: "Weakness %",
  "bonuses.stab": "Stab defence",
  "bonuses.slash": "Slash defence",
  "bonuses.crush": "Crush defence",
  "bonuses.magic": "Magic defence",
  "bonuses.ranged": "Ranged defence",
  ranged_light: "Ranged defence (light)",
  ranged_standard: "Ranged defence (standard)",
  ranged_heavy: "Ranged defence (heavy)",
};

const RECENT_KEY = "gear.recentNpcTargets";
const MAX_RECENT = 6;

function isSummary(value: unknown): value is NpcEntrySummary {
  const row = value as NpcEntrySummary | null;
  return (
    !!row &&
    typeof row.key === "string" &&
    typeof row.name === "string" &&
    typeof row.variant === "string" &&
    typeof row.combat_level === "number" &&
    typeof row.support_status === "string"
  );
}

/** Recently chosen NPCs, newest first. Storage may be unavailable. */
export function readRecentNpcs(): NpcEntrySummary[] {
  try {
    const parsed: unknown = JSON.parse(
      localStorage.getItem(RECENT_KEY) ?? "[]",
    );
    return Array.isArray(parsed) ? parsed.filter(isSummary) : [];
  } catch {
    return [];
  }
}

export function rememberNpc(entry: NpcEntrySummary): void {
  const row: NpcEntrySummary = {
    key: entry.key,
    name: entry.name,
    variant: entry.variant,
    combat_level: entry.combat_level,
    support_status: entry.support_status,
  };
  const next = [
    row,
    ...readRecentNpcs().filter((recent) => recent.key !== row.key),
  ].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Recent targets are a convenience; ignore storage failures.
  }
}
