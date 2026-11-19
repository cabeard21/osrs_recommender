import { CrystalHalberdFields } from "./CrystalHalberdFields";
import { Plus, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useGear } from "../state/GearProvider";
import { draftFieldErrors, newRole, parseGp } from "../state/scenario";
import type { CombatTarget, Draft, Role } from "../api/contracts";
import { potionCombatContext } from "../api/combatOptions";
import { ObjectiveBuilder } from "./ObjectiveBuilder";
import { AssumptionFields } from "./AssumptionFields";
import { FieldError, fieldProps } from "./FieldError";
import { GpBudgetInputs } from "./GpBudgetInputs";
import { LockConstraints } from "./LockConstraints";
import { MultiLockEditor } from "./MultiLockEditor";
import { MultiTemplates } from "./MultiTemplates";
import { MultiTransitions } from "./MultiTransitions";
import { PotionFields } from "./PotionFields";
import {
  applyTargetToAll,
  isTargetSharedByAll,
  nextRoleIndex,
  removeMultiRole,
} from "./multiDraft";
import { RoleFields } from "./RoleFields";
import { SavedSetups } from "./SavedSetups";
import {
  fixedTrip,
  limitTripLoss,
  DEFAULT_WILDERNESS_SPELL_CASTS,
  defaultWilderness,
  wildernessMayUseMagic,
} from "../api/wilderness";
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
  const wilderness = draft.wilderness;
  const secondaryPriority = draft.secondaryPriority ?? "default";
  const supportPolicy = draft.supportPolicy ?? DEFAULT_SUPPORT_POLICY;
  const hasAdvancedChanges =
    supportPolicy !== DEFAULT_SUPPORT_POLICY ||
    secondaryPriority !== "default" ||
    !!draft.objectives?.length;
  const budgetSection = (
    <>
      <span className="eyebrow">Budget and equipment</span>
      <div className="raised">
        <GpBudgetInputs
          name="budget"
          label="Additional purchase budget (GP)"
          sliderLabel="Budget slider"
          value={draft.budget}
          error={errors.budget}
          onChange={(budget) => change({ budget })}
          presets
        />
        <p>
          {liveMode
            ? "This budget covers additional gear purchases. Consumable ammunition are exempt. Items you own are reused, and prices are cached estimates."
            : "Fixture quotes only. Shared purchases counted once in the demo summary."}
        </p>
        {draft.mode === "usable" && !errors.budget && budgetGp === 0 && (
          <p className="notice">
            {draft.includeUntradeables
              ? "Budget is 0, so tradeable gear must already be owned. Eligible untradeables are considered as hypothetical upgrades. Consumable ammunition are exempt."
              : "Budget is 0, so gear must already be owned. Consumable ammunition are exempt."}
          </p>
        )}
      </div>
      <div className="raised">
        <label>
          <input
            type="checkbox"
            checked={!!wilderness}
            onChange={(e) =>
              change({
                ...(!e.target.checked && fixedTrip(draft)
                  ? {
                      objectives: draft.objectives?.filter(
                        (o) => o.kind !== "wilderness_loss_gp",
                      ),
                    }
                  : {}),
                wilderness: e.target.checked
                  ? { ...defaultWilderness }
                  : undefined,
              })
            }
          />{" "}
          Wilderness
        </label>
        {wilderness && (
          <>
            {fixedTrip(draft) && (
              <label>
                <input
                  type="checkbox"
                  checked={!limitTripLoss(draft)}
                  onChange={(e) =>
                    change({ wildernessLimitLoss: !e.target.checked })
                  }
                />{" "}
                No loss cap
              </label>
            )}
            {(!fixedTrip(draft) || limitTripLoss(draft)) && (
              <GpBudgetInputs
                name="wildernessRiskBudget"
                label="Max gear loss if PK’d (GP)"
                sliderLabel="Wilderness risk slider"
                value={draft.wildernessRiskBudget ?? "0"}
                error={errors.wildernessRiskBudget}
                onChange={(wildernessRiskBudget) =>
                  change({ wildernessRiskBudget, wildernessLimitLoss: true })
                }
                minimum={10}
              />
            )}
            <label>
              Wilderness depth
              <select
                value={wilderness.depth}
                onChange={(e) =>
                  change({
                    wilderness: {
                      ...wilderness,
                      depth:
                        e.target.value === "level_1_20"
                          ? "level_1_20"
                          : "level_21_plus",
                    },
                  })
                }
              >
                <option value="level_1_20">Level 1–20</option>
                <option value="level_21_plus">Level 21+</option>
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={wilderness.skulled}
                onChange={(e) =>
                  change({
                    wilderness: { ...wilderness, skulled: e.target.checked },
                  })
                }
              />{" "}
              Skulled at death
            </label>
            <label>
              <input
                type="checkbox"
                checked={wilderness.protect_item}
                onChange={(e) =>
                  change({
                    wilderness: {
                      ...wilderness,
                      protect_item: e.target.checked,
                    },
                  })
                }
              />{" "}
              Assume Protect Item is active at death
            </label>
            <p>Protect Item requires level 25 Prayer.</p>
            {(fixedTrip(draft) || wildernessMayUseMagic(draft.roles)) && (
              <>
                <label>
                  {fixedTrip(draft)
                    ? "Attacks per combat setup"
                    : "Casts to pack per Magic setup"}
                  <input
                    inputMode="numeric"
                    data-run-on-enter
                    value={
                      draft.wildernessSpellCasts ??
                      String(DEFAULT_WILDERNESS_SPELL_CASTS)
                    }
                    {...fieldProps(
                      "wilderness-spell-casts",
                      errors.wildernessSpellCasts,
                    )}
                    onChange={(event) =>
                      change({ wildernessSpellCasts: event.target.value })
                    }
                  />
                </label>
                <FieldError
                  id="wilderness-spell-casts"
                  message={errors.wildernessSpellCasts}
                />
                <p>
                  {fixedTrip(draft)
                    ? "Ammo quantities use expected recovery. Your stack can run out earlier."
                    : "The optimizer packs loose runes after accounting for runes supplied by your staff."}
                </p>
              </>
            )}
            <p>
              Estimates loss on a standard Wilderness PvP death for worn gear,
              switches, and the recommended ammo, charges, and spell runes.
              Extra inventory can add losses or change which items are
              protected.
            </p>
          </>
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
        : role.autoDiscipline
          ? "Auto"
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
  const hasAutoRoles = draft.roles.some(
    (role) => !role.utility && role.autoDiscipline,
  );
  const disciplineCombinations = draft.roles.reduce(
    (count, role) =>
      count *
      (!role.utility && role.autoDiscipline
        ? (role.allowedDisciplines?.length ?? 3)
        : 1),
    1,
  );
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
          {hasAutoRoles && (
            <p aria-label="Joint discipline search effort">
              {disciplineCombinations} discipline combination
              {disciplineCombinations === 1 ? "" : "s"} will be compared at full
              joint search effort. Potion optimization adds searches for each
              relevant potion setup. More combinations can take substantially
              longer.
            </p>
          )}
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
      <label>
        <input
          type="checkbox"
          checked={draft.includeUntradeables ?? false}
          disabled={draft.mode === "owned"}
          onChange={(event) =>
            change({ includeUntradeables: event.target.checked })
          }
        />{" "}
        Consider unowned untradeables
      </label>
      <p>
        Include eligible untradeables as hypothetical upgrades. Obtain these
        separately; they do not use the GP budget. Skill and quest wear
        requirements still apply.
      </p>
      {draft.mode === "owned" && (
        <p>
          Observed owned only excludes unowned gear regardless of this setting.
        </p>
      )}
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
      <label>
        Tome of Fire pages
        <select
          value={draft.fireTomePages ?? "burnt"}
          onChange={(e) =>
            change({ fireTomePages: e.target.value as Draft["fireTomePages"] })
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
      <PotionFields
        policy={draft.potions}
        catalog={state.context?.live?.potion_catalog ?? []}
        onChange={(potions) => change({ potions })}
      />
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
        <ObjectiveBuilder
          wilderness={!!wilderness}
          objectives={draft.objectives}
          legacyPriority={draft.secondaryPriority}
          mode={draft.optimizationMode}
          onChange={(objectives) =>
            change({ objectives, secondaryPriority: "default" })
          }
        />
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
