import { Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useGear } from "../state/GearProvider";
import { newRole } from "../state/scenario";
import type { Draft, Role, Style } from "../api/contracts";
export function ConfigurationPanel() {
  const { state, current, edit, liveMode } = useGear(),
    draft = current.draft;
  const change = (patch: Partial<Draft>) => edit({ ...draft, ...patch });
  const roleChange = (id: string, patch: Partial<Role>) =>
    change({
      roles: draft.roles.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    });
  return (
    <section className="panel configuration" aria-labelledby="parameters">
      <h2 id="parameters" className="eyebrow">
        <SlidersHorizontal size={17} /> Optimization parameters
      </h2>
      <div className="raised">
        <span className="eyebrow blue">Encounter target</span>
        <label>
          Custom target
          <input
            value={draft.target}
            onChange={(e) => change({ target: e.target.value })}
          />
        </label>
        <label>
          Target defence
          <input
            type="number"
            min="0"
            max="1000"
            value={draft.defence}
            onChange={(e) => change({ defence: e.target.value })}
          />
        </label>
        <p>
          Ordinary attacks only. User-supplied target assumptions; no encounter
          mechanics.
        </p>
      </div>
      <span className="eyebrow">Combat configurations</span>
      {draft.roles.map((role, index) => (
        <fieldset key={role.id}>
          <legend>
            {state.mode === "single"
              ? "Combat discipline"
              : `Configuration ${index + 1}`}
          </legend>
          {state.mode === "multi" && (
            <label>
              Name
              <input
                value={role.name}
                onChange={(e) => roleChange(role.id, { name: e.target.value })}
              />
            </label>
          )}
          <div className="segmented" aria-label={`${role.name} discipline`}>
            {(["melee", "ranged", "magic"] as Style[]).map((style) => (
              <button
                key={style}
                aria-pressed={role.style === style}
                onClick={() =>
                  roleChange(role.id, {
                    style,
                    stance: style === "ranged" ? "rapid" : "accurate",
                  })
                }
              >
                {style}
              </button>
            ))}
          </div>
          {role.style === "melee" && (
            <label>
              Melee attack type
              <select
                value={role.attackType}
                onChange={(e) =>
                  roleChange(role.id, {
                    attackType: e.target.value as Role["attackType"],
                  })
                }
              >
                {["stab", "slash", "crush"].map((type) => (
                  <option key={type}>{type}</option>
                ))}
              </select>
            </label>
          )}
          <label>
            Attack stance
            <select
              value={role.stance}
              onChange={(e) => roleChange(role.id, { stance: e.target.value })}
            >
              {(role.style === "melee"
                ? ["accurate", "aggressive", "controlled", "defensive"]
                : role.style === "ranged"
                  ? ["accurate", "rapid", "longrange"]
                  : ["accurate", "defensive"]
              ).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          {role.style === "magic" && (
            <label>
              Standard spell
              <select
                value={role.spell}
                onChange={(e) => roleChange(role.id, { spell: e.target.value })}
              >
                {[
                  "fire_strike",
                  "wind_wave",
                  "water_wave",
                  "earth_wave",
                  "fire_wave",
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          )}
          {state.mode === "multi" && (
            <>
              <label>
                Active-time weight
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={role.weight}
                  onChange={(e) =>
                    roleChange(role.id, { weight: e.target.value })
                  }
                />
              </label>
              <button
                disabled={draft.roles.length <= 2}
                onClick={() => {
                  const roles = draft.roles.filter((r) => r.id !== role.id);
                  change({
                    roles,
                    baseRole:
                      draft.baseRole === role.id ? roles[0].id : draft.baseRole,
                  });
                }}
              >
                <Trash2 size={14} /> Remove configuration
              </button>
            </>
          )}
        </fieldset>
      ))}
      {state.mode === "multi" && (
        <>
          <button
            disabled={draft.roles.length >= 4}
            onClick={() => {
              const next =
                Math.max(
                  ...draft.roles.map((r) => Number(r.id.split("-")[1])),
                ) + 1;
              change({ roles: [...draft.roles, newRole(next)] });
            }}
          >
            <Plus size={16} /> Add configuration
          </button>
          <p>
            Removing a configuration removes its generated directed transitions.
          </p>
          <label>
            Base configuration
            <select
              value={draft.baseRole}
              onChange={(e) => change({ baseRole: e.target.value })}
            >
              {draft.roles.map((r) => (
                <option value={r.id} key={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Transition topology
            <select
              value={draft.topology}
              onChange={(e) =>
                change({ topology: e.target.value as Draft["topology"] })
              }
            >
              <option value="base">Base ↔ every configuration</option>
              <option value="ordered">Ordered sequence →</option>
            </select>
          </label>
          <label>
            Maximum equipment actions
            <input
              type="number"
              min="0"
              max="12"
              value={draft.maxActions}
              onChange={(e) => change({ maxActions: e.target.value })}
            />
          </label>
          <label>
            Reserved supply slots
            <input
              type="number"
              min="0"
              max="28"
              value={draft.supplies}
              onChange={(e) => change({ supplies: e.target.value })}
            />
          </label>
        </>
      )}
      <span className="eyebrow">Optimization objective</span>
      <div className="objective-grid">
        <button aria-pressed="true">ϟ Max DPS</button>
        {["Max hit", "Accuracy", "Survivability"].map((s) => (
          <button key={s} disabled title="Unavailable: unsupported objective">
            {s}
            <small>Unavailable</small>
          </button>
        ))}
      </div>
      <div className="raised">
        <label>
          Additional purchase budget (GP)
          <input
            type="number"
            min="0"
            step="1"
            max="2147483647"
            value={draft.budget}
            onChange={(e) => change({ budget: e.target.value })}
          />
        </label>
        <input
          aria-label="Budget slider"
          type="range"
          min="0"
          max="100000000"
          step="100000"
          value={Math.min(Number(draft.budget), 100000000)}
          onChange={(e) => change({ budget: e.target.value })}
        />
        <p>
          {liveMode
            ? "Draft budget only. No account purchase estimate has been calculated."
            : "Fixture quotes only. Shared purchases counted once in the demo summary."}
        </p>
      </div>
      <label>
        Equipment access
        <select
          value={draft.mode}
          onChange={(e) => change({ mode: e.target.value as Draft["mode"] })}
        >
          <option value="owned">Observed owned only</option>
          <option value="usable">Owned + purchasable</option>
          <option value="future">Hypothetical access</option>
        </select>
      </label>
      <p className="green">✓ Requirements always enforced in production</p>
      <label className="check">
        <input type="checkbox" disabled /> Ban degradables · unavailable
      </label>
      <details>
        <summary>⚗ What-if assumptions</summary>
        <p>Draft-only hypotheses. No account changes.</p>
        <label>
          Assumed Attack level
          <input
            type="number"
            min="1"
            max="99"
            value={draft.assumptions.attack}
            onChange={(e) =>
              change({
                assumptions: { ...draft.assumptions, attack: e.target.value },
              })
            }
          />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.assumptions.quest}
            onChange={(e) =>
              change({
                assumptions: { ...draft.assumptions, quest: e.target.checked },
              })
            }
          />{" "}
          Assume demo quest complete
        </label>
        <label>
          Assumed acquired item IDs
          <input
            placeholder="4151, 6585"
            value={draft.assumptions.acquired}
            onChange={(e) =>
              change({
                assumptions: { ...draft.assumptions, acquired: e.target.value },
              })
            }
          />
        </label>
      </details>
      <details>
        <summary>Draft locks & exclusions</summary>
        <p>
          Production exclusions and manual evaluation are unavailable. These
          controls edit the preview draft only.
        </p>
        {draft.roles.map((r) => (
          <div key={r.id}>
            <strong>{r.name}</strong>
            {Object.entries(r.locks).map(([slot, id]) => (
              <div className="constraint" key={slot}>
                {slot}: {id ?? "empty"}
                <button
                  onClick={() => {
                    const locks = { ...r.locks };
                    delete locks[slot as keyof typeof locks];
                    roleChange(r.id, { locks });
                  }}
                >
                  Unlock {slot}
                </button>
              </div>
            ))}
          </div>
        ))}
        {draft.exclusions.map((id) => (
          <button
            key={id}
            onClick={() =>
              change({ exclusions: draft.exclusions.filter((i) => i !== id) })
            }
          >
            Remove exclusion {id}
          </button>
        ))}
      </details>
    </section>
  );
}
