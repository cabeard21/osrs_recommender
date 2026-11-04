import { Plus, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useGear } from "../state/GearProvider";
import {
  BUDGET_PRESETS,
  SLIDER_MAX,
  budgetToSlider,
  sliderToBudget,
} from "../state/budget";
import { draftFieldErrors, newRole, parseGp } from "../state/scenario";
import type { CombatTarget, Draft, Role } from "../api/contracts";
import { potionCombatContext } from "../api/combatOptions";
import { secondaryPriorities } from "../api/secondaryPriorities";
import { AssumptionFields } from "./AssumptionFields";
import { FieldError, fieldProps } from "./FieldError";
import { LockConstraints } from "./LockConstraints";
import { MultiLockEditor } from "./MultiLockEditor";
import { MultiTemplates } from "./MultiTemplates";
import { MultiTransitions } from "./MultiTransitions";
import {
  applyTargetToAll,
  isTargetSharedByAll,
  nextRoleIndex,
  removeMultiRole,
} from "./multiDraft";
import { RoleFields } from "./RoleFields";
import { SavedSetups } from "./SavedSetups";
import { TargetFields } from "./TargetFields";

const DEFAULT_SUPPORT_POLICY = "community_best_effort";

export function ConfigurationPanel() {
  const { state, current, edit, liveMode, itemById } = useGear(),
    draft = current.draft;
  const [correction, setCorrection] = useState("");
  const errors = draftFieldErrors(draft);
  const isSingle = state.mode === "single";
  const change = (patch: Partial<Draft>) => edit({ ...draft, ...patch });
  const roleChange = (id: string, patch: Partial<Role>) =>
    change({
      roles: draft.roles.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    });
  const itemLabel = (id: number) => {
    const name = itemById(id)?.name;
    return name ? `${name} (#${id})` : `Item #${id}`;
  };
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
  const removeRole = (id: string) => {
    try {
      const removed = removeMultiRole(draft, id);
      edit(removed.draft);
      setCorrection(removed.notice);
    } catch (error) {
      setCorrection((error as Error).message);
    }
  };
  const budgetGp = Number(parseGp(draft.budget));
  const secondaryPriority = draft.secondaryPriority ?? "default";
  const supportPolicy = draft.supportPolicy ?? DEFAULT_SUPPORT_POLICY;
  const hasAdvancedChanges =
    supportPolicy !== DEFAULT_SUPPORT_POLICY || secondaryPriority !== "default";
  const budgetSection = (
    <>
      <span className="eyebrow">Budget and equipment</span>
      <div className="raised">
        <label>
          Additional purchase budget (GP)
          <input
            inputMode="numeric"
            placeholder="10m, 500k or 12345"
            data-run-on-enter
            value={draft.budget}
            {...fieldProps("budget", errors.budget)}
            onChange={(e) => change({ budget: e.target.value })}
          />
        </label>
        <FieldError id="budget" message={errors.budget} />
        {!errors.budget && budgetGp > 0 && (
          <span className="numeric">{budgetGp.toLocaleString()} GP</span>
        )}
        <input
          aria-label="Budget slider"
          aria-valuetext={`${(budgetGp || 0).toLocaleString()} GP`}
          type="range"
          min="0"
          max={SLIDER_MAX}
          step="1"
          value={budgetToSlider(budgetGp)}
          onChange={(e) =>
            change({ budget: String(sliderToBudget(Number(e.target.value))) })
          }
        />
        <div
          className="budget-presets"
          role="group"
          aria-label="Budget presets"
        >
          {BUDGET_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={draft.budget === preset}
              onClick={() => change({ budget: preset })}
            >
              {preset}
            </button>
          ))}
        </div>
        <p>
          {liveMode
            ? "Additional gear purchases only. Ammo and darts ignore this budget. Items you own are reused; prices are cached estimates."
            : "Fixture quotes only. Shared purchases counted once in the demo summary."}
        </p>
        {draft.mode === "usable" && !errors.budget && budgetGp === 0 && (
          <p className="notice">
            Budget is 0, so gear must already be owned. Ammo and darts are
            exempt.
          </p>
        )}
      </div>
    </>
  );
  const roleSummary = (role: Role) =>
    [
      role.name,
      // Template names such as "Magic" already say the style.
      role.utility
        ? "Utility"
        : role.name.toLowerCase() === role.style
          ? null
          : role.style,
      role.combatTarget?.name,
      role.utility ? null : `weight ${role.weight}`,
    ]
      .filter(Boolean)
      .join(" · ");
  const hasSeveralScoredRoles =
    !isSingle && draft.roles.filter((role) => !role.utility).length > 1;
  const roleFields = (role: Role, index: number) => (
    <RoleFields
      key={role.id}
      role={role}
      index={index}
      mode={state.mode}
      draft={draft}
      context={potionCombatContext(state.context, draft.potions)}
      liveMode={liveMode}
      targets={targets}
      onChange={(patch) => roleChange(role.id, patch)}
      onRemove={() => removeRole(role.id)}
      onApplyTargetToAll={
        hasSeveralScoredRoles
          ? () => edit(applyTargetToAll(draft, role.id))
          : undefined
      }
      isTargetSharedByAll={isTargetSharedByAll(draft, role.id)}
    />
  );
  return (
    <section className="panel configuration" aria-labelledby="parameters">
      <h2 id="parameters" className="eyebrow">
        <SlidersHorizontal size={17} /> Optimization parameters
      </h2>
      <SavedSetups draft={draft} mode={state.mode} edit={edit} />
      {isSingle && (
        <TargetFields
          draft={draft}
          liveMode={liveMode}
          targets={targets}
          errors={errors}
          change={change}
        />
      )}
      {!isSingle && budgetSection}
      <span className="eyebrow">Combat configurations</span>
      {!isSingle && <MultiTemplates draft={draft} edit={edit} />}
      {isSingle ? (
        draft.roles.map(roleFields)
      ) : (
        <div className="role-cards">
          {draft.roles.map((role, index) => (
            <details className="role-card" key={role.id} open={!current.result}>
              <summary>{roleSummary(role)}</summary>
              {roleFields(role, index)}
            </details>
          ))}
        </div>
      )}
      {!isSingle && (
        <>
          <button
            disabled={draft.roles.length >= 4}
            onClick={() =>
              change({ roles: [...draft.roles, newRole(nextRoleIndex(draft))] })
            }
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
      {isSingle && budgetSection}
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
      <p className="green">✓ Item requirements are enforced</p>
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
      <details className="control-help">
        <summary>About optimization modes</summary>
        <p>
          Fast uses the existing bounded search. Thorough searches additional
          equipment combinations and can take substantially longer. Neither mode
          guarantees globally optimal equipment.
        </p>
        {!liveMode && (
          <p>
            Fixture mode records this selection; it does not run refinement.
          </p>
        )}
      </details>
      <AssumptionFields
        draft={draft}
        liveMode={liveMode}
        errors={errors}
        change={change}
      />
      <details>
        <summary>
          {liveMode
            ? "Equipment locks & exclusions"
            : "Draft locks & exclusions"}
        </summary>
        <p>
          {liveMode
            ? !isSingle
              ? "Locks and exclusions apply on the next joint optimization. Inspect item facts or edit global and role constraints. Joint manual trials are unavailable."
              : "Locks and exclusions apply on the next optimization. Inspect a slot to preview an alternative, lock an item or an empty slot, or exclude an item."
            : "These controls edit the fixture draft only. Fixture trials use authored examples."}
        </p>
        <MultiLockEditor
          draft={draft}
          change={change}
          itemLabel={itemLabel}
          isSingle={isSingle}
        />
        <LockConstraints draft={draft} change={change} itemLabel={itemLabel} />
      </details>
      <fieldset>
        <legend>Combat potions</legend>
        <label>
          <input
            type="checkbox"
            checked={draft.potions?.mode === "optimize"}
            onChange={(e) =>
              change({
                potions: {
                  mode: e.target.checked ? "optimize" : "disabled",
                  allowed_ids: draft.potions?.allowed_ids ?? [],
                  selected_ids: [],
                },
              })
            }
          />
          Optimize potions
        </label>
        {draft.potions?.mode === "optimize" && (
          <>
            <p>
              Choose allowed potions. Empty selection permits no potions.
              Supplies are assumed available in every equipment mode.
            </p>
            {(state.context?.live?.potion_catalog ?? []).map((potion) => (
              <label key={potion.id}>
                <input
                  type="checkbox"
                  checked={draft.potions!.allowed_ids.includes(potion.id)}
                  onChange={(e) =>
                    change({
                      potions: {
                        ...draft.potions!,
                        allowed_ids: e.target.checked
                          ? [...draft.potions!.allowed_ids, potion.id]
                          : draft.potions!.allowed_ids.filter(
                              (id) => id !== potion.id,
                            ),
                      },
                    })
                  }
                />
                {potion.name}
              </label>
            ))}
            <p>
              Freshly boosted DPS; no decay, duration benefit or supply
              endurance. Potion cost is per application, separate from gear
              budget and attack resources.
            </p>
          </>
        )}
      </fieldset>
      <details>
        <summary>
          Advanced settings{hasAdvancedChanges ? " · modified" : ""}
        </summary>
        <label>
          Equipment support policy
          <select
            value={supportPolicy}
            onChange={(e) =>
              change({
                supportPolicy: e.target.value as Draft["supportPolicy"],
              })
            }
          >
            <option value="community_best_effort">Community best effort</option>
            <option value="verified_only">Verified only</option>
          </select>
        </label>
        <details className="control-help">
          <summary>About the equipment support policy</summary>
          <p>
            Community best effort allows classified ordinary equipment using
            community skill gates. Unresolved equip gates are assumed satisfied
            and items are labeled community-assumed. Known unsupported mechanics
            remain excluded. Verified only requires reviewed eligibility.
          </p>
        </details>
        <label>
          Secondary priority
          <select
            value={secondaryPriority}
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
        {secondaryPriority !== "default" && (
          <label>
            Maximum DPS loss (%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              data-run-on-enter
              value={draft.maxDpsLossPct ?? "10"}
              {...fieldProps("loss", errors.maxDpsLoss)}
              onChange={(e) => change({ maxDpsLossPct: e.target.value })}
            />
            <span>Run optimization to apply the range.</span>
          </label>
        )}
        {secondaryPriority !== "default" && (
          <FieldError id="loss" message={errors.maxDpsLoss} />
        )}
        {isSingle && (
          <>
            <label>
              Reserved supply slots
              <input
                type="number"
                min="0"
                max="28"
                data-run-on-enter
                value={draft.supplies}
                {...fieldProps("supplies", errors.supplies)}
                onChange={(e) => change({ supplies: e.target.value })}
              />
            </label>
            <FieldError id="supplies" message={errors.supplies} />
          </>
        )}
      </details>
    </section>
  );
}
