import type { JointSolutionDTO, JointTransitionDTO } from "../api/contracts";

export function JointInventory({
  solution,
  roles,
  itemName,
}: {
  solution: JointSolutionDTO;
  roles: { id: string; name: string }[];
  itemName: (id: number) => string;
}) {
  const carriedOutside = (roleId: string) => {
    const worn = new Set(
      Object.values(solution.loadouts[roleId]?.equipment ?? {}),
    );
    return solution.carried_item_ids.filter((id) => !worn.has(id));
  };
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
      {roles.map((role) => {
        const inventory = carriedOutside(role.id);
        return (
          <p key={role.id}>
            Carried outside {role.name}:{" "}
            {inventory.map(itemName).join(" · ") || "None"} ({inventory.length}{" "}
            gear inventory slots).
          </p>
        );
      })}
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
            Calculated sequence. Automatic removals do not add equipment
            actions; reverse transitions can require different actions.
          </p>
        </>
      ) : (
        <p>No directed transitions are required by the submitted topology.</p>
      )}
    </section>
  );
}
