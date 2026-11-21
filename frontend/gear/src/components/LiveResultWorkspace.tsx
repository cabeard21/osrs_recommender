import { DisciplineTabs } from "./DisciplineTabs";
import { AcquisitionChecklist } from "./AcquisitionChecklist";
import { EquipmentBonuses } from "./EquipmentBonuses";
import { RunningCostFrontier } from "./RunningCostFrontier";
import { SecondaryFrontier } from "./SecondaryFrontier";
import { ObjectiveFrontier } from "./ObjectiveFrontier";
import { SupportPolicySummary } from "./SupportPolicySummary";
import { Shield } from "lucide-react";
import { emptyEquipment, slots } from "../api/contracts";
import type { OptimizationReply } from "../api/contracts";
import { archiveRunId, resolveResultSelection } from "../state/resultSelection";
import { useGear } from "../state/GearProvider";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { purchaseSummary } from "./PurchaseRows";
import { ResultFreshness } from "./ResultFreshness";
import { NoSolutionHints } from "./NoSolutionHints";
import { SecondaryPrioritySummary } from "./SecondaryPrioritySummary";
import { OptimizationModeSummary } from "./OptimizationModeSummary";
import { CombatOptionSummary } from "./CombatOptionSummary";
import { contextPrayers } from "./PrayerFields";
import { ResultVerdict } from "./ResultVerdict";
import { EQUIPMENT_ACCESS_LABELS, equipmentFor } from "./resultFormat";
import { matchesSecondaryPriority } from "../api/secondaryPriorities";
import { matchesOptimizationPolicy } from "../api/optimizationModes";
import { budgetSummary, WildernessRiskDetails } from "./WildernessRiskDetails";

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
  const {
    state,
    current,
    dispatch,
    itemById,
    client,
    selectObjective,
    labOriginId,
  } = useGear();
  const result = current.result;
  if (!result)
    return (
      <section className="panel empty-result">
        <h2>Find your best configuration</h2>
        <p>
          Choose your target, combat style and budget, then run optimization.
        </p>
      </section>
    );
  const branches = result.live?.result.discipline_results ?? [];
  const {
    branch,
    cap: selectedSwapLimit,
    parsed: solution,
    selected,
  } = resolveResultSelection(
    result,
    current.solutionId,
    current.objectiveGroupId,
    current.objectiveSwapLimit,
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
              objective_definitions: branch.objective_definitions,
              objective_frontiers: branch.objective_frontiers,
            },
          },
        }
      : result;
  const loadout = solution?.loadouts[0];
  const wildernessRisk = solution?.wildernessRisk;
  const previous = current.previous;
  const select = (slot: keyof ReturnType<typeof emptyEquipment>) =>
    dispatch({
      type: "ui",
      mode: state.mode,
      patch: { slot, activeRole: loadout?.roleId ?? "role-1" },
    });
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
  const isDefault =
    current.solutionId ===
    (branch
      ? `discipline-${branch.discipline}-best-found`
      : (result.selectedSolutionId ?? "best-found"));
  const isComparableToPrevious = !!previous && comparable(previous, result);
  // The previous run only offers its overall best, so tabs and tradeoff points have no peer.
  const previousDps =
    isComparableToPrevious && isDefault && !branch
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
        <ResultFreshness
          outdated={current.outdated}
          draftChanged={current.draftChanged}
          contextStale={current.contextStale}
        />
        {request.mode === "future" && (
          <p className="notice">
            Hypothetical submitted result · assumptions retained with this
            result
          </p>
        )}
        {loadout ? (
          <section
            id="selected-outfit"
            tabIndex={-1}
            className={`panel equipment-panel ${current.outdated ? "is-stale" : ""}`}
          >
            <div className="section-title">
              <h2>
                <Shield size={19} />
                {isDefault ? "Best configuration found" : "Selected setup"}
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
              preparations={selected?.loadouts[loadout.roleId]?.preparations}
              obtainIds={selected?.unowned_untradeable_item_ids}
              roleId={loadout.roleId}
              differences={changedSlots}
              differenceLabel="Changed"
            />
            <CombatOptionSummary
              itemName={(id) => itemById(id)?.name ?? `Item #${id}`}
              prayerIds={
                selected?.loadouts[loadout.roleId]?.selected_prayer_ids
              }
              prayerCatalog={contextPrayers(state.context)}
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
            <NoSolutionHints
              hints={viewResult.live?.result.search.no_solution_hints}
            />
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
            {request.wilderness && (
              <p>
                Gear with an unknown loss is excluded from Wilderness
                recommendations.
              </p>
            )}
          </section>
        )}
        {request.wilderness && wildernessRisk && (
          <section className="panel" aria-label="Wilderness risk">
            <h2>Wilderness risk</h2>
            <WildernessRiskDetails
              risk={wildernessRisk}
              policy={request.wilderness}
              itemName={itemName}
            />
          </section>
        )}
        {selected && (
          <AcquisitionChecklist
            solution={selected}
            roles={request.roles}
            itemById={itemById}
            selectionKey={`${archiveRunId(result) ?? result.fingerprint}:${current.solutionId}`}
          />
        )}
        {request.assumed_item_ids.length > 0 && (
          <p className="notice">
            Hypothetically acquired IDs: {request.assumed_item_ids.join(", ")}.
          </p>
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
        <RunningCostFrontier
          group={(
            branch?.running_cost_frontiers ??
            result.live?.result.running_cost_frontiers
          )?.find((g) => g.swap_limit === selectedSwapLimit)}
          selectedId={current.solutionId}
          selected={selected}
          itemName={itemName}
          roleName={roleName}
          onSelect={(solutionId) =>
            dispatch({ type: "ui", mode: state.mode, patch: { solutionId } })
          }
        />
        {request.objectives !== undefined && (
          <ObjectiveFrontier
            result={viewResult!}
            swapLimit={selectedSwapLimit}
            selectedId={current.solutionId}
            selectedSolution={selected}
            labOriginId={labOriginId}
            selectionRevision={current.selectionRevision}
            onSelect={(id, raw, runId, groupId, selectionRevision) =>
              selectObjective(
                state.mode,
                id,
                raw,
                selectedSwapLimit,
                result.fingerprint,
                runId,
                groupId,
                selectionRevision,
              )
            }
          />
        )}
        <SecondaryFrontier
          group={(
            branch?.secondary_frontiers ??
            result.live?.result.secondary_frontiers
          )?.find((g) => g.swap_limit === selectedSwapLimit)}
          selectedId={current.solutionId}
          priority={request.secondary_priority ?? "default"}
          legacyCapped={(request.max_dps_loss_pct ?? 10) < 100}
          onSelect={(solutionId) =>
            dispatch({ type: "ui", mode: state.mode, patch: { solutionId } })
          }
        />
        <section className="panel result-context">
          <span className="eyebrow gold">This result used</span>
          <strong>{request.target.name}</strong>
          <p>
            {request.target.defence} defence · {budgetSummary(request)} ·{" "}
            {EQUIPMENT_ACCESS_LABELS[request.mode]} ·{" "}
            {request.roles[0].autoDiscipline
              ? `Auto selected ${selected?.loadouts[request.roles[0].id]?.discipline ?? loadout?.discipline ?? "no discipline"}`
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
              · {budgetSummary(previous.scenario.request)} ·{" "}
              {previous.modelVersion}
            </p>
            <details>
              <summary>Previous result provenance</summary>
              <p>Account: {previous.snapshotId}</p>
              <p>Catalog: {previous.catalogVersion}</p>
              <p>Prices: {previous.priceRevision}</p>
              <p>Evaluated: {previous.evaluatedAt}</p>
            </details>
            {isComparableToPrevious &&
            isDefault &&
            !branch &&
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
        <SecondaryPrioritySummary
          client={client}
          outdated={current.outdated || current.pending}
          result={viewResult!}
          solution={selected}
          potionCatalog={state.context?.live?.potion_catalog}
        />
        <OptimizationModeSummary result={viewResult!} solution={selected} />
      </div>
    </div>
  );
}
