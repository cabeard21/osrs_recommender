import { useEffect, useState } from "react";
import { canonicalObjectives, objectiveValues } from "../api/objectives";
import { riskWithinBudget } from "../api/wilderness";
import type { TradeoffPoint } from "./objectiveTradeoff";

interface Page {
  points: TradeoffPoint[];
  total: number;
  next_cursor: string | null;
}

const PAGE_SIZE = 50;
const FIRST_PAGE = [null];

export async function fetchObjectiveArchive(path: string, signal: AbortSignal) {
  const response = await fetch("/ui-api/gear/optimization-runs/" + path, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (response.status === 410)
    throw new Error(
      "This optimization session has expired. Run optimization again to browse its tradeoffs.",
    );
  if (!response.ok)
    throw new Error(
      "Unable to load objective results (" + response.status + ").",
    );
  return response.json();
}

function validatePage(
  data: Page,
  goalsKey: string,
  lossCap: number | null | undefined,
) {
  if (
    !Array.isArray(data?.points) ||
    !Number.isSafeInteger(data.total) ||
    data.total < 0 ||
    (data.next_cursor !== null && typeof data.next_cursor !== "string")
  )
    throw new Error("Invalid objective result page.");

  const goals = canonicalObjectives(JSON.parse(goalsKey));
  for (const point of data.points) {
    if (
      typeof point?.id !== "string" ||
      !Number.isFinite(point.score) ||
      !Number.isSafeInteger(point.purchase_cost_gp) ||
      point.purchase_cost_gp < 0 ||
      !Number.isSafeInteger(point.maximum_actions) ||
      point.maximum_actions < 0
    )
      throw new Error("Invalid objective result point.");
    const values = objectiveValues(point.objective_values, goals);
    if (
      lossCap !== undefined &&
      (!riskWithinBudget(point.wilderness_loss_gp, lossCap) ||
        (values.wilderness_loss_gp !== undefined &&
          values.wilderness_loss_gp !== point.wilderness_loss_gp))
    )
      throw new Error("Invalid Wilderness risk in objective result.");
  }
  return data;
}

export function useObjectiveArchive(
  runId: string | undefined,
  groupId: string | undefined,
  sort: string,
  direction: "asc" | "desc",
  goalsKey: string,
  lossCap: number | null | undefined,
) {
  const query = new URLSearchParams({
    sort,
    direction,
    limit: String(PAGE_SIZE),
  });
  const scope = JSON.stringify([
    runId,
    groupId,
    sort,
    direction,
    goalsKey,
    lossCap,
  ]);
  const [paging, setPaging] = useState<{
    scope: string;
    cursors: (string | null)[];
  }>({ scope, cursors: FIRST_PAGE });
  const cursors = paging.scope === scope ? paging.cursors : FIRST_PAGE;
  if (paging.scope !== scope) setPaging({ scope, cursors });
  const cursor = cursors.at(-1);
  if (cursor) query.set("cursor", cursor);
  const path =
    runId && groupId
      ? `${encodeURIComponent(runId)}/frontiers/${encodeURIComponent(groupId)}/points?${query}`
      : null;
  const [response, setResponse] = useState<{
    key: string;
    page?: Page;
    error?: string;
  }>();
  const key = JSON.stringify([scope, cursor]);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    fetchObjectiveArchive(path, controller.signal)
      .then((data) => validatePage(data, goalsKey, lossCap))
      .then((page) => {
        if (!controller.signal.aborted) setResponse({ key, page });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setResponse({ key, error: (error as Error).message });
      });
    return () => controller.abort();
  }, [path, key, goalsKey, lossCap]);
  const current = response?.key === key ? response : undefined;
  return {
    page: current?.page,
    error: current?.error,
    loading: path !== null && !current,
    pageNumber: cursors.length,
    offset: (cursors.length - 1) * PAGE_SIZE,
    previous: () => setPaging({ scope, cursors: cursors.slice(0, -1) }),
    next: (nextCursor: string) =>
      setPaging({ scope, cursors: [...cursors, nextCursor] }),
  };
}
