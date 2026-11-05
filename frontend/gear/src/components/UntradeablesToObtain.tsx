export function UntradeablesToObtain({
  ids = [],
  itemName,
}: {
  ids?: number[];
  itemName: (id: number) => string;
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
        {ids.map((id) => (
          <li key={id}>{itemName(id)}</li>
        ))}
      </ul>
    </section>
  );
}
