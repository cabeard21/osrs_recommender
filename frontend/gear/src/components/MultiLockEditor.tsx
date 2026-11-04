import { useState } from "react";
import { slots, type Draft, type Slot } from "../api/contracts";
import { ItemSearch } from "./ItemSearch";

export function MultiLockEditor({
  draft,
  change,
  itemLabel = (id) => `Item #${id}`,
  isSingle = false,
}: {
  draft: Draft;
  change: (patch: Partial<Draft>) => void;
  itemLabel?: (id: number) => string;
  isSingle?: boolean;
}) {
  const [scope, setScope] = useState("global");
  const [slot, setSlot] = useState<Slot>("weapon");
  const [item, setItem] = useState("");
  const [error, setError] = useState("");
  // Single-style has one configuration, so its locks are always role locks.
  const validScope = isSingle
    ? draft.roles[0].id
    : scope === "global" || draft.roles.some((role) => role.id === scope)
      ? scope
      : "global";
  function setLock(value: string) {
    const id = value.trim().toLowerCase() === "empty" ? null : Number(value);
    if (
      id !== null &&
      (!value.trim() || !Number.isSafeInteger(id) || id <= 0)
    ) {
      setError("Enter a positive physical item ID or empty.");
      return;
    }
    setError("");
    change(
      validScope === "global"
        ? { globalLocks: { ...draft.globalLocks, [slot]: id } }
        : {
            roles: draft.roles.map((role) =>
              role.id === validScope
                ? { ...role, locks: { ...role.locks, [slot]: id } }
                : role,
            ),
          },
    );
  }
  return (
    <div className="raised">
      {!isSingle && (
        <label>
          Constraint scope
          <select
            value={validScope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="global">All configurations</option>
            {draft.roles.map((role) => (
              <option value={role.id} key={role.id}>
                {role.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Equipment slot
        <select
          value={slot}
          onChange={(event) => setSlot(event.target.value as Slot)}
        >
          {slots.map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <ItemSearch
        label="Find item to lock"
        slot={slot}
        onPick={(picked) => setLock(String(picked.id))}
      />
      <ItemSearch
        label="Find item to exclude"
        slot={slot}
        onPick={(picked) => {
          setError("");
          if (!draft.exclusions.includes(picked.id))
            change({ exclusions: [...draft.exclusions, picked.id] });
        }}
      />
      <label>
        Physical item ID or empty
        <input
          value={item}
          placeholder="6585 or empty"
          onChange={(event) => setItem(event.target.value)}
        />
      </label>
      <button onClick={() => setLock(item)}>Set equipment lock</button>
      {error && <p role="alert">{error}</p>}
      {Object.entries(draft.globalLocks ?? {}).map(([key, id]) => (
        <div className="constraint" key={key}>
          Global {key}: {id === null ? "empty" : itemLabel(id)}
          <button
            onClick={() => {
              const locks = { ...draft.globalLocks };
              delete locks[key as Slot];
              change({ globalLocks: locks });
            }}
          >
            Unlock global {key}
          </button>
        </div>
      ))}
      <p>
        {isSingle
          ? "Picking an item locks or excludes it right away. Enter empty to keep a slot empty. Requirements are checked when you run."
          : "Picking an item locks or excludes it right away. Exclusions apply to every configuration. Global and role locks must agree. Requirements and conflicts are checked when you run."}
      </p>
    </div>
  );
}
