import { useEffect, useState } from "react";
import { emptyEquipment, type Item } from "../api/contracts";
import { useGear } from "../state/GearProvider";
import { Dialog } from "./Dialog";
import { ItemSprite } from "./EquipmentGrid";
import { PerformanceSummary } from "./PerformanceSummary";
export function ItemInspector() {
  const { state, current, dispatch, edit, client, itemById } = useGear(),
    slot = current.slot!;
  const solution = current.result?.solutions.find(
    (s) => s.id === current.solutionId,
  );
  const equipment =
    solution?.loadouts.find((l) => l.roleId === current.activeRole)
      ?.equipment ??
    state.context?.equipment ??
    emptyEquipment();
  const id = equipment[slot];
  const [details, setDetails] = useState<Item | null>(null);
  const item = details?.id === id ? details : itemById(id);
  const [alternatives, setAlternatives] = useState<Item[]>([]),
    [error, setError] = useState<string | null>(null),
    [pending, setPending] = useState(false);
  useEffect(() => {
    let active = true;
    setDetails(null);
    setError(null);
    if (id !== null)
      client
        .getItem(id)
        .then((item) => {
          if (active) setDetails(item);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [id, client]);
  useEffect(() => {
    let active = true;
    setAlternatives([]);
    if (current.result)
      client
        .alternatives(slot, current.result.scenario)
        .then((items) => {
          if (active) setAlternatives(items);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [slot, client, current.result]);
  const close = () =>
    dispatch({ type: "ui", mode: state.mode, patch: { slot: null } });
  function lock(exclude = false) {
    const roles = current.draft.roles.map((r) => {
      if (r.id !== current.activeRole) return r;
      const locks = { ...r.locks };
      if (exclude) delete locks[slot];
      else locks[slot] = id;
      return { ...r, locks };
    });
    edit({
      ...current.draft,
      roles,
      exclusions:
        exclude && id
          ? [...new Set([...current.draft.exclusions, id])]
          : current.draft.exclusions.filter((i) => i !== id),
    });
  }
  const locked = current.draft.roles.some((r) =>
    Object.values(r.locks).includes(id),
  );
  async function preview(replacement: number | null) {
    if (!current.result || !solution) return;
    setPending(true);
    setError(null);
    try {
      const trial = await client.evaluate(
        current.result,
        solution.id,
        current.activeRole,
        { ...equipment, [slot]: replacement },
      );
      dispatch({ type: "trial", mode: state.mode, trial });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <Dialog contextual title="Item inspector" onClose={close}>
      <span className="eyebrow blue">{slot} // contextual inspection</span>
      <div className="inspector-item">
        <ItemSprite id={id} />
        <h3>{item?.name ?? "Empty slot"}</h3>
      </div>
      <p className="notice">
        Fixture item facts · no live ownership or price verification.
      </p>
      <dl>
        <dt>Concrete ID</dt>
        <dd>{id ?? "None"}</dd>
        <dt>Ownership example</dt>
        <dd>
          {item
            ? item.owned
              ? "Observed owned (fixture)"
              : "Unowned (fixture)"
            : "Empty"}
        </dd>
        <dt>Quote example</dt>
        <dd>
          {item?.price == null
            ? "Unavailable / untradeable"
            : `${item.price.toLocaleString()} GP`}
        </dd>
        <dt>Last observed</dt>
        <dd>{state.context?.observedAt}</dd>
      </dl>
      <p>{item?.requirement ?? "Empty slots can be locked explicitly."}</p>
      <div className="button-row">
        <button onClick={() => lock()}>
          Lock {id === null ? "empty slot" : "item"} in draft
        </button>
        <button
          disabled={
            id === null ||
            (locked &&
              current.draft.roles.some(
                (r) =>
                  r.id !== current.activeRole &&
                  Object.values(r.locks).includes(id),
              ))
          }
          onClick={() => lock(true)}
        >
          {locked ? "Unlock and exclude" : "Exclude item"} in draft
        </button>
      </div>
      <p>
        Draft controls only. Production exclusions and exact manual evaluations
        are unavailable.
      </p>
      <h3>Equipment alternatives</h3>
      {!current.result && (
        <p>Run a fixture optimization to preview alternatives.</p>
      )}
      {alternatives
        .filter((a) => a.id !== id)
        .map((a) => (
          <article className="alternative" key={a.id}>
            <ItemSprite id={a.id} />
            <span>
              {a.name}
              <small>{a.owned ? "Fixture owned" : "Fixture purchase"}</small>
            </span>
            <button
              disabled={current.outdated || current.pending || pending}
              onClick={() => void preview(a.id)}
            >
              Preview comparison
            </button>
          </article>
        ))}
      {current.result && (
        <button
          disabled={current.outdated || current.pending || pending}
          onClick={() => void preview(null)}
        >
          Preview empty slot
        </button>
      )}
      {current.outdated && (
        <p className="notice">
          Result outdated. Re-run before previewing alternatives.
        </p>
      )}
      {pending && <p role="status">Loading fixture comparison…</p>}
      {error && <p role="alert">{error}</p>}
      {current.trial && (
        <section className="trial">
          <h3>Manual trial · fixture preview</h3>
          <p>Original result and draft equipment remain unchanged.</p>
          <p>
            Baseline {current.trial.baseline.dps.toFixed(2)} DPS → trial{" "}
            {current.trial.proposed.dps.toFixed(2)} DPS. Authored illustration
            only.
          </p>
          <PerformanceSummary
            metrics={current.trial.proposed}
            title="Trial telemetry"
          />
          <button
            onClick={() =>
              dispatch({ type: "trial", mode: state.mode, trial: null })
            }
          >
            Revert trial
          </button>
        </section>
      )}
    </Dialog>
  );
}
