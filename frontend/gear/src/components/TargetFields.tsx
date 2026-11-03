import type { ReactNode } from "react";
import type { CombatTarget, Draft } from "../api/contracts";
import type { DraftFieldErrors } from "../state/scenario";
import { FieldError, fieldProps } from "./FieldError";
import { NpcTargetPicker } from "./NpcTargetPicker";

function CustomTargetWrapper({
  isCollapsible,
  children,
}: {
  isCollapsible: boolean;
  children: ReactNode;
}) {
  if (!isCollapsible) return <>{children}</>;
  return (
    <details className="control-help">
      <summary>Use custom target stats</summary>
      {children}
    </details>
  );
}

export function TargetFields({
  draft,
  liveMode,
  targets,
  errors,
  change,
}: {
  draft: Draft;
  liveMode: boolean;
  targets: CombatTarget[];
  errors: DraftFieldErrors;
  change: (patch: Partial<Draft>) => void;
}) {
  return (
    <div className="raised">
      <span className="eyebrow blue">Encounter target</span>
      {liveMode && (
        <NpcTargetPicker
          selection={draft.targetSelection}
          inputs={draft.targetInputs}
          target={draft.combatTarget}
          onChange={(patch) =>
            change({
              ...patch,
              target: patch.combatTarget?.name ?? draft.target,
              defence: String(
                patch.combatTarget?.defence_level ?? draft.defence,
              ),
            })
          }
        />
      )}
      {liveMode && !draft.targetSelection && (
        <p className="target-hint">
          No NPC selected · using “{draft.target}”, defence {draft.defence}.
          Search above for a real target.
        </p>
      )}
      {!draft.targetSelection && (
        <CustomTargetWrapper isCollapsible={liveMode}>
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
              data-run-on-enter
              value={draft.defence}
              {...fieldProps("defence", errors.defence)}
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
          <FieldError id="defence" message={errors.defence} />
          <label>
            Flat armour
            <input
              type="number"
              min="-10000"
              max="10000"
              value={
                draft.targetInputs?.flat_armour ??
                draft.combatTarget?.flat_armour ??
                0
              }
              onChange={(event) =>
                change({
                  targetInputs: {
                    ...draft.targetInputs,
                    flat_armour: event.target.value,
                  },
                  combatTarget: {
                    name: draft.target,
                    defence_level: Number(draft.defence),
                    magic_level: 1,
                    bonuses: {},
                    ...draft.combatTarget,
                    flat_armour: Number(event.target.value),
                  },
                })
              }
            />
          </label>
          <p>
            Applied to each accurate melee or ranged hitsplat; negative values
            increase damage. Magic ignores flat armour.
          </p>
          <details className="control-help">
            <summary>About custom targets</summary>
            <p>
              Ordinary attacks only. User-supplied target assumptions; no
              encounter mechanics.
            </p>
          </details>
          {liveMode && (
            <p>
              {draft.combatTarget
                ? `Preset metadata retained: Magic ${draft.combatTarget.magic_level}; ${JSON.stringify(draft.combatTarget.bonuses)} defence bonuses. Preset encounter mechanics are not simulated.`
                : "Custom target assumes Magic level 1 and zero defence bonuses."}
            </p>
          )}
        </CustomTargetWrapper>
      )}
    </div>
  );
}
