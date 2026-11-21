import { EquipmentBonuses } from "./EquipmentBonuses";
import { AcquisitionChecklist } from "./AcquisitionChecklist";
import { RunningCostFrontier } from "./RunningCostFrontier";
import { SecondaryFrontier } from "./SecondaryFrontier";
import { ObjectiveFrontier } from "./ObjectiveFrontier";
import { SupportPolicySummary } from "./SupportPolicySummary";
import { Shield } from "lucide-react";
import { slots } from "../api/contracts";
import type { JointSolutionDTO, Slot } from "../api/contracts";
import { performanceMetrics } from "../api/httpClient";
import { useGear } from "../state/GearProvider";
import { archiveRunId, resolveResultSelection } from "../state/resultSelection";
import { ResultFreshness } from "./ResultFreshness";
import { NoSolutionHints } from "./NoSolutionHints";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { purchaseSummary } from "./PurchaseRows";
import { SecondaryPrioritySummary } from "./SecondaryPrioritySummary";
import { OptimizationModeSummary } from "./OptimizationModeSummary";
import { CombatOptionSummary } from "./CombatOptionSummary";
import { contextPrayers } from "./PrayerFields";
import { EQUIPMENT_ACCESS_LABELS, equipmentFor } from "./resultFormat";
import { budgetSummary, WildernessRiskDetails } from "./WildernessRiskDetails";
import { JointInventory, JointTransition } from "./JointSolutionDetails";

