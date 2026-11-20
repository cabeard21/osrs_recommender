import type {
  Scenario,
  WildernessPolicy,
  WildernessRisk,
} from "../api/contracts";
import { wildernessRiskCap } from "../api/wilderness";

const outcomeNames: Record<WildernessRisk["items"][number]["outcome"], string> =
  {
    kept: "Kept",
    gravestone: "Recover from gravestone",
    dropped: "Dropped",
    broken: "Broken",
    mangled: "Mangled",
    destroyed: "Permanently lost",
    converted: "Converted",
    unknown: "Unknown",
  };
export const resourceNames: Readonly<Partial<Record<number, string>>> = {
  554: "Fire rune",
  555: "Water rune",
  556: "Air rune",
  557: "Earth rune",
  558: "Mind rune",
  560: "Death rune",
  562: "Chaos rune",
  564: "Cosmic rune",
  565: "Blood rune",
  566: "Soul rune",
  995: "Coins",
  12934: "Zulrah’s scales",
  21820: "Revenant ether",
  21880: "Wrath rune",
};

export function riskAmount(value: number | null): string {
  return value === null ? "Unavailable" : `${value.toLocaleString()} GP`;
}

export function budgetSummary(request: Scenario["request"]): string {
  const lossCap = wildernessRiskCap(request);
  if (lossCap === undefined)
    return `${riskAmount(request.budget_gp)} additional budget`;
  if (lossCap === null)
    return `${riskAmount(request.budget_gp)} purchase budget · No loss cap`;
  const purchase =
    request.wilderness?.max_loss_gp == null
      ? "No purchase cap"
      : `${riskAmount(request.budget_gp)} purchase budget`;
  return `${purchase} · ${riskAmount(lossCap)} max gear loss if PK’d`;
}

export function WildernessRiskDetails({
  risk,
  policy,
  itemName,
}: {
  risk: WildernessRisk;
  policy: WildernessPolicy;
  itemName: (id: number) => string;
}) {
  const resourceName = (id: number) => resourceNames[id] ?? itemName(id);
  const gearSupplies = risk.quantities.filter((row) => row.kind !== "rune");
  const looseRunes = risk.quantities.filter((row) => row.kind === "rune");
  return (
    <>
      <p>
        <strong className="numeric gold">{riskAmount(risk.loss_gp)}</strong>{" "}
        estimated loss if PK’d
      </p>
      <p>
        Level {policy.depth === "level_1_20" ? "1–20" : "21+"} ·{" "}
        {policy.skulled ? "Skulled" : "Unskulled"} · Protect Item{" "}
        {policy.protect_item ? "active" : "off"}
      </p>
      {policy.protect_item && (
        <p>
          Same setup without Protect Item ·{" "}
          {riskAmount(risk.without_protect_item_gp)}
        </p>
      )}
      {policy.attacks_per_setup != null && (
        <p>
          Departure supplies for {policy.attacks_per_setup.toLocaleString()}{" "}
          attacks per combat setup.
        </p>
      )}
      {gearSupplies.length > 0 && (
        <>
          <p>
            <strong>Recommended ammo and loaded charges</strong>
          </p>
          <ul>
            {gearSupplies.map((row) => (
              <li key={`${row.item_id}-${row.resource_id}-${row.kind}`}>
                {row.quantity.toLocaleString()} ×{" "}
                {resourceName(row.resource_id)}
                {row.item_id !== row.resource_id &&
                  ` for ${itemName(row.item_id)}`}
              </li>
            ))}
          </ul>
        </>
      )}
      {looseRunes.length > 0 && (
        <>
          <p>
            <strong>Loose spell runes</strong>
            {policy.spell_casts != null &&
              ` for ${policy.spell_casts.toLocaleString()} casts per Magic setup`}
          </p>
          <ul>
            {looseRunes.map((row) => (
              <li key={row.resource_id}>
                {row.quantity.toLocaleString()} ×{" "}
                {resourceName(row.resource_id)}
              </li>
            ))}
          </ul>
        </>
      )}
      {risk.items.length > 0 && (
        <details>
          <summary>Items kept and lost</summary>
          <table aria-label="Wilderness item outcomes">
            <thead>
              <tr>
                <th>Item</th>
                <th>Outcome</th>
                <th>Loss</th>
              </tr>
            </thead>
            <tbody>
              {risk.items.map((row, index) => (
                <tr key={`${row.item_id}-${row.outcome}-${index}`}>
                  <td>
                    {resourceName(row.item_id)}
                    {row.quantity > 1 && ` × ${row.quantity.toLocaleString()}`}
                  </td>
                  <td>{outcomeNames[row.outcome]}</td>
                  <td className="numeric">{riskAmount(row.loss_gp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <p>
        Extra inventory can add losses and change which items are protected.
      </p>
    </>
  );
}
