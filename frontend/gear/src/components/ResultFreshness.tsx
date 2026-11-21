export function ResultFreshness({
  outdated,
  draftChanged,
  contextStale,
  newerSnapshot,
}: {
  outdated: boolean;
  draftChanged: boolean;
  contextStale: boolean;
  newerSnapshot: boolean;
}) {
  if (!outdated) return null;
  return (
    <p role="status" className="notice">
      Result outdated. {draftChanged && "Draft settings have changed. "}
      {newerSnapshot
        ? "Newer account observations are available. This result uses the snapshot captured for the run. "
        : contextStale && "Account, price, catalog or model data has changed. "}
      Reoptimize to use current settings and data.
    </p>
  );
}
