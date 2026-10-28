import type { OptimizationReply } from "../api/contracts";
export function SupportPolicySummary({
  result,
}: {
  result: OptimizationReply;
}) {
  const community =
    result.scenario.request.support_policy === "community_best_effort";
  return (
    <section className="panel" aria-label="Equipment support policy result">
      <p>
        Equipment support:{" "}
        {community ? "Community best effort" : "Verified only"}.
      </p>
      {community && (
        <p>
          Community-assumed equipment uses known skill requirements and existing
          physical statistics. Unresolved equip gates are assumed satisfied for
          classified ordinary items. Known unsupported mechanics remain
          excluded; this is not verified eligibility.
        </p>
      )}
      {result.live?.result.support_provenance && (
        <p>Assumption source: {result.live.result.support_provenance}</p>
      )}
    </section>
  );
}
