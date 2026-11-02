import { DisciplineTabs } from "./DisciplineTabs";
import { EquipmentBonuses } from "./EquipmentBonuses";
import { RunningCostFrontier } from "./RunningCostFrontier";
import { SecondaryFrontier } from "./SecondaryFrontier";
import { SupportPolicySummary } from "./SupportPolicySummary";
import { Shield } from "lucide-react";
import { emptyEquipment } from "../api/contracts";
import type { OptimizationReply } from "../api/contracts";
import { useGear } from "../state/GearProvider";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { PurchaseListCopy } from "./PurchaseListCopy";
import { PurchaseRows, purchaseSummary } from "./PurchaseRows";
import { SecondaryPrioritySummary } from "./SecondaryPrioritySummary";
import { OptimizationModeSummary } from "./OptimizationModeSummary";
import { CombatOptionSummary } from "./CombatOptionSummary";
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

        {result.live?.result.discipline_comparison && (
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
          : result.scenario.request.roles.some(
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
            )?.find((g) => g.swap_limit === result.scenario.request.max_swaps)}
            selectedId={current.solutionId}
            selected={selected}
            itemName={(id) => itemById(id)?.name ?? `Item #${id}`}
            onSelect={(solutionId) =>
              dispatch({ type: "ui", mode: state.mode, patch: { solutionId } })
            }
          />
        )}
        <SecondaryFrontier
          group={(
            branch?.secondary_frontiers ??
            result.live?.result.secondary_frontiers
          )?.find((g) => g.swap_limit === result.scenario.request.max_swaps)}
          selectedId={current.solutionId}
          priority={result.scenario.request.secondary_priority ?? "default"}
          onSelect={(solutionId) =>
            dispatch({ type: "ui", mode: state.mode, patch: { solutionId } })
          }
        />
        <section className="panel result-context">
          <span className="eyebrow gold">Submitted scenario</span>
          <strong>{result.scenario.request.target.name}</strong>
          <p>
            {result.scenario.request.target.defence} defence ·{" "}
            {result.scenario.request.budget_gp.toLocaleString()} GP additional
            budget · {result.scenario.request.mode}
          </p>
          <p>
            {result.scenario.request.roles[0].autoDiscipline
              ? `Auto selected ${Object.values(result.live?.result.selected_solution?.loadouts ?? {})[0]?.discipline ?? "no discipline"}`
              : `${result.scenario.request.roles[0].style} combat`}{" "}
            ·{" "}
            {result.scenario.request.roles[0].combatOptions
              ? "option selection enabled"
              : "fixed option"}
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
            {loadout.metrics && (
              <PerformanceSummary
                metrics={loadout.metrics}
                live
                title="Calculated combat performance"
              />
            )}
            {solution && (
              <p className="result-cost">
                {purchaseSummary(solution.purchases.length, solution.cost)}
              </p>
            )}
            <p>Bounded search · select any slot to inspect its item.</p>
            <EquipmentGrid
              equipment={loadout.equipment}
              selected={current.slot}
              onSelect={select}
              optimized
              purchaseIds={solution?.purchases}
              roleId={loadout.roleId}
            />
            <CombatOptionSummary
              option={loadout.combatOption}
              role={result.scenario.request.roles[0]}
              weapon={
                itemById(loadout.equipment.weapon ?? -1)?.name ?? "Unarmed"
              }
            />
            <EquipmentBonuses
              bonuses={selected?.loadouts[loadout.roleId]?.performance.bonuses}
            />
          </section>
        ) : (
          <section className="panel">
            <h2>No feasible solution found within this search</h2>
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
            <h2>Acquisition requirements</h2>
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
              itemName={(id) => itemById(id)?.name ?? `Item #${id}`}
            />
            <PurchaseListCopy
              key={`${result.fingerprint}:${result.priceRevision}:${current.solutionId}`}
              purchases={selected?.purchases ?? []}
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
                {result.scenario.request.assumed_item_ids.join(", ")}.
                Acquisition is assumed; no account ownership changes.
              </p>
            )}
            <p>
              Inspect each item for ownership observations, missing prices and
              selected price provenance.
            </p>
          </section>
        )}
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
            {comparable(previous, result) &&
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
