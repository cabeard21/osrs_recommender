export function UntradeablesToObtain({
  ids = [],
  itemName,
  acquisitionNotes,
  usedBy,
}: {
  ids?: number[];
  itemName: (id: number) => string;
  acquisitionNotes?: (id: number) => string[];
  usedBy?: (id: number) => string[];
}) {
  if (!ids.length) return null;
  return (
    <section aria-label="Untradeables to obtain">
      <h3>Untradeables to obtain</h3>
      <p>
        Hypothetical upgrades. Obtain these separately; they do not use the GP
        budget. Ownership is unchanged.
      </p>
      <ul>
        {ids.map((id) => {
          const roles = usedBy?.(id) ?? [];
          return (
            <li key={id}>
              <span>{itemName(id)}</span>
              {roles.length > 0 && <small>Used by {roles.join(", ")}</small>}
              {acquisitionNotes?.(id).map((note) => (
                <p key={note}>{note}</p>
              ))}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
