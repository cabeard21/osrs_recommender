import type { Draft, Workspace } from "../api/contracts";
import { newDraft, newRole, upgradeStoredDraft } from "./scenario";

/** A named copy of a draft the player can load again later. */
export interface SavedSetup {
  name: string;
  mode: Workspace;
  savedAt: string;
  draft: Draft;
}

const STORAGE_KEY = "gear.savedSetups.v1";
export const MAX_SAVED_SETUPS = 20;
export const MAX_SETUP_NAME_LENGTH = 60;

function isWorkspace(value: unknown): value is Workspace {
  return value === "single" || value === "multi";
}

/** Saved setups for every mode, newest first. Storage may be unavailable. */
export function readSavedSetups(storage: Storage = localStorage): SavedSetup[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((row: Partial<SavedSetup> | null) => {
      if (
        !row ||
        typeof row.name !== "string" ||
        !row.name.trim() ||
        !isWorkspace(row.mode) ||
        typeof row.savedAt !== "string"
      )
        return [];
      const draft = upgradeStoredDraft(row.draft);
      if (!draft) return [];
      if (row.mode === "single" && draft.roles.length !== 1) return [];
      return [{ name: row.name, mode: row.mode, savedAt: row.savedAt, draft }];
    });
  } catch {
    return [];
  }
}

function writeSavedSetups(setups: SavedSetup[], storage: Storage): boolean {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(setups));
    return true;
  } catch {
    return false;
  }
}

const sameSetup = (a: SavedSetup, name: string, mode: Workspace) =>
  a.mode === mode && a.name.toLowerCase() === name.toLowerCase();

/**
 * Saves a copy of the draft under a name, replacing a setup with the same
 * name in the same mode. Returns the new list, or throws a readable error.
 */
export function saveSetup(
  name: string,
  mode: Workspace,
  draft: Draft,
  storage: Storage = localStorage,
  now: Date = new Date(),
): SavedSetup[] {
  const trimmed = name.trim();
  if (!trimmed) throw new Error("Enter a name for this setup.");
  if (trimmed.length > MAX_SETUP_NAME_LENGTH)
    throw new Error(
      `Setup names can be at most ${MAX_SETUP_NAME_LENGTH} characters.`,
    );
  const others = readSavedSetups(storage).filter(
    (setup) => !sameSetup(setup, trimmed, mode),
  );
  if (others.length >= MAX_SAVED_SETUPS)
    throw new Error(
      `You can keep up to ${MAX_SAVED_SETUPS} saved setups. Delete one first.`,
    );
  const next = [
    {
      name: trimmed,
      mode,
      savedAt: now.toISOString(),
      draft: structuredClone(draft),
    },
    ...others,
  ];
  if (!writeSavedSetups(next, storage))
    throw new Error("This browser blocked saving. Setups cannot be stored.");
  return next;
}

export function deleteSetup(
  name: string,
  mode: Workspace,
  storage: Storage = localStorage,
): SavedSetup[] {
  const next = readSavedSetups(storage).filter(
    (setup) => !sameSetup(setup, name, mode),
  );
  writeSavedSetups(next, storage);
  return next;
}

/** The draft a fresh workspace starts with. Multi-style needs two configurations. */
export function defaultDraft(mode: Workspace): Draft {
  const draft = newDraft();
  if (mode === "single") return draft;
  return {
    ...draft,
    roles: [newRole(1), newRole(2)].map((role) => ({
      ...role,
      combatTarget: {
        name: draft.target,
        defence_level: Number(draft.defence),
        magic_level: 1,
        bonuses: {},
      },
      targetInputs: { defence_level: draft.defence },
    })),
  };
}
