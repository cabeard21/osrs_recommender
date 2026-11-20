import type { Scenario, Slot } from "./contracts";
import { canonicalObjectives } from "./objectives";

export const apiSlot = (slot: Slot) => (slot === "ammo" ? "ammunition" : slot);

export function optimizationRequest(scenario: Scenario) {
  const r = scenario.request;
  if (r.roles.length < 1 || r.roles.length > 4)
    throw new Error(
      "Live optimization supports one through four configurations.",
    );
  if (r.roles.some((role) => role.autoDiscipline && role.utility))
    throw new Error("Auto requires a scored combat configuration.");
  return {
    roles: r.roles.map((role) => ({
      id: role.id,
      on_slayer_task: role.onSlayerTask ?? false,
      safe_spotting: role.safeSpotting ?? false,
      fight_duration_seconds: Number(role.fightDurationSeconds ?? "60"),
      mark_of_darkness: role.markOfDarkness ?? false,
      ...(role.autoDiscipline
        ? {
            allowed_disciplines: role.allowedDisciplines ?? [
              "melee",
              "ranged",
              "magic",
            ],
          }
        : {}),
      style: role.utility
        ? "special"
        : role.style === "melee"
          ? role.attackType
          : role.style,
      stance: role.stance,
      spell: role.spell,
      ...(role.combatOptions ? { combat_options: role.combatOptions } : {}),
      prayers: role.prayers ?? {
        mode: "disabled",
        selected_ids: [],
        allowed_ids: [],
      },
      weight: role.weight,
      locks: Object.fromEntries(
        Object.entries(role.locks).map(([slot, id]) => [
          apiSlot(slot as Slot),
          id,
        ]),
      ),
      ...(role.parentRole ? { parent_role: role.parentRole } : {}),
      ...((role.targetSelection ??
      (r.roles.length === 1 ? r.target.selection : undefined))
        ? {
            target_selection:
              role.targetSelection ??
              (r.roles.length === 1 ? r.target.selection : undefined),
          }
        : {}),
      target: role.combatTarget ??
        r.target.definition ?? {
          name: r.target.name,
          defence_level: r.target.defence,
          magic_level: 1,
          bonuses: {},
        },
    })),
    ...(Object.keys(r.locks ?? {}).length
      ? {
          locks: Object.fromEntries(
            Object.entries(r.locks ?? {}).map(([slot, id]) => [
              apiSlot(slot as Slot),
              id,
            ]),
          ),
        }
      : {}),
    ...(r.roles.length > 1
      ? {
          base_role: r.base_role,
          ...(r.ordered_roles?.length
            ? { ordered_roles: r.ordered_roles, loop: !!r.loop }
            : r.transitions.length
              ? { transitions: r.transitions }
              : {}),
        }
      : {}),
    ...(r.crystal_halberd_charging
      ? { crystal_halberd_charging: r.crystal_halberd_charging }
      : {}),
    fire_tome_pages: r.fire_tome_pages ?? "burnt",
    support_policy: r.support_policy ?? "verified_only",
    mode: r.mode,
    include_untradeables: r.include_untradeables ?? false,
    optimization_mode: r.optimization_mode ?? "fast",
    potions: r.potions ?? {
      mode: "disabled",
      allowed_ids: [],
      selected_ids: [],
    },
    ...(r.objectives !== undefined
      ? {
          objectives: canonicalObjectives(r.objectives),
          secondary_priority: "default",
        }
      : { secondary_priority: r.secondary_priority ?? "default" }),
    max_dps_loss_pct: 100,
    budget_gp: r.budget_gp,
    ...(r.wilderness ? { wilderness: r.wilderness } : {}),
    reserved_supply_slots: r.reserved_supply_slots,
    max_swaps: r.max_swaps,
    skill_overrides: r.skill_overrides,
    quest_overrides: r.quest_overrides,
    assumed_item_ids: r.assumed_item_ids,
    ...(r.excluded_item_ids.length
      ? { excluded_item_ids: [...r.excluded_item_ids] }
      : {}),
    expected_snapshot_id: r.expected_snapshot_id,
  };
}
