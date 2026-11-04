import type { Draft, Slot } from "../api/contracts";

/** Lists role locks and exclusions with per-item and clear-all removal. */
export function LockConstraints({
  draft,
  change,
  itemLabel,
}: {
  draft: Draft;
  change: (patch: Partial<Draft>) => void;
  itemLabel: (id: number) => string;
}) {
  const hasGlobalLocks = Object.keys(draft.globalLocks ?? {}).length > 0;
  const hasRoleLocks = draft.roles.some(
    (role) => Object.keys(role.locks).length > 0,
  );
  const hasLocks = hasGlobalLocks || hasRoleLocks;
  const hasExclusions = draft.exclusions.length > 0;
  const unlock = (roleId: string, slot: Slot) =>
    change({
      roles: draft.roles.map((role) => {
        if (role.id !== roleId) return role;
        const locks = { ...role.locks };
        delete locks[slot];
        return { ...role, locks };
      }),
    });
  if (!hasLocks && !hasExclusions)
    return <p className="target-hint">No locks or exclusions yet.</p>;
  return (
    <>
      {draft.roles
        .filter((role) => Object.keys(role.locks).length > 0)
        .map((role) => (
          <div key={role.id}>
            <strong>{role.name}</strong>
            {Object.entries(role.locks).map(([slot, id]) => (
              <div className="constraint" key={slot}>
                {slot}: {id === null ? "empty" : itemLabel(id)}
                <button onClick={() => unlock(role.id, slot as Slot)}>
                  Unlock {slot}
                </button>
              </div>
            ))}
          </div>
        ))}
      {draft.exclusions.map((id) => (
        <button
          key={id}
          onClick={() =>
            change({ exclusions: draft.exclusions.filter((i) => i !== id) })
          }
        >
          Remove exclusion {itemLabel(id)}
        </button>
      ))}
      <div className="option-shortcuts">
        {hasLocks && (
          <button
            type="button"
            onClick={() =>
              change({
                globalLocks: {},
                roles: draft.roles.map((role) => ({ ...role, locks: {} })),
              })
            }
          >
            Clear all locks
          </button>
        )}
        {hasExclusions && (
          <button type="button" onClick={() => change({ exclusions: [] })}>
            Clear all exclusions
          </button>
        )}
      </div>
    </>
  );
}
