import { Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useState } from "react";
import { useGear } from "../state/GearProvider";
import { newRole } from "../state/scenario";
import type { CombatTarget, Draft, Role, Style } from "../api/contracts";
import { RoleTargetEditor } from "./RoleTargetEditor";
import { MultiTransitions } from "./MultiTransitions";
import { MultiLockEditor } from "./MultiLockEditor";
import { nextRoleIndex, removeMultiRole } from "./multiDraft";
import { secondaryPriorities } from "../api/secondaryPriorities";
import { CombatOptionsControls } from "./CombatOptionsControls";
export function ConfigurationPanel() {
  const { state, current, edit, liveMode } = useGear(),
    draft = current.draft;
  const [correction, setCorrection] = useState("");
  const change = (patch: Partial<Draft>) => edit({ ...draft, ...patch });
  const roleChange = (id: string, patch: Partial<Role>) =>
    change({
      roles: draft.roles.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    });
  const presets = (state.context?.live?.capabilities.encounter_presets ??
    []) as { name: string; roles: { target?: CombatTarget }[] }[];
  const targets = presets.flatMap((preset) =>
    preset.roles.flatMap((role) =>
      role.target &&
      !(role.target.unsupported_mechanics as string[] | undefined)?.length
        ? [role.target]
        : [],
    ),
  );
  return (
    <section className="panel configuration" aria-labelledby="parameters">
      <h2 id="parameters" className="eyebrow">
        <SlidersHorizontal size={17} /> Optimization parameters
      </h2>
      <label>
        Equipment support policy
        <select
          value={draft.supportPolicy ?? "community_best_effort"}
          onChange={(e) =>
            change({ supportPolicy: e.target.value as Draft["supportPolicy"] })
          }
        >
          <option value="community_best_effort">Community best effort</option>
          <option value="verified_only">Verified only</option>
        </select>
      </label>
      <p>
        Community best effort allows classified ordinary equipment using
        community skill gates. Unresolved equip gates are assumed satisfied and
        items are labeled community-assumed. Known unsupported mechanics remain
        excluded. Verified only requires reviewed eligibility.
      </p>
      <label>
        Optimization mode
        <select
          value={draft.optimizationMode ?? "fast"}
          onChange={(e) =>
            change({
              optimizationMode: e.target.value as Draft["optimizationMode"],
            })
          }
        >
          <option value="fast">Fast</option>
          <option value="thorough">Thorough</option>
        </select>
      </label>
      <p>
        Fast uses the existing bounded search. Thorough searches additional
        equipment combinations and can take substantially longer. Neither mode
        guarantees globally optimal equipment.
      </p>
      {!liveMode && (
        <p>Fixture mode records this selection; it does not run refinement.</p>
      )}
      <label>
        Secondary priority
        <select
          value={draft.secondaryPriority ?? "default"}
          onChange={(e) =>
            change({
              secondaryPriority: e.target.value as Draft["secondaryPriority"],
            })
          }
        >
          {secondaryPriorities.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {(draft.secondaryPriority ?? "default") !== "default" && (
        <label>
          Maximum DPS loss (%)
          <input
            type="number"
            min="0"
            max="100"
            step="0.1"
            value={draft.maxDpsLossPct ?? "10"}
            onChange={(e) => change({ maxDpsLossPct: e.target.value })}
          />
          <span>Run optimization to apply the range.</span>
        </label>
      )}
      {state.mode === "single" && (
        <div className="raised">
          <span className="eyebrow blue">Encounter target</span>
          {liveMode && (
            <label>
              Target selection
              <select
                value={
                  targets.some(
                    (target) => target.name === draft.combatTarget?.name,
                  )
                    ? draft.combatTarget!.name
                    : "custom"
                }
                onChange={(e) => {
                  const target = targets.find((t) => t.name === e.target.value);
                  change({
                    combatTarget: target ? structuredClone(target) : undefined,
                    target: target?.name ?? "Custom ordinary-attack target",
                    defence: String(target?.defence_level ?? 1),
                  });
                }}
              >
                <option value="custom">Custom ordinary-attack target</option>
                {targets.map((target) => (
                  <option key={target.name} value={target.name}>
                    {target.name} · ordinary attacks
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Custom target
            <input
              value={draft.target}
              onChange={(e) =>
                change({
                  target: e.target.value,
                  combatTarget: draft.combatTarget
                    ? { ...draft.combatTarget, name: e.target.value }
                    : undefined,
                })
              }
            />
          </label>
          <label>
            Target defence
            <input
              type="number"
              min="0"
              max="1000"
              value={draft.defence}
              onChange={(e) =>
                change({
                  defence: e.target.value,
                  combatTarget: draft.combatTarget
                    ? {
                        ...draft.combatTarget,
                        defence_level: Number(e.target.value),
                      }
                    : undefined,
                })
              }
            />
          </label>
          <p>
            Ordinary attacks only. User-supplied target assumptions; no
            encounter mechanics.
          </p>
          {liveMode && (
            <p>
              {draft.combatTarget
                ? `Preset metadata retained: Magic ${draft.combatTarget.magic_level}; ${JSON.stringify(draft.combatTarget.bonuses)} defence bonuses. Preset encounter mechanics are not simulated.`
                : "Custom target assumes Magic level 1 and zero defence bonuses."}
            </p>
          )}
        </div>
      )}
      <span className="eyebrow">Combat configurations</span>
      {draft.roles.map((role, index) => (
        <fieldset key={role.id}>
          <legend>
            {state.mode === "single"
              ? "Combat discipline"
              : `Configuration ${index + 1}`}
          </legend>
          {state.mode === "multi" && (
            <>
              <label>
                Name
                <input
                  value={role.name}
                  onChange={(e) =>
                    roleChange(role.id, { name: e.target.value })
                  }
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={role.utility ?? false}
                  disabled={
                    !role.utility &&
                    draft.roles.some(
                      (candidate) =>
                        candidate.utility && candidate.parentRole === role.id,
                    )
                  }
                  onChange={(event) =>
                    roleChange(role.id, {
                      utility: event.target.checked,
                      parentRole: event.target.checked
                        ? draft.roles.find(
                            (candidate) =>
                              candidate.id !== role.id && !candidate.utility,
                          )?.id
                        : undefined,
                    })
                  }
                />
                Unscored utility configuration
              </label>
              {role.utility ? (
                <div className="raised">
                  <p>
                    Equipment carriage only. No special-attack damage or utility
                    score is calculated.
                  </p>
                  <label>
                    Parent configuration
                    <select
                      value={role.parentRole ?? ""}
                      onChange={(event) =>
                        roleChange(role.id, { parentRole: event.target.value })
                      }
                    >
                      <option value="">Choose ordinary parent</option>
                      {draft.roles
                        .filter(
                          (candidate) =>
                            candidate.id !== role.id && !candidate.utility,
                        )
                        .map((candidate) => (
                          <option value={candidate.id} key={candidate.id}>
                            {candidate.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Utility weapon physical ID
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={role.locks.weapon ?? ""}
                      onChange={(event) =>
                        roleChange(role.id, {
                          locks: {
                            ...role.locks,
                            weapon: event.target.value
                              ? Number(event.target.value)
                              : null,
                          },
                        })
                      }
                    />
                  </label>
                </div>
              ) : (
                <RoleTargetEditor
                  role={role}
                  draft={draft}
                  targets={targets}
                  onChange={(patch) => roleChange(role.id, patch)}
                />
              )}
            </>
          )}
          {!role.utility && (
            <>
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
              <CombatOptionsControls
                role={role}
                context={state.context}
                liveMode={liveMode}
                onChange={(patch) => roleChange(role.id, patch)}
              />
              {role.combatOptionOptimization === false &&
                role.style === "melee" && (
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
              {role.combatOptionOptimization === false && (
                <label>
                  Attack stance
                  <select
                    value={role.stance}
                    onChange={(e) =>
                      roleChange(role.id, { stance: e.target.value })
                    }
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
              )}
              {role.combatOptionOptimization === false &&
                role.style === "magic" && (
                  <label>
                    Standard spell
                    <select
                      value={role.spell}
                      onChange={(e) =>
                        roleChange(role.id, { spell: e.target.value })
                      }
                    >
                      {(liveMode
                        ? (
                            (state.context?.live?.capabilities.spells ??
                              []) as {
                              id: string;
                            }[]
                          ).map((s) => s.id)
                        : [
                            "fire_strike",
                            "wind_wave",
                            "water_wave",
                            "earth_wave",
                            "fire_wave",
                          ]
                      ).map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>
                  </label>
                )}
            </>
          )}
          {state.mode === "multi" && (
            <>
              {!role.utility && (
                <label>
                  Active-time weight
                  <input
                    type="number"
                    min="0"
                    max="1000000"
                    step="any"
                    value={role.weight}
                    onChange={(e) =>
                      roleChange(role.id, { weight: e.target.value })
                    }
                  />
                </label>
              )}
              <button
                disabled={draft.roles.length <= 2}
                onClick={() => {
                  try {
                    const removed = removeMultiRole(draft, role.id);
                    edit(removed.draft);
                    setCorrection(removed.notice);
                  } catch (error) {
                    setCorrection((error as Error).message);
                  }
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
              change({
                roles: [...draft.roles, newRole(nextRoleIndex(draft))],
              });
            }}
          >
            <Plus size={16} /> Add configuration
          </button>
          {correction && (
            <p role="status" className="notice">
              {correction}
            </p>
          )}
          <MultiTransitions draft={draft} change={change} />
        </>
      )}
      {state.mode === "single" && (
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
            ? "Additional purchases only. Existing owned equipment is reused; estimates come from Python cached price facts."
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
      <p className="green">✓ Requirements enforced by Python</p>
      <label className="check">
        <input type="checkbox" disabled /> Ban degradables · unavailable
      </label>
      <details>
        <summary>⚗ What-if assumptions</summary>
        <p>
          Explicit request-local hypotheses. Select hypothetical access to apply
          them; no account changes.
        </p>
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
        {!liveMode && (
          <label className="check">
            <input
              type="checkbox"
              checked={draft.assumptions.quest}
              onChange={(e) =>
                change({
                  assumptions: {
                    ...draft.assumptions,
                    quest: e.target.checked,
                  },
                })
              }
            />{" "}
            Assume demo quest complete
          </label>
        )}
        {liveMode && (
          <>
            <label>
              Other assumed skill levels
              <input
                placeholder="strength=80, ranged=75"
                value={draft.assumptions.skillLevels ?? ""}
                onChange={(e) =>
                  change({
                    assumptions: {
                      ...draft.assumptions,
                      skillLevels: e.target.value,
                    },
                  })
                }
              />
            </label>
            <label>
              Assumed completed quest IDs
              <input
                placeholder="monkey_madness_i"
                value={draft.assumptions.completedQuests ?? ""}
                onChange={(e) =>
                  change({
                    assumptions: {
                      ...draft.assumptions,
                      completedQuests: e.target.value,
                    },
                  })
                }
              />
            </label>
            <p>
              Use canonical quest IDs separated by commas. Python validates
              skill and quest identities.
            </p>
          </>
        )}
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
        <summary>
          {liveMode
            ? "Equipment locks & exclusions"
            : "Draft locks & exclusions"}
        </summary>
        <p>
          {liveMode
            ? state.mode === "multi"
              ? "Locks and exclusions apply on the next joint optimization. Inspect physical item facts or edit global and role constraints. Joint manual trials are unavailable."
              : "Locks and exclusions apply on the next optimization. Inspect a slot to preview an alternative, lock a physical item or an empty slot, or exclude an item."
            : "These controls edit the fixture draft only. Fixture trials use authored examples."}
        </p>
        {state.mode === "multi" && (
          <MultiLockEditor draft={draft} change={change} />
        )}
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
