export function ResultFreshness({
  outdated,
  draftChanged,
  contextStale,
}: {
  outdated: boolean;
  draftChanged: boolean;
  contextStale: boolean;
}) {
  if (!outdated) return null;
  return (
    <p role="status" className="notice">
      Result outdated. {draftChanged && "Draft settings have changed. "}
      {contextStale && "Account, price, catalog or model data has changed. "}
      Reoptimize to use current settings and data.
    </p>
  );
}
