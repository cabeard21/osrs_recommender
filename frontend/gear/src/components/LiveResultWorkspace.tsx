import { DisciplineTabs } from "./DisciplineTabs";
import { AmmoComparison } from "./AmmoComparison";
import { EquipmentBonuses } from "./EquipmentBonuses";
import { RunningCostFrontier } from "./RunningCostFrontier";
import { SecondaryFrontier } from "./SecondaryFrontier";
import { SupportPolicySummary } from "./SupportPolicySummary";
import { Shield } from "lucide-react";
import { emptyEquipment, slots } from "../api/contracts";
import type { OptimizationReply } from "../api/contracts";
import { useGear } from "../state/GearProvider";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { PurchaseListCopy } from "./PurchaseListCopy";
import { PurchaseRows, purchaseSummary } from "./PurchaseRows";
import { SecondaryPrioritySummary } from "./SecondaryPrioritySummary";
import { OptimizationModeSummary } from "./OptimizationModeSummary";
import { CombatOptionSummary } from "./CombatOptionSummary";
import { ResultVerdict } from "./ResultVerdict";
import { EQUIPMENT_ACCESS_LABELS, equipmentFor } from "./resultFormat";
import { matchesSecondaryPriority } from "../api/secondaryPriorities";
import { matchesOptimizationPolicy } from "../api/optimizationModes";

