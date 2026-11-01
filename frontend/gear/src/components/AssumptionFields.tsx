import { useState } from "react";
import { slots, type Draft, type Slot } from "../api/contracts";
import type { DraftFieldErrors } from "../state/scenario";
import { FieldError, fieldProps } from "./FieldError";
import { ItemSearch } from "./ItemSearch";

export function AssumptionFields({
  draft,
  liveMode,
  errors,
  change,
}: {
  draft: Draft;
  liveMode: boolean;
  errors: DraftFieldErrors;
  change: (patch: Partial<Draft>) => void;
}) {
  const [searchSlot, setSearchSlot] = useState<Slot>("weapon");
  const assume = (patch: Partial<Draft["assumptions"]>) =>
    change({ assumptions: { ...draft.assumptions, ...patch } });
  return (
    <details>
      <summary>⚗ What-if assumptions</summary>
      <details className="control-help">
        <summary>About what-if assumptions</summary>
        <p>
          Explicit request-local hypotheses. Select hypothetical access to apply
          them; no account changes.
        </p>
      </details>
      <label>
        Assumed Attack level
        <input
          type="number"
          min="1"
          max="99"
          value={draft.assumptions.attack}
          {...fieldProps("attack", errors.attack)}
          onChange={(e) => assume({ attack: e.target.value })}
        />
      </label>
      <FieldError id="attack" message={errors.attack} />
      {!liveMode && (
        <label className="check">
          <input
            type="checkbox"
            checked={draft.assumptions.quest}
            onChange={(e) => assume({ quest: e.target.checked })}
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
              {...fieldProps("skills", errors.skillLevels)}
              onChange={(e) => assume({ skillLevels: e.target.value })}
            />
          </label>
          <FieldError id="skills" message={errors.skillLevels} />
          <label>
            Assumed completed quest IDs
            <input
              placeholder="monkey_madness_i"
              value={draft.assumptions.completedQuests ?? ""}
              onChange={(e) => assume({ completedQuests: e.target.value })}
            />
          </label>
          <details className="control-help">
            <summary>About assumed skills and quests</summary>
            <p>
              Use canonical quest IDs separated by commas. Skills and quests are
              checked when you run.
            </p>
          </details>
          <label>
            Item slot to search
            <select
              value={searchSlot}
              onChange={(e) => setSearchSlot(e.target.value as Slot)}
            >
              {slots.map((slot) => (
                <option key={slot}>{slot}</option>
              ))}
            </select>
          </label>
          <ItemSearch
            label="Find item to assume"
            slot={searchSlot}
            onPick={(item) =>
              assume({
                acquired: [draft.assumptions.acquired.trim(), String(item.id)]
                  .filter(Boolean)
                  .join(", "),
              })
            }
          />
        </>
      )}
      <label>
        Assumed acquired item IDs
        <input
          placeholder="4151, 6585"
          value={draft.assumptions.acquired}
          {...fieldProps("acquired", errors.acquired)}
          onChange={(e) => assume({ acquired: e.target.value })}
        />
      </label>
      <FieldError id="acquired" message={errors.acquired} />
    </details>
  );
}
