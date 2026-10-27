import { useState } from "react";
import { slots, type Draft, type Slot } from "../api/contracts";

export function MultiLockEditor({
  draft,
  change,
}: {
  draft: Draft;
  change: (patch: Partial<Draft>) => void;
}) {
  const [scope, setScope] = useState("global");
  const [slot, setSlot] = useState<Slot>("weapon");
  const [item, setItem] = useState("");
  const [error, setError] = useState("");
  const validScope =
    scope === "global" || draft.roles.some((role) => role.id === scope)
      ? scope
      : "global";
  function setLock() {
    const id = item.trim().toLowerCase() === "empty" ? null : Number(item);
    if (id !== null && (!item.trim() || !Number.isSafeInteger(id) || id <= 0)) {
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
      <label>
        Physical item ID or empty
        <input
          value={item}
          placeholder="6585 or empty"
          onChange={(event) => setItem(event.target.value)}
        />
      </label>
      <button onClick={setLock}>Set equipment lock</button>
      {error && <p role="alert">{error}</p>}
      {Object.entries(draft.globalLocks ?? {}).map(([key, id]) => (
        <div className="constraint" key={key}>
          Global {key}: {id ?? "empty"}
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
        Locks require a compatible physical item, and global and role locks must
        agree. Python validates requirements and conflicts on submission.
      </p>
    </div>
  );
}
