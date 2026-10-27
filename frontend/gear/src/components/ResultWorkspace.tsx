import { useState } from "react";
import { ArrowRightLeft, Shield } from "lucide-react";
import { useGear } from "../state/GearProvider";
import { EquipmentGrid } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
import type { Loadout, Solution } from "../api/contracts";
import { LiveResultWorkspace } from "./LiveResultWorkspace";
export function ResultWorkspace() {
  const { state, current, dispatch, itemById, liveMode } = useGear();
  const [transitionKey, setTransitionKey] = useState("");
  const solution = current.result?.solutions.find(
    (s) => s.id === current.solutionId,
  );
  function equipmentCard(loadout: Loadout, solution?: Solution) {
    return (
      <section className="panel equipment-panel" key={loadout.roleId}>
        <div className="section-title">
          <h2>
            <Shield size={19} />
            {loadout.name}
          </h2>
          <span className="badge">
            {solution ? "Fixture result" : "Fixture baseline"}
          </span>
        </div>
        <p>
          {solution
            ? "Best-found presentation example · select any slot to inspect"
            : "Demo equipment · no account connection"}
        </p>
        <EquipmentGrid
          prefix={state.mode === "multi" ? `${loadout.name} ` : ""}
          equipment={loadout.equipment}
          shared={solution?.shared}
          selected={current.activeRole === loadout.roleId ? current.slot : null}
          onSelect={(slot) =>
            dispatch({
              type: "ui",
              mode: state.mode,
              patch: { slot, activeRole: loadout.roleId },
            })
          }
        />
        <PerformanceSummary metrics={loadout.metrics} />
      </section>
    );
  }
  if (liveMode) return <LiveResultWorkspace />;
  if (
    !current.result &&
    state.context &&
    state.context.equipmentStatus !== "observed"
  )
    return (
      <section className="panel">
        <h2>
          {state.context?.equipmentStatus === "partial"
            ? "Partial equipment observation"
            : "Current equipment unknown"}
        </h2>
        <p>
          No complete fixture equipment scan. Baseline metrics are unavailable;
          missing observations do not mean empty equipment.
        </p>
      </section>
    );
  if (!current.result)
    return (
      <div className="result-column">
        {state.context &&
          equipmentCard({
            roleId: "role-1",
            name: "Current demo loadout",
            equipment: state.context.equipment,
            metrics: { dps: 5.66, maxHit: 36, accuracy: 0.558, ticks: 4 },
          })}
      </div>
    );
  if (!solution)
    return (
      <section className="panel">
        <h2>No feasible solution found within this search</h2>
        <p>
          This is the selected no-solution fixture. Change the demo outcome to
          success and run again. Your draft is preserved.
        </p>
      </section>
    );
  const transition =
    solution.transitions.find((t) => `${t.from}:${t.to}` === transitionKey) ??
    solution.transitions[0];
  const active =
    solution.loadouts.find((l) => l.roleId === current.activeRole) ??
    solution.loadouts[0];
  return (
    <div className="result-column">
      {state.mode === "single" && (
        <button
          onClick={() => {
            dispatch({ type: "use-single-in-multi" });
            location.hash = "multi";
          }}
        >
          Use as locked role in Multi
        </button>
      )}
      <div className="panel result-context">
        <span className="eyebrow gold">
          Submitted scenario // fixture result
        </span>
        <strong>{current.result.scenario.request.target.name}</strong>
        <p>
          {current.result.scenario.request.target.defence} defence ·{" "}
          {current.result.scenario.request.budget_gp.toLocaleString()} GP ·{" "}
          {current.result.scenario.request.mode}
        </p>
        {current.outdated && (
          <p role="status" className="notice">
            Result outdated — draft inputs changed. Re-run to use the draft.
          </p>
        )}
        {current.result.scenario.request.mode === "future" && (
          <p className="notice">
            Hypothetical submitted result · assumptions retained with this
            result
          </p>
        )}
      </div>
      {state.mode === "multi" && (
        <>
          <div className="panel">
            <div className="segmented">
              <button
                aria-pressed={current.view === "side"}
                onClick={() =>
                  dispatch({
                    type: "ui",
                    mode: "multi",
                    patch: { view: "side" },
                  })
                }
              >
                Side-by-side
              </button>
              <button
                aria-pressed={current.view === "interactive"}
                onClick={() =>
                  dispatch({
                    type: "ui",
                    mode: "multi",
                    patch: { view: "interactive" },
                  })
                }
              >
                Interactive switching
              </button>
            </div>
            <label>
              Swap-efficiency fixture
              <select
                value={current.solutionId}
                onChange={(e) =>
                  dispatch({
                    type: "ui",
                    mode: "multi",
                    patch: { solutionId: e.target.value },
                  })
                }
              >
                {current.result.solutions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id} · {s.actionLimit} action example ·{" "}
                    {s.weightedDps.toFixed(2)} weighted DPS
                  </option>
                ))}
              </select>
            </label>
            <p>
              Authored curve points; constraints are not calculated in this
              preview.
            </p>
          </div>
          {current.view === "interactive" && (
            <div className="panel">
              <span className="eyebrow">Active combat configuration</span>
              <div className="segmented">
                {solution.loadouts.map((l) => (
                  <button
                    key={l.roleId}
                    aria-pressed={active.roleId === l.roleId}
                    onClick={() =>
                      dispatch({
                        type: "ui",
                        mode: "multi",
                        patch: { activeRole: l.roleId, slot: null },
                      })
                    }
                  >
                    {l.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      <div
        className={
          state.mode === "multi" && current.view === "side"
            ? "comparison-grid"
            : ""
        }
      >
        {(state.mode === "multi" && current.view === "interactive"
          ? [active]
          : solution.loadouts
        ).map((l) => equipmentCard(l, solution))}
      </div>
      {state.mode === "multi" && (
        <section className="panel">
          <h2>
            <ArrowRightLeft size={19} /> Shared equipment & directed transitions
          </h2>
          <p className="green">
            {solution.shared.length} shared concrete items
          </p>
          <p>
            {solution.shared.map((id) => itemById(id)?.name).join(" · ") ||
              "No shared items"}
          </p>
          <label>
            Directed transition
            <select
              value={transition ? `${transition.from}:${transition.to}` : ""}
              onChange={(e) => setTransitionKey(e.target.value)}
            >
              {solution.transitions.map((t) => (
                <option key={`${t.from}:${t.to}`} value={`${t.from}:${t.to}`}>
                  {solution.loadouts.find((l) => l.roleId === t.from)?.name} →{" "}
                  {solution.loadouts.find((l) => l.roleId === t.to)?.name}
                </option>
              ))}
            </select>
          </label>
          {transition && (
            <>
              <ol>
                {transition.actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ol>
              <p>
                {transition.actions.length} equipment actions ·{" "}
                {transition.changedSlots} changed slots · {transition.peak} peak
                gear slots (fixture)
              </p>
              <p>
                {current.result.scenario.request.reserved_supply_slots} reserved
                supply slots in submitted scenario. No supply inventory
                inferred.
              </p>
            </>
          )}
        </section>
      )}
      {current.previous && (
        <section className="panel">
          <h2>Previous configuration comparison</h2>
          <p>
            Previous target: {current.previous.scenario.request.target.name} ·
            defence {current.previous.scenario.request.target.defence} · budget{" "}
            {current.previous.scenario.request.budget_gp} GP ·{" "}
            {current.previous.modelVersion}
          </p>
          <p>
            Current target: {current.result.scenario.request.target.name} ·
            defence {current.result.scenario.request.target.defence} · budget{" "}
            {current.result.scenario.request.budget_gp} GP ·{" "}
            {current.result.modelVersion}
          </p>
          <p>
            Authored weighted DPS:{" "}
            {current.previous.solutions[0]?.weightedDps.toFixed(2) ??
              "Unavailable"}{" "}
            → {solution.weightedDps.toFixed(2)}. Contexts may differ; no
            improvement claim.
          </p>
          {solution.loadouts.map((l) => {
            const before = current.previous?.solutions[0]?.loadouts.find(
              (b) => b.roleId === l.roleId,
            );
            return (
              <p key={l.roleId}>
                {l.name}:{" "}
                {before
                  ? Object.entries(l.equipment)
                      .filter(
                        ([slot, id]) =>
                          before.equipment[
                            slot as keyof typeof before.equipment
                          ] !== id,
                      )
                      .map(([slot]) => slot)
                      .join(", ") || "No equipment changes"
                  : "New configuration"}
              </p>
            );
          })}
        </section>
      )}
    </div>
  );
}
