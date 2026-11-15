import type {
  PotionPolicy,
  CombatOptionAvailability,
  CombatOptionCapabilities,
  CombatOptionSelection,
  GearContext,
  Role,
  Style,
} from "./contracts";

const attackTypes: Record<Style, string[]> = {
  melee: ["stab", "slash", "crush"],
  ranged: ["light", "standard", "heavy"],
  magic: ["magic"],
};
const stances: Record<Style, string[]> = {
  melee: ["accurate", "aggressive", "defensive", "controlled"],
  ranged: ["accurate", "rapid", "longrange"],
  magic: ["accurate", "defensive", "longrange"],
};

export const emptyCombatOptions = (): CombatOptionSelection => ({
  attack_types: [],
  stances: [],
  spells: [],
});

export function combatCapabilities(
  context: GearContext | null,
): CombatOptionCapabilities | null {
  const raw = context?.live?.capabilities.combat_options;
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  if (
    !["attack_types", "stances", "spells"].every((key) =>
      Array.isArray(row[key]),
    )
  )
    return null;
  return raw as CombatOptionCapabilities;
}

export function availableCombatOptions(
  role: Pick<Role, "style" | "autoDiscipline" | "allowedDisciplines">,
  context: GearContext | null,
): CombatOptionCapabilities | null {
  const catalog = combatCapabilities(context);
  if (!catalog) return null;
  const disciplines = role.autoDiscipline
    ? (role.allowedDisciplines ?? ["melee", "ranged", "magic"])
    : [role.style];
  const allowedAttackTypes = new Set(
    disciplines.flatMap((style) => attackTypes[style]),
  );
  const allowedStances = new Set(
    disciplines.flatMap((style) => stances[style]),
  );
  const filter = (rows: CombatOptionAvailability[], ids?: Set<string>) => {
    const eligible = rows.filter(
      (row) =>
        (!ids || ids.has(row.id)) &&
        (!row.category || disciplines.includes(row.category)),
    );
    return [...new Set(eligible.map((row) => row.id))].map(
      (id) =>
        eligible.find((row) => row.id === id && row.available) ??
        eligible.find((row) => row.id === id)!,
    );
  };
  return {
    attack_types: filter(catalog.attack_types, allowedAttackTypes),
    stances: filter(catalog.stances, allowedStances),
    spells: disciplines.includes("magic") ? filter(catalog.spells) : [],
  };
}

export function selectedCombatOptions(
  role: Pick<
    Role,
    | "style"
    | "autoDiscipline"
    | "allowedDisciplines"
    | "combatOptionDisabled"
    | "combatOptionExplicitlyEmpty"
  >,
  context: GearContext | null,
): CombatOptionSelection | null {
  const available = availableCombatOptions(role, context);
  if (!available) return null;
  const disabled = role.combatOptionDisabled ?? emptyCombatOptions();
  return {
    attack_types: (role.combatOptionExplicitlyEmpty?.attack_types
      ? []
      : available.attack_types
    )
      .filter((row) => row.available && !disabled.attack_types.includes(row.id))
      .map((row) => row.id),
    stances: (role.combatOptionExplicitlyEmpty?.stances
      ? []
      : available.stances
    )
      .filter((row) => row.available && !disabled.stances.includes(row.id))
      .map((row) => row.id),
    spells: (role.combatOptionExplicitlyEmpty?.spells ? [] : available.spells)
      .filter((row) => row.available && !disabled.spells.includes(row.id))
      .map((row) => row.id),
  };
}

type OptionField = keyof CombatOptionSelection;
type OptionPatch = Pick<
  Role,
  "combatOptionDisabled" | "combatOptionExplicitlyEmpty"
>;

const disciplinesOf = (
  role: Pick<Role, "style" | "autoDiscipline" | "allowedDisciplines">,
): Style[] =>
  role.autoDiscipline
    ? (role.allowedDisciplines ?? ["melee", "ranged", "magic"])
    : [role.style];

/** Groups that apply to the role's disciplines but have nothing selected. */
export function emptyCombatOptionGroups(
  role: Parameters<typeof selectedCombatOptions>[0],
  context: GearContext | null,
): OptionField[] {
  const selected = selectedCombatOptions(role, context);
  if (!selected) return [];
  const fields: OptionField[] = disciplinesOf(role).includes("magic")
    ? ["attack_types", "stances", "spells"]
    : ["attack_types", "stances"];
  return fields.filter((field) => selected[field].length === 0);
}

