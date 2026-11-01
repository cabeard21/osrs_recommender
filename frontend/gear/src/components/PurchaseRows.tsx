import { ItemSprite } from "./EquipmentGrid";

type Purchase = {
  item_id: number;
  cost_gp: number | null;
  conditional: boolean;
};

export function purchaseSummary(count: number, costGp: number): string {
  if (!count) return "No additional purchases";
  return `Buy ${count} item${count === 1 ? "" : "s"} · ${costGp.toLocaleString()} GP`;
}

export function PurchaseRows({
  purchases,
  itemName,
}: {
  purchases: Purchase[];
  itemName: (id: number) => string;
}) {
  if (!purchases.length) return null;
  return (
    <ul className="purchase-rows">
      {purchases.map((purchase) => {
        const price =
          purchase.cost_gp === null
            ? "Price unavailable"
            : `${purchase.cost_gp.toLocaleString()} GP`;
        const note = purchase.conditional
          ? " · conditional purchase: ownership uncertain"
          : "";
        return (
          <li key={purchase.item_id}>
            <ItemSprite id={purchase.item_id} />
            <span>{`${itemName(purchase.item_id)} · ${price}${note}`}</span>
          </li>
        );
      })}
    </ul>
  );
}
