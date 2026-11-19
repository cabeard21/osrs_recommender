import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { ObjectiveBuilder } from "../components/ObjectiveBuilder";
import type { Objective } from "../api/objectives";
import {
  canonicalObjectives,
  objectiveId,
  objectiveValues,
} from "../api/objectives";
import {
  deleteObjectivePreset,
  readObjectivePresets,
  saveObjectivePreset,
} from "../state/objectivePresets";

function Editor() {
  const [goals, setGoals] = useState<Objective[]>([]);
  return (
    <>
      <ObjectiveBuilder objectives={goals} onChange={setGoals} />
      <output aria-label="Objective payload">{JSON.stringify(goals)}</output>
    </>
  );
}
it("builds independent mixed objectives and supports multiple custom groups", async () => {
  const user = userEvent.setup();
  render(<Editor />);
  await user.click(screen.getByRole("checkbox", { name: "stab" }));
  await user.click(screen.getByRole("checkbox", { name: "magic" }));
  await user.click(screen.getByRole("checkbox", { name: "Prayer bonus" }));
  expect(
    JSON.parse(screen.getByLabelText("Objective payload").textContent!),
  ).toHaveLength(2);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Selected defence rolls" }),
    "separate",
  );
  expect(
    JSON.parse(screen.getByLabelText("Objective payload").textContent!),
  ).toHaveLength(3);
  await user.click(
    screen.getByRole("button", { name: "Edit objective groups" }),
  );
  await user.click(screen.getByRole("button", { name: "+ Defence group" }));
  expect(
    screen.getAllByRole("group", { name: "Defence roll group" }),
  ).toHaveLength(3);
  await user.click(
    screen.getByRole("button", { name: "Edit objective groups" }),
  );
  expect(screen.getByLabelText("Objective payload")).toHaveTextContent(
    "prayer_bonus",
  );
});
it("requires explicit replacement of complex custom groups", async () => {
  const user = userEvent.setup();
  render(
    <ObjectiveBuilder
      objectives={[
        {
          kind: "defence_roll",
          styles: ["stab", "magic"],
          aggregation: "minimum",
        },
        {
          kind: "defence_roll",
          styles: ["crush", "ranged"],
          aggregation: "mean",
        },
      ]}
      onChange={() => {}}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "Replace with Quick select" }),
  );
  expect(
    within(
      screen.getByRole("group", { name: "Replace custom objective groups" }),
    ).getByRole("button", { name: "Keep groups" }),
  ).toBeVisible();
});
it("saves, replaces and deletes independent objective presets", () => {
  const goals: Objective[] = [
    { kind: "gp_per_damage" },
    { kind: "prayer_bonus" },
  ];
  expect(saveObjectivePreset("Hybrid", goals, sessionStorage)).toHaveLength(1);
  expect(readObjectivePresets(sessionStorage)[0].objectives).toEqual(goals);
  expect(saveObjectivePreset("HYBRID", [], sessionStorage)).toHaveLength(1);
  expect(readObjectivePresets(sessionStorage)[0].objectives).toEqual([]);
  expect(deleteObjectivePreset("HYBRID", sessionStorage)).toEqual([]);
  expect(() => saveObjectivePreset(" ", goals, sessionStorage)).toThrow();
});
it("supports all 64 functions with no smaller selection cap", () => {
  const styles = ["stab", "slash", "crush", "ranged", "magic"] as const;
  const groups: Objective[] = [];
  for (let mask = 1; mask < 32; mask++)
    for (const aggregation of ["minimum", "mean"] as const)
      groups.push({
        kind: "defence_roll",
        styles: styles.filter((_, i) => mask & (1 << i)),
        aggregation,
      });
  // Canonicalize each group before deduplication, then add the seven other objectives.
  const unique = [
    ...new Map(
      groups.map((g) => {
        const goal = canonicalObjectives([g])[0];
        return [objectiveId(goal), goal];
      }),
    ).values(),
  ];
  expect(
    canonicalObjectives([
      ...unique,
      ...(
        [
          "accuracy",
          "gp_per_damage",
          "wilderness_loss_gp",
          "prayer_bonus",
          "melee_strength_bonus",
          "ranged_strength_bonus",
          "magic_damage_bonus",
        ] as const
      ).map((kind) => ({ kind })),
    ]),
  ).toHaveLength(64);
});
it("edits reductions, removes groups, and applies preset shortcuts", async () => {
  const user = userEvent.setup();
  render(<Editor />);
  await user.click(
    screen.getByRole("button", { name: "Weakest melee defence" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Edit objective groups" }),
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Combine these rolls" }),
    "mean",
  );
  expect(screen.getByLabelText("Objective payload")).toHaveTextContent("mean");
  for (const name of ["stab", "slash", "crush"])
    await user.click(screen.getByRole("checkbox", { name }));
  expect(screen.getByRole("alert")).toHaveTextContent("Choose at least one");
  await user.click(
    screen.getByRole("button", { name: "Remove defence group" }),
  );
  await user.click(screen.getByRole("button", { name: "+ Accuracy" }));
  await user.click(screen.getByRole("button", { name: "Remove Accuracy" }));
  await user.click(
    screen.getByRole("button", { name: "Magic + ranged defence" }),
  );
  await user.click(screen.getByRole("button", { name: "DPS only" }));
  expect(screen.getByLabelText("Objective payload")).toHaveTextContent("[]");
});
it("saves and restores presets through the editor and explains invalid names", async () => {
  localStorage.removeItem("gear.objectivePresets.v1");
  const user = userEvent.setup();
  render(<Editor />);
  await user.click(screen.getByText("Objective presets", { exact: true }));
  await user.click(
    screen.getByRole("button", { name: "Save objective preset" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("preset name");
  await user.type(
    screen.getByRole("textbox", { name: "Preset name" }),
    "My hybrid",
  );
  await user.click(
    screen.getByRole("button", { name: "Magic + ranged defence" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Save objective preset" }),
  );
  await user.click(screen.getByRole("button", { name: "DPS only" }));
  await user.click(screen.getByRole("button", { name: "My hybrid" }));
  expect(screen.getByLabelText("Objective payload")).toHaveTextContent("magic");
  await user.click(
    screen.getByRole("button", { name: "Delete objective preset My hybrid" }),
  );
  expect(
    screen.queryByRole("button", { name: "My hybrid" }),
  ).not.toBeInTheDocument();
});
it("confirms replacing complex groups with Quick select", async () => {
  const user = userEvent.setup();
  render(<Editor />);
  await user.click(
    screen.getByRole("button", { name: "Magic + ranged defence" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Edit objective groups" }),
  );
  await user.click(screen.getByRole("button", { name: "+ Defence group" }));
  await user.click(
    screen.getByRole("button", { name: "Replace with Quick select" }),
  );
  await user.click(screen.getByRole("button", { name: "Replace groups" }));
  expect(screen.getByLabelText("Objective payload")).toHaveTextContent("[]");
  expect(
    screen.getByRole("combobox", { name: "Selected defence rolls" }),
  ).toBeVisible();
});
it("reports invalid stored presets and bounded preset storage", () => {
  sessionStorage.setItem("gear.objectivePresets.v1", "{}");
  expect(() => readObjectivePresets(sessionStorage)).toThrow(/invalid/);
  sessionStorage.setItem("gear.objectivePresets.v1", "[{}]");
  expect(() => readObjectivePresets(sessionStorage)).toThrow(/invalid/);
  sessionStorage.removeItem("gear.objectivePresets.v1");
  for (let i = 0; i < 20; i++)
    saveObjectivePreset("Preset " + i, [], sessionStorage);
  expect(() => saveObjectivePreset("Overflow", [], sessionStorage)).toThrow(
    /20/,
  );
});

it("admits an unpriced DPS winner while requiring priced frontier points", () => {
  const goals = canonicalObjectives([{ kind: "gp_per_damage" }]);
  expect(objectiveValues(undefined, goals, true)).toEqual({
    gp_per_damage: null,
  });
  expect(objectiveValues({ gp_per_damage: null }, goals, true)).toEqual({
    gp_per_damage: null,
  });
  expect(objectiveValues({ gp_per_damage: 0 }, goals)).toEqual({
    gp_per_damage: 0,
  });
  expect(() => objectiveValues({ gp_per_damage: null }, goals)).toThrow();
  expect(() => objectiveValues({ gp_per_damage: -1 }, goals, true)).toThrow();
  expect(() =>
    objectiveValues({}, [...goals, { kind: "accuracy" }], true),
  ).toThrow();
});
