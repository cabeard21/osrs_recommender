import { useEffect, useState } from "react";
import type { Item, Slot } from "../api/contracts";
import { useGear } from "../state/GearProvider";

const SEARCH_DELAY_MS = 200;
const MAX_RESULTS = 5;

export function ItemSearch({
  label,
  slot,
  onPick,
}: {
  label: string;
  slot: Slot;
  onPick: (item: Item) => void;
}) {
  const { client, current } = useGear();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");
  const policy = current.draft.supportPolicy ?? "community_best_effort";
  useEffect(() => {
    setError("");
    if (!query.trim() || !client.browseItems) {
      setItems([]);
      return;
    }
    let active = true;
    const timer = setTimeout(() => {
      client
        .browseItems?.(slot, query, 0, policy)
        .then((page) => {
          if (active) setItems(page.items.slice(0, MAX_RESULTS));
        })
        .catch((e: Error) => {
          if (active) setError(e.message);
        });
    }, SEARCH_DELAY_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, slot, policy, client]);
  if (!client.browseItems) return null;
  return (
    <div className="item-search">
      <label>
        {label}
        <input
          type="search"
          value={query}
          placeholder="Item name"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      {items.length > 0 && (
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => {
                  onPick(item);
                  setQuery("");
                }}
              >
                {item.name} (#{item.id})
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