function comparable(a: OptimizationReply, b: OptimizationReply) {
  const combat = (r: OptimizationReply) => {
    const role = r.scenario.request.roles[0];
    const serverRoles = r.live?.scenario.roles as
      { target: unknown }[] | undefined;
    return JSON.stringify({
      target: serverRoles?.[0]?.target ?? r.scenario.request.target,
      style: role.style,
      autoDiscipline: role.autoDiscipline,
      allowedDisciplines: role.allowedDisciplines,
      attackType: role.attackType,
      stance: role.stance,
      spell: role.spell,
      combatOptions: role.combatOptions,
    });
  };
  return (
    matchesSecondaryPriority(a, b) &&
    matchesOptimizationPolicy(a, b) &&
    a.snapshotId === b.snapshotId &&
    a.catalogVersion === b.catalogVersion &&
    a.modelVersion === b.modelVersion &&
    a.priceRevision === b.priceRevision &&
    a.live?.result.assumptions_fingerprint ===
      b.live?.result.assumptions_fingerprint &&
    combat(a) === combat(b)
  );
}
export function LiveResultWorkspace() {
  const { state, current, dispatch, itemById } = useGear();
  const result = current.result;
  const branches = result?.live?.result.discipline_results ?? [];
  const branch = branches.find((row) =>
    current.solutionId.startsWith(`discipline-${row.discipline}-`),
  );
  const active = branch?.discipline ?? "overall";
  const viewResult =
    branch && result?.live
      ? {
          ...result,
          live: {
            ...result.live,
            result: {
              ...result.live.result,
              search: branch.search,
              limitations: branch.limitations,
              selected_solution: branch.selected_solution,
            },
          },
        }
      : result;
  const solution =
    result?.solutions.find((s) => s.id === current.solutionId) ??
    (branch ? undefined : result?.solutions[0]);
  const selected =
    solution?.live ??
    (branch
      ? branch.selected_solution
      : result?.live?.result.selected_solution);
  const loadout = solution?.loadouts[0];
  const previous = current.previous;
  const ammoLoadout = Object.values(selected?.loadouts ?? {})[0];
  const select = (slot: keyof ReturnType<typeof emptyEquipment>) =>
    dispatch({
      type: "ui",
      mode: state.mode,
      patch: { slot, activeRole: loadout?.roleId ?? "role-1" },
    });
  if (!result)
    return (
      <section className="panel empty-result">
        <h2>Find your best configuration</h2>
        <p>
          Choose your target, combat style and budget, then run optimization.
        </p>
      </section>
    );
  const baseline = result.live?.baseline;
  const baselineEquipment =
    baseline?.status === "available" ? equipmentFor(baseline.equipment) : null;
  const changedSlots =
    baselineEquipment && loadout
      ? slots.filter(
          (slot) => baselineEquipment[slot] !== loadout.equipment[slot],
        )
      : [];
  const request = result.scenario.request;
  const isComparableToPrevious = !!previous && comparable(previous, result);
  // The previous run only offers its overall best, so tabs and tradeoff points have no peer.
  const previousDps =
    isComparableToPrevious && solution === result.solutions[0]
      ? previous.solutions[0]?.loadouts[0]?.metrics?.dps
      : undefined;
  const isAttackStyleOptimized =
    !!request.roles[0].autoDiscipline || !!request.roles[0].combatOptions;
  const isUnsynced = !state.context?.live?.account?.last_sync_at;
  const itemName = (id: number) => itemById(id)?.name ?? `Item #${id}`;
  const roleName = (roleId: string) =>
    request.roles.find((role) => role.id === roleId)?.name ?? "Loadout";
  return (
    <div className="result-column">
      {branches.length > 0 && (
        <DisciplineTabs
          disciplines={branches.map((row) => row.discipline)}
          active={active}
          onSelect={(discipline) =>
            dispatch({
              type: "ui",
              mode: state.mode,
              patch: {
                solutionId:
                  discipline === "overall"
                    ? "best-found"
                    : `discipline-${discipline}-best-found`,
                slot: null,
              },
            })
          }
        />
      )}
      <div
        id="discipline-loadouts"
        className="result-column"
        role={branches.length ? "tabpanel" : undefined}
        aria-labelledby={
          branches.length ? `discipline-tab-${active}` : undefined
        }
      >
        {branch && (
          <p role="status">
            Viewing {branch.discipline} loadouts
            {branch.reasons.length ? `: ${branch.reasons.join(" ")}` : ""}
          </p>
        )}
        {current.outdated && (
          <p role="status" className="notice">
            Result outdated — draft inputs, account, prices, catalog or model
            changed. Re-run to use the draft and current context.
          </p>
        )}
        {request.mode === "future" && (
          <p className="notice">
            Hypothetical submitted result · assumptions retained with this
            result
          </p>
        )}
        {loadout ? (
          <section
            className={`panel equipment-panel ${current.outdated ? "is-stale" : ""}`}
          >
            <div className="section-title">
              <h2>
                <Shield size={19} />
                Best configuration found
              </h2>
              <span className="badge">
                {previous ? "Reoptimized result" : "Optimized result"}
              </span>
            </div>
            {loadout.metrics && (
              <ResultVerdict
                dps={loadout.metrics.dps}
                baseline={baseline}
                previousDps={previousDps}
                isAttackStyleOptimized={isAttackStyleOptimized}
              />
            )}
            {solution && (
              <p className="result-cost">
                {purchaseSummary(solution.purchases.length, solution.cost)}
              </p>
            )}
            {loadout.metrics && (
              <PerformanceSummary
                metrics={loadout.metrics}
                live
                title="Calculated combat performance"
              />
            )}
            <p>
              Select any slot to inspect it. Best found, not guaranteed optimal.
            </p>
            <EquipmentGrid
              equipment={loadout.equipment}
              selected={current.slot}
              onSelect={select}
              optimized
              purchaseIds={solution?.purchases}
              roleId={loadout.roleId}
              differences={changedSlots}
              differenceLabel="Changed"
            />
            <CombatOptionSummary
              performance={selected?.loadouts[loadout.roleId]?.performance}
              option={loadout.combatOption}
              role={request.roles[0]}
              weapon={
                itemById(loadout.equipment.weapon ?? -1)?.name ?? "Unarmed"
              }
            />
            <details>
              <summary>Equipment bonuses</summary>
              <EquipmentBonuses
                bonuses={
                  selected?.loadouts[loadout.roleId]?.performance.bonuses
                }
              />
            </details>
          </section>
        ) : (
          <section className="panel">
            <h2>No feasible solution found within this search</h2>
            {isUnsynced && (
              <p className="notice">
                No account data has been synced, so nothing can be confirmed as
                owned or wearable. Sync with RuneLite, then refresh your
                account.
              </p>
            )}
            <p>
              No legal combat configuration may satisfy the selected filters and
              equipment constraints. Change the options or other constraints and
              run again. Bounded search does not prove that no legal
              configuration exists.
            </p>
          </section>
        )}
        {solution && (
          <section className="panel">
            <h2>What to buy</h2>
            <strong className="gold numeric">
              {solution.cost.toLocaleString()} GP additional purchases
            </strong>
            <p>
              {solution.purchases.length
                ? "Concrete purchases counted once; cached estimates are not guaranteed execution prices."
                : "No additional purchases required."}
            </p>
            <PurchaseRows
              purchases={selected?.purchases ?? []}
              itemName={itemName}
            />
            <PurchaseListCopy
              key={`${result.fingerprint}:${result.priceRevision}:${current.solutionId}`}
              purchases={selected?.purchases ?? []}
              itemName={itemName}
            />
            <h3 className="eyebrow">Gear you already own</h3>
            <p>
              {Object.values(loadout!.equipment)
                .filter((id) => id !== null && itemById(id)?.owned)
                .map((id) => itemById(id)?.name)
                .join(" · ") || "None confirmed"}
            </p>
            {request.assumed_item_ids.length > 0 && (
              <p className="notice">
                Hypothetically acquired IDs:{" "}
                {request.assumed_item_ids.join(", ")}. Acquisition is assumed;
                no account ownership changes.
              </p>
            )}
            <p>
              Inspect each item for ownership observations, missing prices and
              selected price provenance.
            </p>
          </section>
        )}
        {!!result.live?.result.discipline_comparison?.length && (
          <section className="panel" aria-label="Combat discipline comparison">
            <h2>Combat discipline comparison</h2>
            <table>
              <thead>
                <tr>
                  <th>Discipline</th>
                  <th>Best-found DPS</th>
                  <th>Purchase cost</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {result.live.result.discipline_comparison.map((row) => (
                  <tr key={row.discipline}>
                    <th scope="row">{row.discipline}</th>
                    <td>{row.score?.toFixed(3) ?? "Unavailable"}</td>
                    <td>
                      {row.purchase_cost_gp === null
                        ? "Unavailable"
                        : `${row.purchase_cost_gp.toLocaleString()} GP`}
                    </td>
                    <td>
                      {row.status === "best_found"
                        ? "Best found"
                        : row.reasons.join(" ") ||
                          "No feasible setup found within this search."}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
        {(branch
          ? branch.discipline === "magic"
          : request.roles.some(
              (role) =>
                role.style === "magic" ||
                (role.autoDiscipline &&
                  (
                    role.allowedDisciplines ?? ["melee", "ranged", "magic"]
                  ).includes("magic")),
            )) && (
          <RunningCostFrontier
            group={(
              branch?.running_cost_frontiers ??
              result.live?.result.running_cost_frontiers
            )?.find((g) => g.swap_limit === request.max_swaps)}
            selectedId={current.solutionId}
            selected={selected}
            itemName={itemName}
            roleName={roleName}
            onSelect={(solutionId) =>
              dispatch({ type: "ui", mode: state.mode, patch: { solutionId } })
            }
          />
        )}
        <SecondaryFrontier
          group={(
            branch?.secondary_frontiers ??
            result.live?.result.secondary_frontiers
          )?.find((g) => g.swap_limit === request.max_swaps)}
          selectedId={current.solutionId}
          priority={request.secondary_priority ?? "default"}
          legacyCapped={(request.max_dps_loss_pct ?? 10) < 100}
          onSelect={(solutionId) =>
            dispatch({ type: "ui", mode: state.mode, patch: { solutionId } })
          }
        />
        {result.live &&
          ammoLoadout &&
          (ammoLoadout.discipline === "ranged" ||
            ammoLoadout.combat_option?.attack_type === "ranged" ||
            request.roles[0].style === "ranged") && (
            <AmmoComparison
              scenario={result.live.scenario}
              loadout={ammoLoadout.equipment}
              combatOption={ammoLoadout.combat_option}
              identity={{
                snapshot_id: result.snapshotId,
                catalog_version: result.catalogVersion,
                price_revision: result.priceRevision,
                model_version: result.modelVersion,
                assumptions_fingerprint:
                  result.live.result.assumptions_fingerprint,
                scenario_fingerprint: result.live.scenario_fingerprint,
              }}
              outdated={current.outdated}
            />
          )}
        <section className="panel result-context">
          <span className="eyebrow gold">This result used</span>
          <strong>{request.target.name}</strong>
          <p>
            {request.target.defence} defence ·{" "}
            {request.budget_gp.toLocaleString()} GP additional budget ·{" "}
            {EQUIPMENT_ACCESS_LABELS[request.mode]} ·{" "}
            {request.roles[0].autoDiscipline
              ? `Auto selected ${Object.values(result.live?.result.selected_solution?.loadouts ?? {})[0]?.discipline ?? "no discipline"}`
              : `${request.roles[0].style} combat`}{" "}
            ·{" "}
            {request.roles[0].combatOptions
              ? "attack style chosen automatically"
              : "fixed attack style"}
          </p>
          <details>
            <summary>Submitted constraints and assumptions</summary>
            <pre className="fact-json">
              {JSON.stringify(result.live?.scenario, null, 2)}
            </pre>
          </details>
        </section>
        {previous && (
          <details className="panel">
            <summary>Previous configuration comparison</summary>
            <h2>Previous configuration comparison</h2>
            <p>
              Previous accepted result · {previous.scenario.request.target.name}{" "}
              · budget {previous.scenario.request.budget_gp.toLocaleString()} GP
              · {previous.modelVersion}
            </p>
            <details>
              <summary>Previous result provenance</summary>
              <p>Account: {previous.snapshotId}</p>
              <p>Catalog: {previous.catalogVersion}</p>
              <p>Prices: {previous.priceRevision}</p>
              <p>Evaluated: {previous.evaluatedAt}</p>
            </details>
            {isComparableToPrevious &&
            previous.solutions[0]?.loadouts[0]?.metrics &&
            solution?.loadouts[0]?.metrics ? (
              <p>
                Calculated DPS:{" "}
                {previous.solutions[0].loadouts[0].metrics.dps.toFixed(2)} →{" "}
                {solution.loadouts[0].metrics.dps.toFixed(2)}
              </p>
            ) : (
              <p>
                Performance comparison unavailable: account, target, combat
                assumptions, catalog, model, optimization mode or work budget
                differ, or a result has no feasible solution.
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
          </details>
        )}
        <SupportPolicySummary result={viewResult!} />
        <SecondaryPrioritySummary result={viewResult!} solution={selected} />
        <OptimizationModeSummary result={viewResult!} solution={selected} />
      </div>
    </div>
  );
}
