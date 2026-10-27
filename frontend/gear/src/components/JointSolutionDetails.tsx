import type { JointSolutionDTO, JointTransitionDTO } from "../api/contracts";
import { PurchaseListCopy } from "./PurchaseListCopy";

export function JointInventory({
  solution,
  activeRole,
  roleName,
  itemName,
}: {
  solution: JointSolutionDTO;
  activeRole: string;
  roleName: string;
  itemName: (id: number) => string;
}) {
  const worn = new Set(
    Object.values(solution.loadouts[activeRole]?.equipment ?? {}),
  );
  const inventory = solution.carried_item_ids.filter((id) => !worn.has(id));
  return (
    <section className="panel" aria-label="Gear inventory requirements">
      <h2>Gear inventory and required equipment</h2>
      <dl>
        {[
          ["Unique required items", solution.distinct_items],
          ["Base gear inventory slots", solution.gear_inventory_slots],
          [
            "Transient peak gear inventory slots",
            solution.max_gear_inventory_slots,
          ],
          ["Reserved supply slots", solution.reserved_supply_slots],
          ["Remaining inventory capacity", solution.remaining_inventory_slots],
          ["Total supply capacity at peak", solution.remaining_supply_slots],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <p>
        Carried outside {roleName}:{" "}
        {inventory.map(itemName).join(" · ") || "None"} ({inventory.length} gear
        inventory slots).
      </p>
      <details>
        <summary>All required physical equipment</summary>
        <p>
          {solution.carried_item_ids
            .map((id) => `${itemName(id)} (#${id})`)
            .join(" · ") || "No equipment required"}
        </p>
      </details>
      <p>
        The required item union includes equipped items. Gear inventory counts
        equipment outside active slots; supply reservations do not simulate
        consumption.
      </p>
    </section>
  );
}

export function JointTransition({
  solution,
  selected,
  onSelect,
  roleName,
  itemName,
}: {
  solution: JointSolutionDTO;
  selected: string;
  onSelect: (key: string) => void;
  roleName: (id: string) => string;
  itemName: (id: number) => string;
}) {
  const key = (transition: JointTransitionDTO) =>
    `${transition.from_role}:${transition.to_role}`;
  const transition =
    solution.transitions.find((t) => key(t) === selected) ??
    solution.transitions[0];
  return (
    <section className="panel" aria-label="Directed equipment transition">
      <h2>Directed equipment transition</h2>
      {transition ? (
        <>
          <label>
            Directed transition
            <select
              value={key(transition)}
              onChange={(e) => onSelect(e.target.value)}
            >
              {solution.transitions.map((t) => (
                <option key={key(t)} value={key(t)}>
                  {roleName(t.from_role)} → {roleName(t.to_role)}
                </option>
              ))}
            </select>
          </label>
          <dl>
            <div>
              <dt>Changed equipment slots</dt>
              <dd>{transition.changed_slots}</dd>
            </div>
            <div>
              <dt>Equipment actions</dt>
              <dd>{transition.action_count}</dd>
            </div>
            <div>
              <dt>Transition peak gear inventory slots</dt>
              <dd>{transition.max_gear_inventory_slots}</dd>
            </div>
          </dl>
          {transition.actions.length ? (
            <ol>
              {transition.actions.map((action, index) => (
                <li key={index}>
                  {action.operation === "equip" ? "Equip" : "Unequip"}{" "}
                  {itemName(action.item_id)} ({action.slot}).
                  {action.automatically_removed.length > 0 && (
                    <>
                      {" "}
                      Automatically removed:{" "}
                      {action.automatically_removed.map(itemName).join(", ")}.
                    </>
                  )}{" "}
                  Gear inventory: {action.gear_inventory_slots} slots.
                </li>
              ))}
            </ol>
          ) : (
            <p>No equipment actions required for this directed transition.</p>
          )}
          <p>
            Backend-provided sequence. Automatic removals do not add equipment
            actions; reverse transitions can require different actions.
          </p>
        </>
      ) : (
        <p>No directed transitions are required by the submitted topology.</p>
      )}
    </section>
  );
}

export function JointPurchases({
  solution,
  identity,
  itemName,
}: {
  solution: JointSolutionDTO;
  identity: string;
  itemName: (id: number) => string;
}) {
  return (
    <section className="panel">
      <h2>Joint acquisition requirements</h2>
      <strong className="gold numeric">
        {solution.purchase_cost_gp.toLocaleString()} GP additional purchases
      </strong>
      <p>
        Shared purchases are counted once across all configurations. Cached
        acquisition estimates are not guaranteed market prices.
      </p>
      {solution.purchases.map((purchase) => (
        <p key={purchase.item_id}>
          {itemName(purchase.item_id)} ·{" "}
          {purchase.cost_gp === null
            ? "Price unavailable"
            : `${purchase.cost_gp.toLocaleString()} GP`}
          {purchase.conditional &&
            " · conditional purchase: ownership uncertain"}
        </p>
      ))}
      <PurchaseListCopy
        key={identity}
        purchases={solution.purchases}
        itemName={itemName}
      />
    </section>
  );
}
