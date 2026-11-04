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
