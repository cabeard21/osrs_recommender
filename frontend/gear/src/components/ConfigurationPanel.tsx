import { Plus, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import type { CombatTarget, Draft, Role } from "../api/contracts";
import { potionCombatContext } from "../api/combatOptions";
import type { Objective } from "../api/objectives";
import { fixedTrip } from "../api/wilderness";
import { useGear } from "../state/GearProvider";
import { draftFieldErrors, newRole, parseGp } from "../state/scenario";
import { activeTimeWeight, validationMessage } from "../state/setupValidation";
import { AssumptionFields } from "./AssumptionFields";
import { CrystalHalberdFields } from "./CrystalHalberdFields";
import { FieldError, fieldProps } from "./FieldError";
import { GpBudgetInputs } from "./GpBudgetInputs";
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
import { ObjectiveBuilder } from "./ObjectiveBuilder";
import { PotionFields } from "./PotionFields";
import { RoleFields } from "./RoleFields";
import { effectiveRoleTarget } from "./RoleTargetEditor";
import { objectiveSummary, roleDiscipline } from "./RunReadback";
import { SavedSetups } from "./SavedSetups";
import { TargetFields } from "./TargetFields";
import { WildernessSettings } from "./WildernessSettings";
import "../styles/setup.css";

const DEFAULT_SUPPORT_POLICY = "community_best_effort";

export function ConfigurationPanel() {
  const { state, current, edit, liveMode, itemById } = useGear();
  const draft = current.draft;
  const [correction, setCorrection] = useState("");
  const errors = draftFieldErrors(draft);
  const isSingle = state.mode === "single";
  const change = (patch: Partial<Draft>) => edit({ ...draft, ...patch });
  const roleChange = (id: string, patch: Partial<Role>) =>
    change({
      roles: draft.roles.map((role) =>
        role.id === id ? { ...role, ...patch } : role,
      ),
    });
  const changeObjectives = (objectives: Objective[]) =>
    change({
      objectives,
      secondaryPriority: "default",
      // Apply the current cap when adding the trip objective.
      ...(draft.wilderness &&
        !fixedTrip(draft) &&
        fixedTrip({ objectives }) && { wildernessLimitLoss: true }),
    });
  const itemLabel = (id: number) => {
    const name = itemById(id)?.name;
    return name ? `${name} (#${id})` : `Item #${id}`;
  };
  const presets = (state.context?.live?.capabilities.encounter_presets ??
    []) as { name: string; roles: { target?: CombatTarget }[] }[];
  const targets = presets.flatMap((preset) =>
    preset.roles.flatMap(({ target }) =>
      target && !(target.unsupported_mechanics as string[] | undefined)?.length
        ? [target]
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
  const context = potionCombatContext(state.context, draft.potions);
  const budgetGp = Number(parseGp(draft.budget));
  const supportPolicy = draft.supportPolicy ?? DEFAULT_SUPPORT_POLICY;
  const scoredRoles = draft.roles.filter((role) => !role.utility);
  const validWeights = scoredRoles.every(
    (role) => !validationMessage(() => activeTimeWeight(role.weight)),
  );
  const totalWeight = validWeights
    ? scoredRoles.reduce((sum, role) => sum + Number(role.weight), 0)
    : 0;
  const autoRoles = scoredRoles.filter((role) => role.autoDiscipline);
  const disciplineCombinations = autoRoles.reduce(
    (count, role) => count * (role.allowedDisciplines?.length ?? 3),
    1,
  );
  const roleSummary = (role: Role) => {
    const share = totalWeight > 0 ? Number(role.weight) / totalWeight : null;
    return [
      role.name,
      roleDiscipline(role),
      role.utility ? null : effectiveRoleTarget(role, draft).name,
      role.utility
        ? null
        : share === null
          ? "Review active-time weights"
          : `${share.toLocaleString("en-US", { style: "percent", maximumFractionDigits: 1 })} active time`,
    ]
      .filter(Boolean)
      .join(" · ");
  };
  const roleFields = (role: Role, index: number) => (
    <RoleFields
      key={role.id}
      role={role}
      index={index}
      mode={state.mode}
      draft={draft}
      context={context}
      liveMode={liveMode}
      targets={targets}
      onChange={(patch) => roleChange(role.id, patch)}
      onRemove={() => removeRole(role.id)}
      onApplyTargetToAll={
        !isSingle && scoredRoles.length > 1
          ? () => edit(applyTargetToAll(draft, role.id))
          : undefined
      }
      isTargetSharedByAll={isTargetSharedByAll(draft, role.id)}
    />
  );
  return (
    <section className="panel configuration" aria-labelledby="parameters">
      <div className="setup-heading">
        <h2 id="parameters" className="eyebrow">
          <SlidersHorizontal size={17} /> Optimization parameters
        </h2>
        <SavedSetups draft={draft} mode={state.mode} edit={edit} />
      </div>
      <div className="setup-core">
        {isSingle && (
          <section className="setup-card" aria-labelledby="setup-target">
            <h3 id="setup-target">Encounter target</h3>
            <TargetFields
              draft={draft}
              liveMode={liveMode}
              targets={targets}
              errors={errors}
              change={change}
            />
          </section>
        )}
        <section
          className={`setup-card ${isSingle ? "" : "setup-combat-multi"}`}
          aria-labelledby="setup-combat"
        >
          <h3 id="setup-combat">
            {isSingle ? "Combat discipline" : "Combat configurations"}
          </h3>
          {isSingle ? (
            draft.roles.map(roleFields)
          ) : (
            <>
              <MultiTemplates draft={draft} edit={edit} />
              <div className="role-cards">
                {draft.roles.map((role, index) => (
                  <details
                    className="role-card"
                    key={role.id}
                    open={!current.result}
                  >
                    <summary>{roleSummary(role)}</summary>
                    {roleFields(role, index)}
                  </details>
                ))}
              </div>
              {autoRoles.length > 0 && (
                <p aria-label="Joint discipline search effort">
                  {disciplineCombinations} discipline combination
                  {disciplineCombinations === 1 ? "" : "s"} will be compared at
                  full joint search effort. Potion optimization adds searches
                  for each relevant potion setup.
                </p>
              )}
              <button
                type="button"
                disabled={draft.roles.length >= 4}
                onClick={() =>
                  change({
                    roles: [...draft.roles, newRole(nextRoleIndex(draft))],
                  })
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
        </section>
        <section className="setup-card" aria-labelledby="setup-budget">
          <h3 id="setup-budget">Budget and access</h3>
          <GpBudgetInputs
            name="budget"
            label="Additional purchase budget (GP)"
            sliderLabel="Budget slider"
            value={draft.budget}
            error={errors.budget}
            onChange={(budget) => change({ budget })}
            presets
          />
          <label>
            Equipment access
            <select
              value={draft.mode}
              onChange={(event) =>
                change({ mode: event.target.value as Draft["mode"] })
              }
            >
              <option value="owned">Observed owned only</option>
              <option value="usable">Owned + purchasable</option>
              <option value="future">Hypothetical access</option>
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={draft.includeUntradeables ?? false}
              disabled={draft.mode === "owned"}
              onChange={(event) =>
                change({ includeUntradeables: event.target.checked })
              }
            />
            Consider unowned untradeables
          </label>
          {draft.mode === "usable" && !errors.budget && budgetGp === 0 && (
            <p className="notice">
              {draft.includeUntradeables
                ? "Budget is 0, so tradeable gear must already be owned. Eligible untradeables are considered as hypothetical upgrades. Consumable ammunition is exempt."
                : "Budget is 0, so gear must already be owned. Consumable ammunition is exempt."}
            </p>
          )}
          <details className="control-help">
            <summary>How budget and access work</summary>
            <p>
              {liveMode
                ? "The purchase budget uses cached prices for additional gear. Owned items are reused and consumable ammunition is exempt."
                : "Fixture quotes only. Shared purchases are counted once in the demo summary."}
            </p>
            <p>
              Obtain eligible untradeables separately. Item requirements still
              apply.
            </p>
          </details>
        </section>
        <section className="setup-card" aria-labelledby="setup-goals">
          <h3 id="setup-goals">Optimize for</h3>
          <details className="setup-objectives">
            <summary>
              Tradeoff objectives <small>· {objectiveSummary(draft)}</small>
            </summary>
            <ObjectiveBuilder
              wilderness={!!draft.wilderness}
              wildernessControl
              showHeading={false}
              objectives={draft.objectives}
              legacyPriority={draft.secondaryPriority}
              mode={draft.optimizationMode}
              onChange={changeObjectives}
            />
          </details>
          <label>
            Optimization mode
            <select
              value={draft.optimizationMode ?? "fast"}
              onChange={(event) =>
                change({
                  optimizationMode: event.target
                    .value as Draft["optimizationMode"],
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
              Fast uses a bounded search. Thorough searches additional equipment
              combinations and can take substantially longer.
            </p>
            {!liveMode && (
              <p>Fixture mode records this selection and uses demo results.</p>
            )}
          </details>
        </section>
      </div>
      <WildernessSettings
        draft={draft}
        change={change}
        changeObjectives={changeObjectives}
      />
      <div className="setup-disclosures">
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
          <LockConstraints
            draft={draft}
            change={change}
            itemLabel={itemLabel}
          />
        </details>
        <details>
          <summary>
            Combat resources
            <small>
              {" · "}Potions{" "}
              {draft.potions?.mode === "optimize" ? "optimized" : "off"} · Tome{" "}
              {draft.fireTomePages ?? "burnt"}
            </small>
          </summary>
          <PotionFields
            policy={draft.potions}
            catalog={state.context?.live?.potion_catalog ?? []}
            onChange={(potions) => change({ potions })}
          />
          <label>
            Tome of Fire pages
            <select
              value={draft.fireTomePages ?? "burnt"}
              onChange={(event) =>
                change({
                  fireTomePages: event.target.value as Draft["fireTomePages"],
                })
              }
            >
              <option value="burnt">Burnt</option>
              <option value="searing">Searing</option>
            </select>
          </label>
          <p>Tome page availability, consumption, and costs are excluded.</p>
          <CrystalHalberdFields
            policy={draft.crystalHalberdCharging}
            onChange={(crystalHalberdCharging) =>
              change({ crystalHalberdCharging })
            }
          />
        </details>
        <details>
          <summary>
            Advanced settings
            {supportPolicy !== DEFAULT_SUPPORT_POLICY
              ? " · verified equipment only"
              : ""}
          </summary>
          <label>
            Equipment support policy
            <select
              value={supportPolicy}
              onChange={(event) =>
                change({
                  supportPolicy: event.target.value as Draft["supportPolicy"],
                })
              }
            >
              <option value="community_best_effort">
                Community best effort
              </option>
              <option value="verified_only">Verified only</option>
            </select>
          </label>
          <details className="control-help">
            <summary>About the equipment support policy</summary>
            <p>
              Community best effort uses community skill gates for classified
              ordinary equipment. Unresolved gates are assumed satisfied and
              labeled community-assumed. Verified only requires reviewed
              eligibility.
            </p>
          </details>
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
                  onChange={(event) => change({ supplies: event.target.value })}
                />
              </label>
              <FieldError id="supplies" message={errors.supplies} />
            </>
          )}
        </details>
      </div>
    </section>
  );
}
