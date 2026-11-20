import type { Item, JointSolutionDTO, Preparation } from "../api/contracts";
import { BankTagExport } from "./BankTagExport";
import { PurchaseListCopy } from "./PurchaseListCopy";
import { PurchaseRows } from "./PurchaseRows";
import { UntradeablesToObtain } from "./UntradeablesToObtain";
import { resourceNames, riskAmount } from "./WildernessRiskDetails";
import { equipmentFor } from "./resultFormat";
import "../styles/acquisition-checklist.css";

type RoleLoadout = {
  id: string;
  name: string;
  loadout: JointSolutionDTO["loadouts"][string];
};

function groupPreparations(roles: RoleLoadout[]) {
  const groups = new Map<
    string,
    { preparation: Preparation; roleNames: string[] }
  >();
  for (const role of roles) {
    for (const preparation of role.loadout.preparations ?? []) {
      const key = JSON.stringify([
        preparation.usable_item_id,
        preparation.source_item_id,
        preparation.market_item_id,
        preparation.charging_required,
        preparation.activation_reserve,
        preparation.message,
      ]);
      const roleNames = groups.get(key)?.roleNames ?? [];
      groups.set(key, { preparation, roleNames: [...roleNames, role.name] });
    }
  }
  return [...groups.entries()];
}

export function AcquisitionChecklist({
  solution,
  roles,
  itemById,
  selectionKey,
}: {
  solution: JointSolutionDTO;
  roles: readonly { id: string; name: string }[];
  itemById: (id: number) => Item | undefined;
  selectionKey: string;
}) {
  const roleLoadouts = roles.flatMap((role) => {
    const loadout = solution.loadouts[role.id];
    return loadout ? [{ ...role, loadout }] : [];
  });
  const joint = roleLoadouts.length > 1;
  const preparations = groupPreparations(roleLoadouts);
  const itemName = (id: number) => itemById(id)?.name ?? `Item #${id}`;
  const exactForm = (id: number) => {
    const item = itemById(id);
    return item ? `${item.name} (#${id})` : `Item #${id}`;
  };
  const resourceName = (id: number) =>
    solution.running_cost?.resources.find((resource) => resource.item_id === id)
      ?.name ??
    resourceNames[id] ??
    itemName(id);
  const rolesUsing = (id: number, includeMarketForms = false) =>
    joint
      ? roleLoadouts
          .filter(({ loadout }) =>
            Object.values(loadout.equipment).some((usableId) => {
              const route =
                includeMarketForms &&
                loadout.preparations?.find(
                  (p) => p.usable_item_id === usableId,
                );
              return route
                ? route.source_item_id === null &&
                    (route.market_item_id ?? usableId) === id
                : usableId === id;
            }),
          )
          .map((role) => role.name)
      : [];
  const upkeep = solution.running_cost?.gp_per_hour;
  return (
    <section
      className="panel acquisition-checklist"
      id="selected-acquisition"
      tabIndex={-1}
      aria-labelledby="selected-acquisition-title"
    >
      <h2 id="selected-acquisition-title">Acquisition checklist</h2>
      <section aria-label="Buy">
        <h3>Buy</h3>
        <strong className="gold numeric">
          {solution.purchase_cost_gp.toLocaleString()} GP additional purchases
        </strong>
        {solution.purchases.length > 0 && <p>Prices are cached estimates.</p>}
        <PurchaseRows
          purchases={solution.purchases}
          itemName={itemName}
          usedBy={(id) => rolesUsing(id, true)}
        />
        <PurchaseListCopy
          key={selectionKey}
          purchases={solution.purchases}
          itemName={itemName}
        />
      </section>
      <UntradeablesToObtain
        ids={solution.unowned_untradeable_item_ids}
        itemName={itemName}
        acquisitionNotes={(id) =>
          itemById(id)?.facts?.acquisition_descriptions ?? []
        }
        usedBy={rolesUsing}
      />
      {preparations.length > 0 && (
        <section aria-label="Prepare">
          <h3>Prepare</h3>
          <ul>
            {preparations.map(([key, { preparation, roleNames }]) => {
              const source =
                preparation.source_item_id ?? preparation.market_item_id;
              const usable = preparation.usable_item_id;
              return (
                <li key={key}>
                  <strong>
                    {source !== null &&
                      source !== usable &&
                      `${exactForm(source)} → `}
                    {exactForm(usable)}
                  </strong>
                  {joint && <small>Used by {roleNames.join(", ")}</small>}
                  <p>{preparation.message}</p>
                  {preparation.activation_reserve.length > 0 && (
                    <p>
                      Activation reserve ·{" "}
                      {preparation.activation_reserve
                        .map(
                          ({ item_id, quantity }) =>
                            `${quantity.toLocaleString()} × ${resourceName(item_id)}`,
                        )
                        .join(", ")}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {(solution.running_cost || solution.wilderness_risk) && (
        <dl className="acquisition-estimates">
          {solution.running_cost && (
            <div>
              <dt>Estimated upkeep</dt>
              <dd className="numeric">
                {upkeep == null
                  ? "Unavailable"
                  : `${upkeep.toLocaleString(undefined, { maximumFractionDigits: 2 })} GP/hour`}
              </dd>
            </div>
          )}
          {solution.wilderness_risk && (
            <div>
              <dt>Estimated Wilderness loss</dt>
              <dd className="numeric">
                {riskAmount(solution.wilderness_risk.loss_gp)}
              </dd>
            </div>
          )}
        </dl>
      )}
      <section aria-label="Export">
        <h3>Export</h3>
        <div className="acquisition-exports">
          {roleLoadouts.map(({ id, name, loadout }) => (
            <div
              key={`${selectionKey}:${id}`}
              role="group"
              aria-label={`Bank tag for ${name}`}
            >
              {joint && <p>{name}</p>}
              <BankTagExport
                equipment={equipmentFor(loadout.equipment)}
                name={name}
              />
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
