import type { Draft } from "../api/contracts";
import {
  maxEquipmentActions,
  reservedSupplySlots,
  validationMessage,
} from "../state/setupValidation";
import { FieldError, fieldProps } from "./FieldError";

export function MultiTransitions({
  draft,
  change,
}: {
  draft: Draft;
  change: (patch: Partial<Draft>) => void;
}) {
  const phases = draft.orderedRoles ?? draft.roles.map((role) => role.id);
  const edges = draft.transitions ?? [];
  const actionError = validationMessage(() =>
    maxEquipmentActions(draft.maxActions),
  );
  const supplyError = validationMessage(() =>
    reservedSupplySlots(draft.supplies),
  );
  return (
    <details>
      <summary>
        <span>Transitions &amp; inventory</span>
        <small>
          {" "}
          · {draft.maxActions || "—"} actions · {draft.supplies || "—"} reserved
          supply slots
        </small>
      </summary>
      <label>
        Base configuration
        <select
          value={draft.baseRole}
          onChange={(event) => change({ baseRole: event.target.value })}
        >
          {draft.roles.map((role) => (
            <option value={role.id} key={role.id}>
              {role.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Transition topology
        <select
          value={draft.topology}
          onChange={(event) =>
            change({
              topology: event.target.value as Draft["topology"],
              ...(event.target.value === "ordered"
                ? { orderedRoles: phases }
                : {}),
            })
          }
        >
          <option value="base">Base ↔ ordinary configurations</option>
          <option value="explicit">Explicit directed transitions</option>
          <option value="ordered">Ordered phases →</option>
        </select>
      </label>
      {draft.topology === "base" && (
        <p>
          Requires each ordinary configuration to switch to and from the base.
          Utility roles retain their parent transitions.
        </p>
      )}
      {draft.topology === "explicit" && (
        <fieldset>
          <legend>Required directed transitions</legend>
          {draft.roles.flatMap((from) =>
            draft.roles
              .filter((to) => from.id !== to.id)
              .map((to) => {
                const checked = edges.some(
                  ([a, b]) => a === from.id && b === to.id,
                );
                return (
                  <label className="check" key={`${from.id}:${to.id}`}>
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && edges.length >= 16}
                      onChange={(event) =>
                        change({
                          transitions: event.target.checked
                            ? [...edges, [from.id, to.id]]
                            : edges.filter(
                                ([a, b]) => a !== from.id || b !== to.id,
                              ),
                        })
                      }
                    />
                    {from.name} → {to.name}
                  </label>
                );
              }),
          )}
          <p>
            Choose at least one directed edge. The reverse direction is a
            separate constraint. Utility parent transitions follow the existing
            backend rules.
          </p>
        </fieldset>
      )}
      {draft.topology === "ordered" && (
        <div>
          <p>
            Repeated configurations are allowed. Consecutive phases define
            directed transitions.
          </p>
          {phases.map((id, index) => (
            <div className="constraint" key={index}>
              <label>
                Phase {index + 1}
                <select
                  value={id}
                  onChange={(event) =>
                    change({
                      orderedRoles: phases.map((phase, i) =>
                        i === index ? event.target.value : phase,
                      ),
                    })
                  }
                >
                  {draft.roles.map((role) => (
                    <option value={role.id} key={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={phases.length <= 2}
                onClick={() =>
                  change({ orderedRoles: phases.filter((_, i) => i !== index) })
                }
              >
                Remove phase {index + 1}
              </button>
            </div>
          ))}
          <button
            disabled={phases.length >= 100}
            onClick={() =>
              change({ orderedRoles: [...phases, draft.baseRole] })
            }
          >
            Add phase
          </button>
          <label className="check">
            <input
              type="checkbox"
              checked={draft.loop ?? false}
              onChange={(event) => change({ loop: event.target.checked })}
            />
            Loop ordered phases
          </label>
        </div>
      )}
      <label>
        Maximum equipment actions
        <input
          type="number"
          min="0"
          max="12"
          data-run-on-enter
          value={draft.maxActions}
          {...fieldProps("multi-actions", actionError)}
          onChange={(event) => change({ maxActions: event.target.value })}
        />
      </label>
      <FieldError id="multi-actions" message={actionError} />
      <label>
        Reserved supply slots
        <input
          type="number"
          min="0"
          max="28"
          data-run-on-enter
          value={draft.supplies}
          {...fieldProps("multi-supplies", supplyError)}
          onChange={(event) => change({ supplies: event.target.value })}
        />
      </label>
      <FieldError id="multi-supplies" message={supplyError} />
      <p>
        Equipment actions count directed equips and unequips, rather than
        changed slots. Supplies reserve capacity; consumption is not simulated.
      </p>
    </details>
  );
}
