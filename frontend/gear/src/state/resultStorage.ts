import type { OptimizationReply, Workspace } from "../api/contracts";

const MODES: Workspace[] = ["single", "multi"];
const keyFor = (player: string, mode: Workspace) =>
  `gear-results:${player}:${mode}`;

export interface SavedResult {
  result: OptimizationReply;
  solutionId: string;
  outdated: boolean;
}
export type SavedResults = Partial<Record<Workspace, SavedResult>>;

/** Checks every field the restore reducer dereferences; older shapes are discarded. */
function isSavedResult(value: unknown): value is SavedResult {
  const saved = value as Partial<SavedResult> | null;
  return (
    !!saved &&
    typeof saved.solutionId === "string" &&
    typeof saved.outdated === "boolean" &&
    Array.isArray(saved.result?.solutions) &&
    !!saved.result?.live &&
    typeof saved.result?.scenario?.request?.roles?.[0]?.id === "string"
  );
}

/** Long Thorough runs should survive a reload; a full store only loses that mode's result. */
export function saveResults(
  player: string,
  results: SavedResults,
  storage: Storage,
): void {
  for (const mode of MODES) {
    const saved = results[mode];
    try {
      if (saved) storage.setItem(keyFor(player, mode), JSON.stringify(saved));
      else storage.removeItem(keyFor(player, mode));
    } catch {
      storage.removeItem(keyFor(player, mode));
    }
  }
}

function readResult(
  player: string,
  mode: Workspace,
  storage: Storage,
): SavedResult | null {
  try {
    const parsed: unknown = JSON.parse(
      storage.getItem(keyFor(player, mode)) ?? "null",
    );
    return isSavedResult(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function readResults(player: string, storage: Storage): SavedResults {
  return Object.fromEntries(
    MODES.flatMap((mode) => {
      const saved = readResult(player, mode, storage);
      return saved ? [[mode, saved]] : [];
    }),
  );
}
