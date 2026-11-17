import { useState, type ComponentProps } from "react";
import { ObjectiveScatter } from "./ObjectiveScatter";

type ScatterProps = ComponentProps<typeof ObjectiveScatter>;
type Point = ScatterProps["points"][number];

export function ObjectiveFrontierChart({
  points,
  selected,
  ...props
}: ScatterProps & { selected?: Point }) {
  const [retained, setRetained] = useState<Point[]>([]);
  // Keep configurations added through selection so changing the highlight cannot
  // remove a point and rescale the chart. The parent keys this by frontier scope.
  const additions =
    selected &&
    !points.some((point) => point.id === selected.id) &&
    !retained.some((point) => point.id === selected.id)
      ? [...retained, selected]
      : retained;
  if (additions !== retained) setRetained(additions);
  return (
    <ObjectiveScatter
      {...props}
      points={[
        ...points,
        ...additions.filter((point) => !points.some((p) => p.id === point.id)),
      ]}
    />
  );
}
