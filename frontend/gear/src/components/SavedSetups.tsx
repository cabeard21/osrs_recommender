import { useId, useState } from "react";
import type { Draft, Workspace } from "../api/contracts";
import { sameValue } from "../api/runtime";
import {
  MAX_SETUP_NAME_LENGTH,
  defaultDraft,
  deleteSetup,
  readSavedSetups,
  saveSetup,
  type SavedSetup,
} from "../state/savedSetups";

type Props = {
  draft: Draft;
  mode: Workspace;
  edit: (draft: Draft) => void;
};

/** What the last action changed, so it can be undone. */
type LastAction =
  | { kind: "replaced"; message: string; before: Draft; after: Draft }
  | { kind: "deleted"; message: string; setup: SavedSetup }
  | { kind: "saved"; message: string };

export function SavedSetups({ draft, mode, edit }: Props) {
  const id = useId();
  const [setups, setSetups] = useState(() => readSavedSetups());
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [last, setLast] = useState<LastAction | null>(null);
  const forMode = setups.filter((setup) => setup.mode === mode);
  const chosen = forMode.find((setup) => setup.name === selected);
  const isDefault = sameValue(draft, defaultDraft(mode));
  // Loading or resetting can be undone only until the draft changes again.
  const canUndo =
    last?.kind === "deleted" ||
    (last?.kind === "replaced" && sameValue(last.after, draft));

  const replaceDraft = (next: Draft, message: string) => {
    setError("");
    setLast({ kind: "replaced", message, before: draft, after: next });
    edit(next);
  };
  const save = () => {
    const trimmed = name.trim();
    const exists = forMode.some(
      (setup) => setup.name.toLowerCase() === trimmed.toLowerCase(),
    );
    try {
      setSetups(saveSetup(trimmed, mode, draft));
      setSelected(trimmed);
      setName("");
      setError("");
      setLast({
        kind: "saved",
        message: `${exists ? "Updated" : "Saved"} “${trimmed}”.`,
      });
    } catch (problem) {
      setError((problem as Error).message);
    }
  };
  const remove = () => {
    if (!chosen) return;
    setSetups(deleteSetup(chosen.name, mode));
    setSelected("");
    setError("");
    setLast({
      kind: "deleted",
      message: `Deleted “${chosen.name}”.`,
      setup: chosen,
    });
  };
  const undo = () => {
    if (last?.kind === "replaced") edit(last.before);
    if (last?.kind === "deleted") {
      try {
        setSetups(saveSetup(last.setup.name, mode, last.setup.draft));
        setSelected(last.setup.name);
      } catch (problem) {
        setError((problem as Error).message);
      }
    }
    setLast(null);
  };
  const showStatus = last && (last.kind === "saved" || canUndo) ? last : null;

  return (
    <details className="saved-setups">
      <summary>Saved setups</summary>
      <div className="raised">
        {forMode.length > 0 && (
          <div className="saved-setups-row">
            <label htmlFor={`${id}-pick`}>Saved setups</label>
            <select
              id={`${id}-pick`}
              value={chosen ? selected : ""}
              onChange={(event) => setSelected(event.target.value)}
            >
              <option value="">Choose a setup</option>
              {forMode.map((setup) => (
                <option key={setup.name} value={setup.name}>
                  {setup.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!chosen}
              onClick={() =>
                chosen &&
                replaceDraft(
                  structuredClone(chosen.draft),
                  `Loaded “${chosen.name}”.`,
                )
              }
            >
              Load setup
            </button>
            <button type="button" disabled={!chosen} onClick={remove}>
              Delete setup
            </button>
          </div>
        )}
        <div className="saved-setups-row">
          <label htmlFor={`${id}-name`}>Save current setup as</label>
          <input
            id={`${id}-name`}
            value={name}
            maxLength={MAX_SETUP_NAME_LENGTH}
            placeholder="e.g. Vorkath ranged"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && name.trim()) {
                event.preventDefault();
                save();
              }
            }}
          />
          <button type="button" disabled={!name.trim()} onClick={save}>
            Save setup
          </button>
          <button
            type="button"
            disabled={isDefault}
            onClick={() =>
              replaceDraft(
                defaultDraft(mode),
                "Reset every setting to default.",
              )
            }
          >
            Reset all
          </button>
        </div>
        {error && <p role="alert">{error}</p>}
        {showStatus && (
          <p role="status" className="notice">
            {showStatus.message}
            {showStatus.kind !== "saved" && (
              <>
                {" "}
                <button type="button" onClick={undo}>
                  Undo
                </button>
              </>
            )}
          </p>
        )}
      </div>
    </details>
  );
}
