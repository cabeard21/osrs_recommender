import type { Draft } from "../api/contracts";
import { legacyObjectives, type Objective } from "../api/objectives";
import {
  defaultWilderness,
  DEFAULT_WILDERNESS_SPELL_CASTS,
  fixedTrip,
  limitTripLoss,
  wildernessMayUseMagic,
} from "../api/wilderness";
import { draftFieldErrors, parseGp } from "../state/scenario";
import { FieldError, fieldProps } from "./FieldError";
import { GpBudgetInputs } from "./GpBudgetInputs";

export function WildernessSettings({
  draft,
  change,
  changeObjectives,
}: {
  draft: Draft;
  change: (patch: Partial<Draft>) => void;
  changeObjectives: (objectives: Objective[]) => void;
}) {
  const wilderness = draft.wilderness;
  const trip = fixedTrip(draft);
  const capped = !trip || limitTripLoss(draft);
  const goals = draft.objectives ?? legacyObjectives(draft.secondaryPriority);
  const errors = draftFieldErrors(draft);
  const attacks =
    draft.wildernessSpellCasts ?? String(DEFAULT_WILDERNESS_SPELL_CASTS);
  return (
    <fieldset className="raised wilderness-settings">
      <legend>Wilderness settings</legend>
      <label className="check">
        <input
          type="checkbox"
          checked={!!wilderness}
          onChange={(event) =>
            change(
              event.target.checked
                ? { wilderness: { ...defaultWilderness } }
                : {
                    wilderness: undefined,
                    ...(trip && {
                      objectives: goals.filter(
                        (goal) => goal.kind !== "wilderness_loss_gp",
                      ),
                    }),
                  },
            )
          }
        />
        Wilderness
      </label>
      {wilderness && (
        <>
          <label className="check">
            <input
              type="checkbox"
              checked={trip}
              onChange={(event) =>
                changeObjectives(
                  event.target.checked
                    ? [...goals, { kind: "wilderness_loss_gp" }]
                    : goals.filter(
                        (goal) => goal.kind !== "wilderness_loss_gp",
                      ),
                )
              }
            />
            Wilderness loss if PK’d (GP)
          </label>
          <p>
            Include estimated loss as a tradeoff objective for a fixed trip.
          </p>
          {trip && (
            <label className="check">
              <input
                type="checkbox"
                checked={!capped}
                onChange={(event) =>
                  change({ wildernessLimitLoss: !event.target.checked })
                }
              />
              No loss cap
            </label>
          )}
          <div className="wilderness-inputs">
            {capped && (
              <div>
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
              </div>
            )}
            {(trip || wildernessMayUseMagic(draft.roles)) && (
              <div>
                <label>
                  {trip
                    ? "Attacks per combat setup"
                    : "Casts to pack per Magic setup"}
                  <input
                    inputMode="numeric"
                    data-run-on-enter
                    value={attacks}
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
                  {trip
                    ? "Ammo quantities use expected recovery. Your stack can run out earlier."
                    : "The optimizer packs loose runes after accounting for runes supplied by your staff."}
                </p>
              </div>
            )}
          </div>
          <p aria-label="Applied Wilderness settings">
            {capped
              ? errors.wildernessRiskBudget
                ? "Correct the loss cap"
                : `${Number(parseGp(draft.wildernessRiskBudget ?? "0")).toLocaleString()} GP loss cap`
              : "Uncapped loss"}
            {trip &&
              !errors.wildernessSpellCasts &&
              ` · ${Number(attacks).toLocaleString()} attacks per setup`}
          </p>
          <label>
            Wilderness depth
            <select
              value={wilderness.depth}
              onChange={(event) =>
                change({
                  wilderness: {
                    ...wilderness,
                    depth:
                      event.target.value === "level_1_20"
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
          <label className="check">
            <input
              type="checkbox"
              checked={wilderness.skulled}
              onChange={(event) =>
                change({
                  wilderness: { ...wilderness, skulled: event.target.checked },
                })
              }
            />
            Skulled at death
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={wilderness.protect_item}
              aria-describedby="wilderness-protect-help"
              onChange={(event) =>
                change({
                  wilderness: {
                    ...wilderness,
                    protect_item: event.target.checked,
                  },
                })
              }
            />
            Assume Protect Item is active at death
          </label>
          <p id="wilderness-protect-help">
            Protect Item requires level 25 Prayer.
          </p>
          <p>
            Estimates loss for worn gear, switches, and recommended ammunition,
            charges, and runes on a standard Wilderness PvP death. Extra
            inventory can change what you lose or protect.
          </p>
        </>
      )}
    </fieldset>
  );
}
