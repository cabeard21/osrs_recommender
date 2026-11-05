import { validateRunningCost } from "./runningCosts";
import { validateUntradeables } from "./untradeables";
import { slots } from "./contracts";
import { validateSecondaryPriority } from "./secondaryPriorities";
import type {
  Item,
  JointSolutionDTO,
  Scenario,
  Slot,
  Solution,
  CombatPerformance,
} from "./contracts";
import {
  object,
  requireFields,
  strings,
  equipmentMap,
  performanceMetrics,
  sameValue,
  uiSlot,
} from "./runtime";
export function parseJointSolution(
  value: unknown,
  scenario: Scenario,
  items: Item[],
  id: string,
  actionLimit: number,
): Solution {
  const row = requireFields(value, {
    score: "number",
    purchase_cost_gp: "number",
  });
  validateRunningCost(row.running_cost);
  validateSecondaryPriority(
    row,
    scenario.request.secondary_priority ?? "default",
    true,
  );
  const integer = (n: unknown) => Number.isSafeInteger(n) && Number(n) >= 0;
  for (const field of [
    "purchase_cost_gp",
    "distinct_items",
    "gear_inventory_slots",
    "max_gear_inventory_slots",
    "remaining_supply_slots",
    "remaining_inventory_slots",
    "reserved_supply_slots",
    "maximum_actions",
  ])
    if (!integer(row[field]))
      throw new Error(`Invalid joint solution ${field}`);
  if (
    !Number.isFinite(row.score) ||
    !Array.isArray(row.purchases) ||
    !Array.isArray(row.carried_item_ids) ||
    !Array.isArray(row.transitions)
  )
    throw new Error("Invalid joint result");
  const byRole = object(row.loadouts),
    roles = scenario.request.roles;
  if (
    Object.keys(byRole).length !== roles.length ||
    Object.keys(byRole).some((key) => !roles.some((r) => r.id === key))
  )
    throw new Error("Joint result role IDs do not match submitted roles");
  const loadouts = roles.map((role) => {
    const loadout = object(byRole[role.id]),
      equipment = equipmentMap(loadout.equipment);
    validateRunningCost(loadout.running_cost);
    if (
      role.autoDiscipline &&
      !(role.allowedDisciplines ?? ["melee", "ranged", "magic"]).includes(
        loadout.discipline as import("./contracts").Style,
      )
    )
      throw new Error("Invalid resolved Auto discipline");
    for (const [slot, itemId] of Object.entries(equipment))
      if (
        itemId !== null &&
        (!items.some((i) => i.id === itemId && i.slot === slot) ||
          scenario.request.excluded_item_ids.includes(itemId))
      )
        throw new Error("Missing physical joint result item metadata");
    const performance = object(
      loadout.performance,
    ) as unknown as CombatPerformance;
    if (
      typeof performance.supported !== "boolean" ||
      !strings(performance.limitations)
    )
      throw new Error("Invalid role performance");
    if (
      !performance.supported &&
      [
        performance.dps,
        performance.max_hit,
        performance.accuracy,
        performance.attack_interval,
      ].some((n) => n !== null)
    )
      throw new Error("Unsupported roles must withhold performance");
    return {
      roleId: role.id,
      name: role.name,
      equipment,
      metrics: role.utility
        ? null
        : performance.supported
          ? performanceMetrics(performance)
          : null,
      performance,
      selectedPrayerIds: loadout.selected_prayer_ids as string[] | undefined,
      discipline: loadout.discipline as import("./contracts").Style | undefined,
      combatOption: loadout.combat_option as
        import("./contracts").CombatOption | undefined,
    };
  });
  const required = [
    ...new Set(
      loadouts.flatMap((l) =>
        Object.values(l.equipment).filter((v): v is number => v !== null),
      ),
    ),
  ].sort((a, b) => a - b);
  if (
    !sameValue(
      required,
      [...row.carried_item_ids].sort((a, b) => Number(a) - Number(b)),
    ) ||
    row.distinct_items !== required.length
  )
    throw new Error("Invalid required equipment union");
  const purchaseIds = new Set<number>();
  for (const purchase of row.purchases) {
    const p = requireFields(purchase, {
      item_id: "number",
      conditional: "boolean",
    });
    if (
      !required.includes(Number(p.item_id)) ||
      purchaseIds.has(Number(p.item_id)) ||
      (p.cost_gp !== null && !integer(p.cost_gp))
    )
      throw new Error("Invalid shared purchase union");
    purchaseIds.add(Number(p.item_id));
  }
  validateUntradeables(
    row.unowned_untradeable_item_ids,
    required,
    [...purchaseIds],
    scenario.request.include_untradeables === true &&
      scenario.request.mode !== "owned",
  );
  const transitions = row.transitions.map((value) => {
    const t = requireFields(value, { from_role: "string", to_role: "string" });
    if (
      !roles.some((r) => r.id === t.from_role) ||
      !roles.some((r) => r.id === t.to_role) ||
      t.from_role === t.to_role ||
      !Array.isArray(t.actions) ||
      !integer(t.action_count) ||
      t.action_count !== t.actions.length ||
      !integer(t.changed_slots) ||
      !integer(t.max_gear_inventory_slots)
    )
      throw new Error("Invalid directed transition");
    const actions = t.actions.map((value) => {
      const a = requireFields(value, {
        operation: "string",
        slot: "string",
        item_id: "number",
      });
      if (
        !["equip", "unequip"].includes(String(a.operation)) ||
        !slots.includes(uiSlot(a.slot) as Slot) ||
        !required.includes(Number(a.item_id)) ||
        !Array.isArray(a.automatically_removed) ||
        a.automatically_removed.some((i) => !required.includes(Number(i))) ||
        !integer(a.gear_inventory_slots)
      )
        throw new Error("Invalid equipment action sequence");
      return `${a.operation} ${items.find((i) => i.id === a.item_id)?.name ?? `Item #${a.item_id}`} (${a.slot})`;
    });
    return {
      from: t.from_role as string,
      to: t.to_role as string,
      actions,
      changedSlots: t.changed_slots as number,
      peak: t.max_gear_inventory_slots as number,
    };
  });
  if (
    row.reserved_supply_slots !== scenario.request.reserved_supply_slots ||
    Number(row.max_gear_inventory_slots) +
      Number(row.reserved_supply_slots) +
      Number(row.remaining_inventory_slots) !==
      28 ||
    Number(row.max_gear_inventory_slots) +
      Number(row.remaining_supply_slots) !==
      28
  )
    throw new Error("Invalid joint inventory capacity");
  if (id !== "unrestricted" && Number(row.maximum_actions) > actionLimit)
    throw new Error("Joint solution exceeds curve action limit");
  return {
    id,
    actionLimit,
    loadouts,
    weightedDps: row.score as number,
    purchases: [...purchaseIds],
    cost: row.purchase_cost_gp as number,
    shared: required.filter(
      (itemId) =>
        loadouts.filter((l) => Object.values(l.equipment).includes(itemId))
          .length > 1,
    ),
    transitions,
    live: structuredClone(value) as JointSolutionDTO,
  };
}
