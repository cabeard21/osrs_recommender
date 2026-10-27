import { useState } from "react";

export function PurchaseListCopy({
  purchases,
  itemName,
}: {
  purchases: {
    item_id: number;
    cost_gp: number | null;
    conditional: boolean;
  }[];
  itemName: (id: number) => string;
}) {
  const [status, setStatus] = useState<"copied" | "error" | null>(null);
  const text = purchases.length
    ? purchases
        .map(
          (p) =>
            `${itemName(p.item_id)} (#${p.item_id}) · ${p.cost_gp === null ? "Price unavailable" : `${p.cost_gp.toLocaleString()} GP`}${p.conditional ? " · conditional purchase: ownership uncertain" : ""}`,
        )
        .join("\n")
    : "No additional purchases required.";
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("copied");
    } catch {
      setStatus("error");
    }
  }
  return (
    <div>
      <button onClick={() => void copy()}>Copy purchase list</button>
      {status === "copied" && <p role="status">Purchase list copied.</p>}
      {status === "error" && (
        <p role="alert">Could not copy. Select the purchase list below.</p>
      )}
      <details open={status === "error"}>
        <summary>Selectable purchase list</summary>
        <pre className="fact-json">{text}</pre>
      </details>
    </div>
  );
}