/** Replaces one group's selection with exactly `ids` (eligible ones only). */
export function selectOnlyCombatOptions(
  role: Role,
  field: OptionField,
  ids: string[],
  context: GearContext | null,
): OptionPatch {
  const disabled = role.combatOptionDisabled ?? emptyCombatOptions();
  const rows = availableCombatOptions(role, context)?.[field] ?? [];
  const shown = new Set(rows.map((row) => row.id));
  const keep = new Set(ids);
  return {
    combatOptionDisabled: {
      ...disabled,
      // Entries for other disciplines are not visible here, so leave them.
      [field]: [
        ...disabled[field].filter((id) => !shown.has(id)),
        ...rows.filter((row) => !keep.has(row.id)).map((row) => row.id),
      ],
    },
    combatOptionExplicitlyEmpty: {
      ...role.combatOptionExplicitlyEmpty,
      [field]: !rows.some((row) => row.available && keep.has(row.id)),
    },
  };
}

const STANDARD_SPELL =
  /^(wind|water|earth|fire)_(strike|bolt|blast|wave|surge)$/;
const ANCIENT_SPELL = /^(smoke|shadow|blood|ice)_(rush|burst|blitz|barrage)$/;
const STANDARD_TIERS = ["strike", "bolt", "blast", "wave", "surge"];
const ANCIENT_TIERS = ["rush", "burst", "blitz", "barrage"];
const DEMONBANE_SPELLS = [
  "inferior_demonbane",
  "superior_demonbane",
  "dark_demonbane",
];
const ELEMENTS = ["fire", "water", "earth", "air"] as const;

export interface SpellQuickPick {
  label: string;
  ids: string[];
}

function highestTier(ids: string[], pattern: RegExp, tiers: string[]) {
  const tierOf = (id: string) => tiers.indexOf(pattern.exec(id)![2]);
  const matching = ids.filter((id) => pattern.test(id));
  const top = Math.max(-1, ...matching.map(tierOf));
  return matching.filter((id) => tierOf(id) === top);
}

/** One-click spell selections built from the spells the account can cast. */
export function spellQuickPicks(
  role: Pick<Role, "style" | "autoDiscipline" | "allowedDisciplines">,
  context: GearContext | null,
): SpellQuickPick[] {
  const eligible = (availableCombatOptions(role, context)?.spells ?? [])
    .filter((row) => row.available)
    .map((row) => row.id);
  const picks: SpellQuickPick[] = [
    {
      label: "Standard",
      ids: eligible.filter((id) => STANDARD_SPELL.test(id)),
    },
    { label: "Ancient", ids: eligible.filter((id) => ANCIENT_SPELL.test(id)) },
    {
      label: "Demonbane",
      ids: eligible.filter((id) => DEMONBANE_SPELLS.includes(id)),
    },
    {
      label: "Highest tier",
      ids: [
        ...highestTier(eligible, STANDARD_SPELL, STANDARD_TIERS),
        ...highestTier(eligible, ANCIENT_SPELL, ANCIENT_TIERS),
        ...DEMONBANE_SPELLS.filter((id) => eligible.includes(id)).slice(-1),
      ],
    },
    ...ELEMENTS.map((element) => ({
      label: element[0].toUpperCase() + element.slice(1),
      ids: eligible.filter(
        (id) =>
          STANDARD_SPELL.test(id) &&
          id.startsWith(`${element === "air" ? "wind" : element}_`),
      ),
    })),
  ];
  return picks.filter((pick) => pick.ids.length > 0);
}

export function setCombatOptionEnabled(
  role: Role,
  field: keyof CombatOptionSelection,
  id: string,
  enabled: boolean,
  context: GearContext | null,
): Role {
  const disabled = role.combatOptionDisabled ?? emptyCombatOptions();
  const nextDisabled = enabled
    ? disabled[field].filter((entry) => entry !== id)
    : [...new Set([...disabled[field], id])];
  const available = availableCombatOptions(role, context);
  const explicitlyEmpty =
    !enabled &&
    !!available &&
    available[field]
      .filter((row) => row.available)
      .every((row) => nextDisabled.includes(row.id));
  return {
    ...role,
    combatOptionDisabled: {
      ...disabled,
      [field]: nextDisabled,
    },
    combatOptionExplicitlyEmpty: {
      ...role.combatOptionExplicitlyEmpty,
      [field]: enabled ? false : explicitlyEmpty,
    },
  };
}

/** Use server-reviewed spell access at the maximum allowed fresh Magic boost. */
export function potionCombatContext(
  context: GearContext | null,
  policy?: PotionPolicy,
): GearContext | null {
  const ids =
    policy?.mode === "fixed"
      ? policy.selected_ids
      : policy?.mode === "optimize"
        ? policy.allowed_ids
        : [];
  if (
    !context?.live ||
    !ids?.some((id) => id === "magic" || id === "divine_magic") ||
    !context.live.capabilities.potion_combat_options
  )
    return context;
  return {
    ...context,
    live: {
      ...context.live,
      capabilities: {
        ...context.live.capabilities,
        combat_options: context.live.capabilities.potion_combat_options,
      },
    },
  };
}
