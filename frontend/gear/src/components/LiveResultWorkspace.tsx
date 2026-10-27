import { Shield } from "lucide-react";
import { emptyEquipment } from "../api/contracts";
import type { OptimizationReply } from "../api/contracts";
import { performanceMetrics } from "../api/httpClient";
import { useGear } from "../state/GearProvider";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { PurchaseListCopy } from "./PurchaseListCopy";

function comparable(a: OptimizationReply, b: OptimizationReply) {
  const combat = (r: OptimizationReply) => {
    const role = r.scenario.request.roles[0];
    const serverRoles = r.live?.scenario.roles as
      { target: unknown }[] | undefined;
    return JSON.stringify({
      target: serverRoles?.[0]?.target ?? r.scenario.request.target,
      style: role.style,
      attackType: role.attackType,
      stance: role.stance,
      spell: role.spell,
    });
  };
  return (
    a.snapshotId === b.snapshotId &&
    a.catalogVersion === b.catalogVersion &&
    a.modelVersion === b.modelVersion &&
    a.live?.result.assumptions_fingerprint ===
      b.live?.result.assumptions_fingerprint &&
    combat(a) === combat(b)
  );
}
export function LiveResultWorkspace() {
  const { state, current, dispatch, itemById } = useGear();
  const result = current.result;
  const solution = result?.solutions[0];
  const loadout = solution?.loadouts[0];
  const baseline = result?.live?.baseline;
  const previous = current.previous;
  const select = (slot: keyof ReturnType<typeof emptyEquipment>) =>
    dispatch({
      type: "ui",
      mode: state.mode,
      patch: { slot, activeRole: loadout?.roleId ?? "role-1" },
    });
  if (!result)
    return (
      <div className="result-column">
        <section className="panel equipment-panel">
          <div className="section-title">
            <h2>
              <Shield size={19} />
              Observed equipment
            </h2>
            <span className="badge">
              {state.context?.equipmentStatus ?? "unknown"}
            </span>
          </div>
          <p>
            Last observed:{" "}
            {state.context?.live?.current_equipment.scanned_at ??
              "No equipment scan"}
            . Select any slot to inspect.
          </p>
          <EquipmentGrid
            equipment={state.context?.equipment ?? emptyEquipment()}
            selected={current.slot}
            onSelect={select}
          />
          <p>
            Combat metrics become available after optimization when the observed
            equipment can be evaluated.
          </p>
        </section>
      </div>
    );
  return (
    <div className="result-column">
      <section className="panel result-context">
        <span className="eyebrow gold">
          Submitted scenario // Python optimizer
        </span>
        <strong>{result.scenario.request.target.name}</strong>
        <p>
          {result.scenario.request.target.defence} defence ·{" "}
          {result.scenario.request.budget_gp.toLocaleString()} GP additional
          budget · {result.scenario.request.mode}
        </p>
        <p>
          {result.scenario.request.roles[0].style} ·{" "}
          {result.scenario.request.roles[0].stance} ·{" "}
          {result.scenario.request.roles[0].style === "magic"
            ? result.scenario.request.roles[0].spell
            : result.scenario.request.roles[0].attackType}
        </p>
        {current.outdated && (
          <p role="status" className="notice">
            Result outdated — draft inputs, account, prices, catalog or model
            changed. Re-run to use the draft and current context.
          </p>
        )}
        {result.scenario.request.mode === "future" && (
          <p className="notice">
            Hypothetical submitted result · assumptions retained with this
            result
          </p>
        )}
        <details>
          <summary>Submitted constraints and assumptions</summary>
          <pre className="fact-json">
            {JSON.stringify(result.live?.scenario, null, 2)}
          </pre>
        </details>
      </section>
      {loadout ? (
        <section className="panel equipment-panel">
          <div className="section-title">
            <h2>
              <Shield size={19} />
              Best configuration found
            </h2>
            <span className="badge">
              {previous ? "Reoptimized result" : "Optimized result"}
            </span>
          </div>
          <p>Bounded search · select any slot to inspect its physical item.</p>
          <EquipmentGrid
            equipment={loadout.equipment}
            selected={current.slot}
            onSelect={select}
            optimized
          />
          <PerformanceSummary
            metrics={loadout.metrics}
            live
            title="Calculated combat performance"
          />
          <details>
            <summary>Equipment bonuses</summary>
            <dl>
              {Object.entries(
                result.live!.result.selected_solution!.loadouts[loadout.roleId]
                  .performance.bonuses,
              ).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </details>
        </section>
      ) : (
        <section className="panel">
          <h2>No feasible solution found within this search</h2>
          <p>
            Change the supported constraints and run again. Bounded search does
            not prove that no legal configuration exists.
          </p>
        </section>
      )}
      <section className="panel">
        <h2>Current equipment comparison</h2>
        {baseline?.status === "available" && baseline.performance ? (
          <>
            <p>
              Observed equipment evaluated against the submitted target and
              combat assumptions. New purchase budget and locks do not restrict
              this baseline.
            </p>
            <PerformanceSummary
              metrics={performanceMetrics(baseline.performance)}
              live
              title="Observed equipment performance"
            />
            {loadout && (
              <p>
                Current equipment DPS {baseline.performance.dps?.toFixed(2)} →
                best configuration found {loadout.metrics.dps.toFixed(2)}
              </p>
            )}
          </>
        ) : (
          <>
            <p>Current equipment baseline unavailable.</p>
            {baseline?.reasons.map((reason) => (
              <p className="notice" key={reason}>
                {reason}
              </p>
            ))}
          </>
        )}
      </section>
      {solution && (
        <section className="panel">
          <h2>Acquisition requirements</h2>
          <strong className="gold numeric">
            {solution.cost.toLocaleString()} GP additional purchases
          </strong>
          <p>
            {solution.purchases.length
              ? "Concrete purchases counted once; cached estimates are not guaranteed execution prices."
              : "No additional purchases required."}
          </p>
          {result.live?.result.selected_solution?.purchases.map((p) => (
            <p key={p.item_id}>
              {itemById(p.item_id)?.name ?? `Item #${p.item_id}`} ·{" "}
              {p.cost_gp === null
                ? "Price unavailable"
                : `${p.cost_gp.toLocaleString()} GP`}
              {p.conditional
                ? " · conditional purchase: ownership uncertain"
                : ""}
            </p>
          ))}
          <PurchaseListCopy
            key={`${result.fingerprint}:${result.priceRevision}`}
            purchases={result.live?.result.selected_solution?.purchases ?? []}
            itemName={(id) => itemById(id)?.name ?? `Item #${id}`}
          />
          <h3 className="eyebrow">Reused observed owned equipment</h3>
          <p>
            {Object.values(loadout!.equipment)
              .filter((id) => id !== null && itemById(id)?.owned)
              .map((id) => itemById(id)?.name)
              .join(" · ") || "None confirmed"}
          </p>
          {result.scenario.request.assumed_item_ids.length > 0 && (
            <p className="notice">
              Hypothetically acquired IDs:{" "}
              {result.scenario.request.assumed_item_ids.join(", ")}. Acquisition
              is assumed; no account ownership changes.
            </p>
          )}
          <p>
            Inspect each item for ownership observations, missing prices and
            selected price provenance.
          </p>
        </section>
      )}
      {previous && (
        <section className="panel">
          <h2>Previous configuration comparison</h2>
          <p>
            Previous accepted result · {previous.scenario.request.target.name} ·
            budget {previous.scenario.request.budget_gp.toLocaleString()} GP ·{" "}
            {previous.modelVersion}
          </p>
          <details>
            <summary>Previous result provenance</summary>
            <p>Account: {previous.snapshotId}</p>
            <p>Catalog: {previous.catalogVersion}</p>
            <p>Prices: {previous.priceRevision}</p>
            <p>Evaluated: {previous.evaluatedAt}</p>
          </details>
          {comparable(previous, result) && previous.solutions[0] && solution ? (
            <p>
              Calculated DPS:{" "}
              {previous.solutions[0].loadouts[0].metrics.dps.toFixed(2)} →{" "}
              {solution.loadouts[0].metrics.dps.toFixed(2)}
            </p>
          ) : (
            <p>
              Performance comparison unavailable: account, target, combat
              assumptions, catalog or model differ, or a result has no feasible
              solution.
            </p>
          )}
          <details>
            <summary>Previous submitted scenario</summary>
            <pre className="fact-json">
              {JSON.stringify(
                previous.live?.scenario ?? previous.scenario,
                null,
                2,
              )}
            </pre>
          </details>
        </section>
      )}
    </div>
  );
}
