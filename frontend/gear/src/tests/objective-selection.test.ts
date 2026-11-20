import { expect, it } from "vitest";
import type { ObjectiveFrontierGroup } from "../api/contracts";
import {
  isDisciplineSolution,
  selectedObjectiveGroup,
} from "../state/resultSelection";

it("keeps a selected scoped objective point in its Auto discipline tab", () => {
  expect(
    isDisciplineSolution("frontier-discipline-melee-2-shared-setup", "melee"),
  ).toBe(true);
  expect(
    isDisciplineSolution("frontier-discipline-ranged-2-shared-setup", "melee"),
  ).toBe(false);
  expect(isDisciplineSolution("discipline-melee-best-found", "melee")).toBe(
    true,
  );
  expect(isDisciplineSolution("frontier-global-2-shared-setup", "melee")).toBe(
    false,
  );
});

it("restores an unsampled point under its own cap when the physical setup appears in several groups", () => {
  const groups: ObjectiveFrontierGroup[] = [0, 1, null].map((cap, index) => ({
    id: `frontier-global-${index}`,
    swap_limit: cap,
    baseline_dps: 5,
    sampled: true,
    points: [],
  }));
  expect(
    selectedObjectiveGroup(groups, "frontier-global-1-shared-setup")
      ?.swap_limit,
  ).toBe(1);
  expect(
    selectedObjectiveGroup(groups, "frontier-global-2-shared-setup")
      ?.swap_limit,
  ).toBe(null);
  expect(
    selectedObjectiveGroup(groups, "frontier-other-run-shared-setup"),
  ).toBeUndefined();
});
