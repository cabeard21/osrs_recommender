import type { PotionDefinition, PotionPolicy } from "../api/contracts";
import { groupPotions, potionQuickSelections } from "./potionFormat";

function sameIds(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id) => b.includes(id));
}

type Props = {
  policy?: PotionPolicy;
  catalog: readonly PotionDefinition[];
  onChange: (policy: PotionPolicy) => void;
};

/** "Combat potions" settings: the optimize toggle and the allowed potions. */
export function PotionFields({ policy, catalog, onChange }: Props) {
  const isOptimizing = policy?.mode === "optimize";
  const allowed = policy?.allowed_ids ?? [];
  const setAllowed = (ids: string[]) =>
    onChange({ mode: "optimize", allowed_ids: ids, selected_ids: [] });
  const toggle = (id: string, isChecked: boolean) =>
    setAllowed(
      isChecked ? [...allowed, id] : allowed.filter((other) => other !== id),
    );
  return (
    <fieldset className="potion-fields">
      <legend>
        Combat potions
        {isOptimizing ? ` · ${allowed.length} allowed` : ""}
      </legend>
      <label className="check">
        <input
          type="checkbox"
          checked={isOptimizing}
          onChange={(e) =>
            onChange({
              mode: e.target.checked ? "optimize" : "disabled",
              allowed_ids: allowed,
              selected_ids: [],
            })
          }
        />
        Optimize potions
      </label>
      {isOptimizing && (
        <>
          <div
            className="option-shortcuts"
            role="group"
            aria-label="Quick potion selections"
          >
            {potionQuickSelections(catalog).map(([label, ids]) => (
              <button
                type="button"
                key={label}
                aria-pressed={sameIds(allowed, ids)}
                onClick={() => setAllowed(ids)}
              >
                {label}
              </button>
            ))}
          </div>
          {allowed.length === 0 && (
            <p className="notice" role="status">
              No potions allowed yet. Tick at least one, or the optimizer runs
              without potions.
            </p>
          )}
          {groupPotions(catalog).map(([group, potions]) => (
            <div
              className="potion-group"
              role="group"
              aria-label={`${group} potions`}
              key={group}
            >
              <span className="potion-group-name">{group}</span>
              {potions.map((potion) => (
                <label className="check" key={potion.id}>
                  <input
                    type="checkbox"
                    checked={allowed.includes(potion.id)}
                    onChange={(e) => toggle(potion.id, e.target.checked)}
                  />
                  {potion.name}
                </label>
              ))}
            </div>
          ))}
          <details className="control-help">
            <summary>About potion optimization</summary>
            <p>
              Supplies are assumed available in every equipment mode. DPS uses
              freshly boosted levels; result graphs preview decay without
              changing recommendations. Supply endurance is not modeled. Potion
              cost is per application, separate from gear budget and attack
              resources. Divine potions consume HP when drunk.
            </p>
          </details>
        </>
      )}
    </fieldset>
  );
}