function sharedIds(solution: JointSolutionDTO, roles: string[]): number[] {
  const counts = new Map<number, number>();
  for (const role of roles) {
    for (const id of new Set(Object.values(solution.loadouts[role].equipment)))
      counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return [...counts].filter(([, count]) => count > 1).map(([id]) => id);
}

export function LiveMultiResultWorkspace() {
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
  if (!result?.live)
    return (
      <section className="panel empty-result">
        <h2>Configure a joint optimization</h2>
        <p>
          Add two to four configurations, then run one joint optimization. All
          views will use that joint result.
        </p>
      </section>
    );
  const raw = result.live.result;
  const request = result.scenario.request;
  const roles = request.roles;
  const roleIds = roles.map((role) => role.id);
  const roleName = (id: string) =>
    roles.find((role) => role.id === id)?.name ?? id;
  const itemName = (id: number) => itemById(id)?.name ?? `Item #${id}`;
  const curve = raw.curve ?? [];
  const {
    curve: point,
    selected: solution,
    cap: selectedSwapLimit,
  } = resolveResultSelection(
    result,
    current.solutionId,
    current.objectiveGroupId,
    current.objectiveSwapLimit,
  );
  const isDefault =
    current.solutionId ===
    (result.selectedSolutionId ?? `curve-${request.max_swaps}`);
  const frontierGroup = raw.secondary_frontiers?.find(
    (g) => g.swap_limit === selectedSwapLimit,
  );
  const runningCostGroup = raw.running_cost_frontiers?.find(
    (g) => g.swap_limit === selectedSwapLimit,
  );
  const ui = (
    patch: Partial<
      Pick<
        typeof current,
        "solutionId" | "activeRole" | "selectedTransition" | "slot"
      >
    >,
  ) => dispatch({ type: "ui", mode: "multi", patch });
  const shared = solution ? sharedIds(solution, roleIds) : [];
  const isUnsynced = !state.context?.live?.account?.last_sync_at;
  function equipmentCard(id: string) {
    if (!solution?.loadouts[id]) return null;
    const loadout = solution.loadouts[id];
    const role = roles.find((entry) => entry.id === id)!;
    const equipment = equipmentFor(loadout.equipment);
    const others = roleIds
      .filter((otherId) => otherId !== id)
      .map((otherId) => equipmentFor(solution.loadouts[otherId].equipment));
    const differences = slots.filter((slot) =>
      others.some((other) => equipment[slot] !== other[slot]),
    );
    const performance = loadout.performance;
    const scored =
      performance.supported &&
      performance.dps !== null &&
      performance.max_hit !== null &&
      performance.accuracy !== null &&
      performance.attack_interval !== null;
    return (
      <section className="panel equipment-panel" key={id}>
        <div className="section-title">
          <h2>
            <Shield size={19} />
            {role.name}
          </h2>
          <span className="badge">Joint solution</span>
        </div>
        {role.utility ? (
          <p>Utility (unscored)</p>
        ) : (
          <>
            <p aria-label="Resolved combat discipline">
              {role.autoDiscipline ? "Auto selected " : "Discipline: "}
              {loadout.discipline ??
                (role.autoDiscipline ? "unavailable" : role.style)}
            </p>
            <CombatOptionSummary
              itemName={itemName}
              prayerIds={loadout.selected_prayer_ids}
              prayerCatalog={contextPrayers(state.context)}
              performance={loadout.performance}
              option={loadout.combat_option}
              role={{ ...role, style: loadout.discipline ?? role.style }}
              weapon={equipment.weapon ? itemName(equipment.weapon) : "Unarmed"}
            />
          </>
        )}
        <p>
          Target:{" "}
          {role.combatTarget?.name ??
            result!.scenario.request.target?.name ??
            "Submitted ordinary-attack target"}
          {role.combatTarget
            ? ` · Defence ${role.combatTarget.defence_level}`
            : ""}
          .
        </p>
        {raw.active_time_shares?.[id] !== undefined && (
          <p>
            Active-time share: {(raw.active_time_shares[id] * 100).toFixed(1)}%
          </p>
        )}
        <EquipmentGrid
          prefix={`${role.name} `}
          equipment={equipment}
          shared={shared}
          differences={differences}
          selected={current.activeRole === id ? current.slot : null}
          onSelect={(slot: Slot) => ui({ slot, activeRole: id })}
          optimized
          purchaseIds={solution.purchases.map((purchase) => purchase.item_id)}
          obtainIds={solution.unowned_untradeable_item_ids}
          preparations={loadout.preparations}
          roleId={id}
        />
        {scored ? (
          <PerformanceSummary
            metrics={performanceMetrics(performance)}
            live
            title={`${role.name} combat performance`}
          />
        ) : (
          <>
            <h3>
              {performance.supported
                ? "Unscored configuration"
                : "Combat performance unavailable"}
            </h3>
            {performance.limitations.map((reason) => (
              <p className="notice" key={reason}>
                {reason}
              </p>
            ))}
          </>
        )}
        <p>
          Differs from another configuration: {differences.join(", ") || "None"}
          .
        </p>
        <details>
          <summary>{role.name} equipment bonuses</summary>
          <EquipmentBonuses
            bonuses={performance.bonuses}
            title={`${role.name} equipment bonuses`}
          />
        </details>
        <details>
          <summary>Role assumptions</summary>
          <pre className="fact-json">
            {JSON.stringify({ performance, role }, null, 2)}
          </pre>
        </details>
      </section>
    );
  }
  const curvePanel = (
    <div className="curve-controls">
      <label>
        Swap-efficiency curve point
        <select
          value={
            selectedSwapLimit != null
              ? `curve-${selectedSwapLimit}`
              : "unrestricted"
          }
          onChange={(e) => ui({ solutionId: e.target.value })}
        >
          {curve.map((p) => (
            <option key={p.swap_limit} value={`curve-${p.swap_limit}`}>
              {p.swap_limit} equipment-action limit ·{" "}
              {p.solution
                ? `${p.solution.score.toFixed(2)} weighted DPS`
                : "No feasible solution found"}
            </option>
          ))}
          {raw.unrestricted && (
            <option value="unrestricted">Unrestricted equipment actions</option>
          )}
        </select>
      </label>
      <p>
        Only computed points are shown. Selection changes the displayed solution
        without running optimization.
      </p>
      {point?.relative_performance !== null &&
        point?.relative_performance !== undefined && (
          <p>
            Selected point: {(point.relative_performance * 100).toFixed(1)}% of
            the best-found reference.
          </p>
        )}
      <p>
        Best found without the swap-action limit:{" "}
        {raw.unrestricted
          ? `${raw.unrestricted.score.toFixed(2)} weighted DPS`
          : "Unavailable"}
        . Account, acquisition, inventory and model constraints still apply.
      </p>
      {raw.suggested_swap_limit != null &&
        curve.some(
          (p) => p.swap_limit === raw.suggested_swap_limit && p.solution,
        ) && (
          <div className="button-row">
            <span>
              Suggested: {raw.suggested_swap_limit} equipment actions for at
              least 95% of the best-found reference.
            </span>
            <button
              type="button"
              onClick={() =>
                ui({ solutionId: `curve-${raw.suggested_swap_limit}` })
              }
            >
              View suggested cap
            </button>
          </div>
        )}
    </div>
  );
  return (
    <div className="result-column">
      <ResultFreshness
        outdated={current.outdated}
        draftChanged={current.draftChanged}
        contextStale={current.contextStale}
      />
      {result.scenario.request.mode === "future" && (
        <p className="notice">
          Hypothetical submitted result · assumptions retained with this result.
        </p>
      )}
      {solution ? (
        <>
          <section className={`panel ${current.outdated ? "is-stale" : ""}`}>
            <h2>
              {isDefault
                ? "Best joint configuration found"
                : "Selected joint setup"}
            </h2>
            <h3>Joint performance</h3>
            <strong
              className="verdict-dps gold numeric"
              aria-label="Weighted aggregate DPS"
            >
              {solution.score.toFixed(2)}
            </strong>
            <p className="result-cost">
              {purchaseSummary(
                solution.purchases.reduce(
                  (count, row) => count + (row.quantity ?? 1),
                  0,
                ),
                solution.purchase_cost_gp,
              )}
            </p>
            <p>
              Active-time weighted ordinary-attack DPS. Unscored utility roles
              have no damage contribution.
            </p>
            <p>
              Maximum equipment actions across required transitions:{" "}
              {solution.maximum_actions}.
            </p>
            {curvePanel}
            {solution.transitions.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  const section = document.getElementById(
                    "selected-switch-sequence",
                  );
                  section?.focus({ preventScroll: true });
                  section?.scrollIntoView?.();
                }}
              >
                Jump to switch sequence
              </button>
            )}
          </section>
          {request.wilderness && solution.wilderness_risk && (
            <section className="panel" aria-label="Wilderness risk">
              <h2>Wilderness risk</h2>
              <WildernessRiskDetails
                risk={solution.wilderness_risk}
                policy={request.wilderness}
                itemName={itemName}
              />
            </section>
          )}
          <div className="comparison-grid" id="selected-outfit" tabIndex={-1}>
            {roleIds.map(equipmentCard)}
          </div>
          <AcquisitionChecklist
            solution={solution}
            roles={roles}
            selectionKey={`${archiveRunId(result) ?? result.fingerprint}:${current.solutionId}`}
            itemById={itemById}
          />
        </>
      ) : (
        <>
          <section className="panel">
            <h2>No feasible solution found within this search</h2>
            <NoSolutionHints hints={raw.search.no_solution_hints} />
            {isUnsynced && (
              <p className="notice">
                No account data has been synced, so nothing can be confirmed as
                owned or wearable. Sync with RuneLite, then refresh your
                account.
              </p>
            )}
            <p>
              No legal combat configuration may satisfy the selected filters and
              equipment constraints. Select another computed point or revise
              constraints and rerun. Bounded search does not prove mathematical
              infeasibility.
            </p>
            {request.wilderness && (
              <p>
                Gear with an unknown loss is excluded from Wilderness
                recommendations.
              </p>
            )}
            {curvePanel}
          </section>
        </>
      )}
      <RunningCostFrontier
        group={runningCostGroup}
        selectedId={current.solutionId}
        selected={solution}
        itemName={itemName}
        roleName={roleName}
        onSelect={(solutionId) => ui({ solutionId })}
      />
      {result.scenario.request.objectives !== undefined && (
        <ObjectiveFrontier
          result={result}
          swapLimit={selectedSwapLimit}
          selectedId={current.solutionId}
          selectedSolution={solution}
          labOriginId={labOriginId}
          selectionRevision={current.selectionRevision}
          onSelect={(id, raw, runId, groupId, selectionRevision) =>
            selectObjective(
              "multi",
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
        group={frontierGroup}
        selectedId={current.solutionId}
        priority={result.scenario.request.secondary_priority ?? "default"}
        legacyCapped={(result.scenario.request.max_dps_loss_pct ?? 10) < 100}
        onSelect={(solutionId) => ui({ solutionId })}
      />
      {solution && (
        <>
          <section className="panel">
            <h2>Shared physical equipment</h2>
            <p className="green">
              Reused across the joint configuration:{" "}
              {shared.map(itemName).join(" · ") || "None"}.
            </p>
          </section>
          <div id="selected-switch-sequence" tabIndex={-1}>
            <JointTransition
              solution={solution}
              selected={current.selectedTransition}
              onSelect={(selectedTransition) => ui({ selectedTransition })}
              roleName={roleName}
              itemName={itemName}
            />
          </div>
          <JointInventory
            solution={solution}
            roles={roles}
            itemName={itemName}
          />
        </>
      )}
      <section className="panel result-context">
        <span className="eyebrow gold">This result used</span>
        <p>
          {roles.length} configurations · {budgetSummary(request)} ·{" "}
          {EQUIPMENT_ACCESS_LABELS[request.mode]}
        </p>
        <details>
          <summary>Result provenance and submitted scenario</summary>
          <p>Account: {result.snapshotId}</p>
          <p>Catalog: {result.catalogVersion}</p>
          <p>Model: {result.modelVersion}</p>
          <p>Prices: {result.priceRevision}</p>
          <p>Evaluated: {result.evaluatedAt}</p>
          <p>Scenario: {result.fingerprint}</p>
          <p>Assumptions: {raw.assumptions_fingerprint}</p>
          <pre className="fact-json">
            {JSON.stringify(result.live.scenario, null, 2)}
          </pre>
        </details>
      </section>
      {current.previous && (
        <section className="panel">
          <h2>Previous joint result</h2>
          <p>
            Previous accepted scenario: {current.previous.fingerprint} · account{" "}
            {current.previous.snapshotId} · catalog{" "}
            {current.previous.catalogVersion} · model{" "}
            {current.previous.modelVersion} · prices{" "}
            {current.previous.priceRevision}.
          </p>
          <details>
            <summary>Previous submitted scenario</summary>
            <pre className="fact-json">
              {JSON.stringify(
                current.previous.live?.scenario ?? current.previous.scenario,
                null,
                2,
              )}
            </pre>
          </details>
          <p>
            Each result retains its own submitted context; no cross-context
            improvement is assumed.
          </p>
        </section>
      )}
      <section className="panel">
        <details>
          <summary>Search diagnostics and model limitations</summary>
          <pre className="fact-json">{JSON.stringify(raw.search, null, 2)}</pre>
          {raw.limitations.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
        </details>
        <p>
          Best found within bounded candidates and beams; global optimality is
          not proven.
        </p>
      </section>
      <SupportPolicySummary result={result} />
      <SecondaryPrioritySummary
        client={client}
        outdated={current.outdated || current.pending}
        result={result}
        solution={solution}
        potionCatalog={state.context?.live?.potion_catalog}
      />
      <OptimizationModeSummary
        result={result}
        solution={solution}
        actionLimit={selectedSwapLimit ?? undefined}
        unrestricted={selectedSwapLimit === null}
      />
    </div>
  );
}
