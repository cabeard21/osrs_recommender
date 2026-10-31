import { EquipmentBonuses } from "./EquipmentBonuses";
import { SecondaryFrontier } from "./SecondaryFrontier";
import { SupportPolicySummary } from "./SupportPolicySummary";
import { Shield } from "lucide-react";
import { emptyEquipment, slots } from "../api/contracts";
import type { Equipment, JointSolutionDTO, Slot } from "../api/contracts";
import { performanceMetrics } from "../api/httpClient";
import { useGear } from "../state/GearProvider";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import { SecondaryPrioritySummary } from "./SecondaryPrioritySummary";
import { OptimizationModeSummary } from "./OptimizationModeSummary";
import { CombatOptionSummary } from "./CombatOptionSummary";
import {
  JointInventory,
  JointPurchases,
  JointTransition,
} from "./JointSolutionDetails";

function equipmentFor(equipment: Record<string, number>): Equipment {
  return {
    ...emptyEquipment(),
    ...Object.fromEntries(
      Object.entries(equipment).map(([slot, id]) => [
        slot === "ammunition" ? "ammo" : slot,
        id,
      ]),
    ),
  };
}
function sharedIds(solution: JointSolutionDTO, roles: string[]): number[] {
  const counts = new Map<number, number>();
  for (const role of roles) {
    for (const id of new Set(Object.values(solution.loadouts[role].equipment)))
      counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return [...counts].filter(([, count]) => count > 1).map(([id]) => id);
}

export function LiveMultiResultWorkspace() {
  const { current, dispatch, itemById } = useGear();
  const result = current.result;
  if (!result?.live)
    return (
      <section className="panel">
        <h2>Configure a joint optimization</h2>
        <p>
          Add two to four configurations, then run one Python joint
          optimization. All views will use that joint result.
        </p>
      </section>
    );
  const raw = result.live.result;
  const roles = result.scenario.request.roles;
  const roleIds = roles.map((role) => role.id);
  const roleName = (id: string) =>
    roles.find((role) => role.id === id)?.name ?? id;
  const itemName = (id: number) => itemById(id)?.name ?? `Item #${id}`;
  const curve = raw.curve ?? [];
  const point = curve.find(
    (p) => `curve-${p.swap_limit}` === current.solutionId,
  );
  const solution = point
    ? point.solution
    : result.solutions.find((s) => s.id === current.solutionId)?.live;
  const frontierGroup =
    raw.secondary_frontiers?.find((g) =>
      g.points.some((p) => p.id === current.solutionId),
    ) ??
    raw.secondary_frontiers?.find(
      (g) =>
        g.swap_limit ===
        (current.solutionId === "unrestricted"
          ? null
          : (point?.swap_limit ?? result.scenario.request.max_swaps)),
    );
  const first = roleIds.includes(current.comparisonRoles[0])
    ? current.comparisonRoles[0]
    : roleIds[0];
  const second =
    roleIds.includes(current.comparisonRoles[1]) &&
    current.comparisonRoles[1] !== first
      ? current.comparisonRoles[1]
      : roleIds.find((id) => id !== first)!;
  const pair: [string, string] = [first, second];
  const active = roleIds.includes(current.activeRole)
    ? current.activeRole
    : first;
  const ui = (
    patch: Partial<
      Pick<
        typeof current,
        | "solutionId"
        | "view"
        | "comparisonRoles"
        | "activeRole"
        | "selectedTransition"
        | "slot"
      >
    >,
  ) => dispatch({ type: "ui", mode: "multi", patch });
  const counterpart = pair[0] === active ? pair[1] : pair[0];
  const displayedPair =
    current.view === "interactive" ? [active, counterpart] : pair;
  const shared = solution ? sharedIds(solution, displayedPair) : [];
  function equipmentCard(id: string) {
    if (!solution?.loadouts[id]) return null;
    const loadout = solution.loadouts[id];
    const role = roles.find((entry) => entry.id === id)!;
    const equipment = equipmentFor(loadout.equipment);
    const comparedRole = pair[0] === id ? pair[1] : pair[0];
    const other = equipmentFor(solution.loadouts[comparedRole].equipment);
    const differences = slots.filter((slot) => equipment[slot] !== other[slot]);
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
          <CombatOptionSummary
            option={loadout.combat_option}
            role={role}
            weapon={equipment.weapon ? itemName(equipment.weapon) : "Unarmed"}
          />
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
          Equipment differences from {roleName(comparedRole)}:{" "}
          {differences.join(", ") || "None"}.
        </p>
        <EquipmentBonuses
          bonuses={performance.bonuses}
          title={`${role.name} equipment bonuses`}
        />
        <details>
          <summary>Role assumptions</summary>
          <pre className="fact-json">
            {JSON.stringify({ performance, role }, null, 2)}
          </pre>
        </details>
      </section>
    );
  }
  return (
    <div className="result-column">
      <SupportPolicySummary result={result} />
      <SecondaryFrontier
        group={frontierGroup}
        selectedId={current.solutionId}
        priority={result.scenario.request.secondary_priority ?? "default"}
        onSelect={(solutionId) => ui({ solutionId })}
      />
      <SecondaryPrioritySummary result={result} solution={solution} />
      <OptimizationModeSummary
        result={result}
        solution={solution}
        actionLimit={
          point?.swap_limit ?? frontierGroup?.swap_limit ?? undefined
        }
        unrestricted={
          current.solutionId === "unrestricted" ||
          frontierGroup?.swap_limit === null
        }
      />
      <section className="panel result-context">
        <span className="eyebrow gold">
          Submitted joint scenario // Python optimizer
        </span>
        <h2>Best joint configuration found</h2>
        <p>
          {roles.length} configurations ·{" "}
          {result.scenario.request.budget_gp.toLocaleString()} GP additional
          budget · {result.scenario.request.mode}
        </p>
        {current.outdated && (
          <p role="status" className="notice">
            Result outdated — draft inputs, account, prices, catalog or model
            changed. The original submitted result remains displayed.
          </p>
        )}
        {result.scenario.request.mode === "future" && (
          <p className="notice">
            Hypothetical submitted result · assumptions retained with this
            result.
          </p>
        )}
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
      <section className="panel">
        <div className="segmented">
          <button
            aria-pressed={current.view === "side"}
            onClick={() => ui({ view: "side" })}
          >
            Side-by-side
          </button>
          <button
            aria-pressed={current.view === "interactive"}
            onClick={() => ui({ view: "interactive" })}
          >
            Interactive switching
          </button>
        </div>
        <label>
          Swap-efficiency curve point
          <select
            value={
              point
                ? `curve-${point.swap_limit}`
                : frontierGroup?.swap_limit != null
                  ? `curve-${frontierGroup.swap_limit}`
                  : current.solutionId
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
          </select>
        </label>
        <p>
          Only computed backend points are shown. Selection changes the
          displayed solution without running optimization.
        </p>
        {point?.relative_performance !== null &&
          point?.relative_performance !== undefined && (
            <p>
              Selected point: {(point.relative_performance * 100).toFixed(1)}%
              of the best-found reference.
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
            <p>
              Backend suggestion: {raw.suggested_swap_limit} equipment actions
              for at least 95% of the best-found reference. This does not change
              the selected point.
            </p>
          )}
      </section>
      {solution ? (
        <>
          <section className="panel">
            <h2>Joint performance</h2>
            <strong
              className="gold numeric"
              aria-label="Weighted aggregate DPS"
            >
              {solution.score.toFixed(2)}
            </strong>
            <p>
              Active-time weighted ordinary-attack DPS. Unscored utility roles
              have no damage contribution.
            </p>
            <p>
              Maximum equipment actions across required transitions:{" "}
              {solution.maximum_actions}.
            </p>
          </section>
          {current.view === "side" ? (
            <>
              {roles.length > 2 && (
                <section className="panel">
                  <h2>Compare two configurations</h2>
                  <label>
                    Compare first configuration
                    <select
                      value={pair[0]}
                      onChange={(e) =>
                        ui({
                          comparisonRoles: [
                            e.target.value,
                            e.target.value === pair[1] ? pair[0] : pair[1],
                          ],
                        })
                      }
                    >
                      {roles.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Compare second configuration
                    <select
                      value={pair[1]}
                      onChange={(e) =>
                        ui({
                          comparisonRoles: [
                            e.target.value === pair[0] ? pair[1] : pair[0],
                            e.target.value,
                          ],
                        })
                      }
                    >
                      {roles.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </section>
              )}
              <div className="comparison-grid">{pair.map(equipmentCard)}</div>
            </>
          ) : (
            <>
              <section className="panel">
                <label>
                  Active combat configuration
                  <select
                    value={active}
                    onChange={(e) =>
                      ui({ activeRole: e.target.value, slot: null })
                    }
                  >
                    {roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                </label>
              </section>
              {equipmentCard(active)}
            </>
          )}
          <section className="panel">
            <h2>Shared physical equipment</h2>
            <p className="green">
              Shared by {roleName(displayedPair[0])} and{" "}
              {roleName(displayedPair[1])}:{" "}
              {shared.map(itemName).join(" · ") || "None"}.
            </p>
            <p>
              Reused across the joint configuration:{" "}
              {sharedIds(solution, roleIds).map(itemName).join(" · ") || "None"}
              .
            </p>
          </section>
          <JointTransition
            solution={solution}
            selected={current.selectedTransition}
            onSelect={(selectedTransition) => ui({ selectedTransition })}
            roleName={roleName}
            itemName={itemName}
          />
          <JointInventory
            solution={solution}
            activeRole={active}
            roleName={roleName(active)}
            itemName={itemName}
          />
          <JointPurchases
            solution={solution}
            identity={`${result.fingerprint}:${current.solutionId}:${result.priceRevision}`}
            itemName={itemName}
          />
        </>
      ) : (
        <section className="panel">
          <h2>No feasible solution found within this search</h2>
          <p>
            No legal combat configuration may satisfy the selected filters and
            equipment constraints. Select another computed point or revise
            constraints and rerun. Bounded search does not prove mathematical
            infeasibility.
          </p>
        </section>
      )}
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
    </div>
  );
}
