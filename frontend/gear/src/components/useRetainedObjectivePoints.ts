import { useState } from "react";

export function useRetainedObjectivePoints<Point extends { id: string }>(
  scope: string,
  selected?: Point,
): Point[] {
  const [state, setState] = useState<{ scope: string; points: Point[] }>({
    scope,
    points: [],
  });
  const previous = state.scope === scope ? state.points : [];
  const points =
    selected && !previous.some((point) => point.id === selected.id)
      ? [...previous, selected]
      : previous;
  // Chart points and comparison rows share the same lifetime, independent of
  // the active highlight. A new run or frontier starts a fresh comparison.
  if (state.scope !== scope || points !== previous) setState({ scope, points });
  return points;
}
