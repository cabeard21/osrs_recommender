import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { ConfigurationPanel } from "../components/ConfigurationPanel";
import { nextRoleIndex, removeMultiRole } from "../components/multiDraft";
import { GearProvider, useGear } from "../state/GearProvider";
import { newDraft, newRole } from "../state/scenario";
import { FixtureGearClient } from "../fixtures/client";

function Harness() {
  const { dispatch, current } = useGear();
  return (
    <>
      <button onClick={() => dispatch({ type: "navigate", mode: "multi" })}>
        Enter Multi
      </button>
      <ConfigurationPanel />
      <output data-testid="draft">{JSON.stringify(current.draft)}</output>
    </>
  );
}
function setup() {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <Harness />
    </GearProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Enter Multi" }));
}

it("edits independent Multi targets and preserves repeated disciplines", () => {
  setup();
  const first = screen.getByRole("group", { name: "Configuration 1" });
  const second = screen.getByRole("group", { name: "Configuration 2" });
  fireEvent.change(within(first).getByLabelText("Role target name"), {
    target: { value: "Armoured target" },
  });
  fireEvent.change(within(first).getByLabelText("Role target defence"), {
    target: { value: "150" },
  });
  fireEvent.click(within(second).getByRole("button", { name: "melee" }));
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles[0].combatTarget).toMatchObject({
    name: "Armoured target",
    defence_level: 150,
  });
  expect(draft.roles[1].combatTarget?.name).not.toBe("Armoured target");
  expect(draft.roles.map((role: { style: string }) => role.style)).toEqual([
    "melee",
    "melee",
  ]);
});

it("offers directed edges, repeated ordered phases, and optional looping", () => {
  setup();
  fireEvent.click(screen.getByText("Transitions & inventory"));
  fireEvent.change(screen.getByLabelText("Transition topology"), {
    target: { value: "explicit" },
  });
  fireEvent.click(screen.getByLabelText("Configuration 1 → Configuration 2"));
  let draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.transitions).toEqual([["role-1", "role-2"]]);
  fireEvent.change(screen.getByLabelText("Transition topology"), {
    target: { value: "ordered" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add phase" }));
  fireEvent.change(screen.getByLabelText("Phase 3"), {
    target: { value: "role-1" },
  });
  fireEvent.click(screen.getByLabelText("Loop ordered phases"));
  draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.orderedRoles).toEqual(["role-1", "role-2", "role-1"]);
  expect(draft.loop).toBe(true);
});

it("cleans removed role references and reports each correction", () => {
  const draft = {
    ...newDraft(),
    roles: [newRole(1), newRole(2), newRole(3)],
    baseRole: "role-2",
    transitions: [
      ["role-1", "role-2"],
      ["role-3", "role-1"],
    ] as [string, string][],
    orderedRoles: ["role-1", "role-2", "role-1", "role-3", "role-2"],
  };
  const result = removeMultiRole(draft, "role-2");
  expect(result.draft.roles.map((role) => role.id)).toEqual([
    "role-1",
    "role-3",
  ]);
  expect(result.draft.transitions).toEqual([["role-3", "role-1"]]);
  expect(result.draft.orderedRoles).toEqual(["role-1", "role-1", "role-3"]);
  expect(result.draft.baseRole).toBe("role-1");
  expect(result.notice).toContain("1 directed transition");
  expect(result.notice).toContain("2 ordered phase");
  expect(draft.orderedRoles).toHaveLength(5);
});

it("requires utility roles to be removed or reparented before deleting their parent", () => {
  const draft = {
    ...newDraft(),
    roles: [
      newRole(1),
      newRole(2),
      {
        ...newRole(3),
        utility: true,
        parentRole: "role-1",
        locks: { weapon: 4151 },
      },
    ],
  };
  expect(() => removeMultiRole(draft, "role-1")).toThrow("reparent");
});

it("edits global and role locks without conflating their scope", () => {
  setup();
  fireEvent.click(screen.getByText("Draft locks & exclusions"));
  fireEvent.change(screen.getByLabelText("Constraint scope"), {
    target: { value: "global" },
  });
  fireEvent.change(screen.getByLabelText("Physical item ID or empty"), {
    target: { value: "6585" },
  });
  fireEvent.change(screen.getByLabelText("Equipment slot"), {
    target: { value: "neck" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.globalLocks).toEqual({ neck: 6585 });
  expect(draft.roles[0].locks).toEqual({});
});

it("retains incomplete numeric target edits and restores default target values explicitly", () => {
  setup();
  const first = screen.getByRole("group", { name: "Configuration 1" });
  fireEvent.change(within(first).getByLabelText("Role target defence"), {
    target: { value: "" },
  });
  let draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles[0].targetInputs.defence_level).toBe("");
  expect(within(first).getByLabelText("Role target defence")).toHaveValue(null);
  fireEvent.click(within(first).getByText("Target defence details"));
  fireEvent.change(within(first).getByLabelText("magic defence bonus"), {
    target: { value: "45" },
  });
  fireEvent.change(within(first).getByLabelText("ranged light"), {
    target: { value: "30" },
  });
  fireEvent.change(within(first).getByLabelText("Elemental weakness"), {
    target: { value: "fire" },
  });
  fireEvent.change(within(first).getByLabelText("Weakness percent"), {
    target: { value: "50" },
  });
  draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles[0].combatTarget).toMatchObject({
    bonuses: { magic: 45 },
    ranged_light: 30,
    weakness_element: "fire",
    weakness_percent: 50,
  });
  fireEvent.change(within(first).getByLabelText("Role target selection"), {
    target: { value: "custom" },
  });
  draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles[0].targetInputs).toEqual({});
  expect(draft.roles[0].combatTarget).not.toHaveProperty("ranged_light");
});

it("configures unscored utility carriage without presenting ordinary damage controls", () => {
  setup();
  const second = screen.getByRole("group", { name: "Configuration 2" });
  fireEvent.click(
    within(second).getByLabelText("Unscored utility configuration"),
  );
  expect(
    within(second).queryByLabelText("Active-time weight"),
  ).not.toBeInTheDocument();
  expect(
    within(second).getByText(/No special-attack damage/),
  ).toBeInTheDocument();
  fireEvent.change(
    within(second).getByLabelText("Utility weapon physical ID"),
    { target: { value: "861" } },
  );
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles[1]).toMatchObject({
    utility: true,
    parentRole: "role-1",
    locks: { weapon: 861 },
  });
  expect(
    within(
      screen.getByRole("group", { name: "Configuration 1" }),
    ).getByLabelText("Unscored utility configuration"),
  ).toBeDisabled();
});

it("reports removal cleanup, retains two configurations, and avoids role ID collisions", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Add configuration" }));
  fireEvent.click(screen.getByText("Transitions & inventory"));
  fireEvent.change(screen.getByLabelText("Transition topology"), {
    target: { value: "ordered" },
  });
  const third = screen.getByRole("group", { name: "Configuration 3" });
  fireEvent.click(
    within(third).getByRole("button", { name: "Remove configuration" }),
  );
  expect(screen.getByText(/^Removed Configuration 3:/)).toHaveTextContent(
    "1 ordered phase(s) removed",
  );
  expect(
    screen
      .getAllByRole("button", { name: "Remove configuration" })
      .every((button) => button.hasAttribute("disabled")),
  ).toBe(true);
  const draft = {
    ...newDraft(),
    roles: [{ ...newRole(1), id: "custom" }, newRole(2), newRole(1)],
  };
  expect(nextRoleIndex(draft)).toBe(3);
  expect(() => removeMultiRole(newDraft(), "role-1")).toThrow("at least two");
});

it("validates lock IDs and supports empty role locks and global unlock", () => {
  setup();
  fireEvent.click(screen.getByText("Draft locks & exclusions"));
  const input = screen.getByLabelText("Physical item ID or empty");
  fireEvent.change(input, { target: { value: "-7" } });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "positive physical item ID",
  );
  fireEvent.change(input, { target: { value: "empty" } });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  fireEvent.click(screen.getByRole("button", { name: "Unlock global weapon" }));
  fireEvent.change(screen.getByLabelText("Constraint scope"), {
    target: { value: "role-2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.globalLocks).toEqual({});
  expect(draft.roles[1].locks).toEqual({ weapon: null });
});

it("lets users reparent utility dependencies before removing an ordinary configuration", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Add configuration" }));
  const third = screen.getByRole("group", { name: "Configuration 3" });
  fireEvent.click(
    within(third).getByLabelText("Unscored utility configuration"),
  );
  fireEvent.click(
    within(screen.getByRole("group", { name: "Configuration 1" })).getByRole(
      "button",
      { name: "Remove configuration" },
    ),
  );
  expect(
    screen.getByText(
      "Remove or reparent dependent utility configurations first.",
    ),
  ).toBeInTheDocument();
  fireEvent.change(within(third).getByLabelText("Parent configuration"), {
    target: { value: "role-2" },
  });
  fireEvent.click(
    within(screen.getByRole("group", { name: "Configuration 1" })).getByRole(
      "button",
      { name: "Remove configuration" },
    ),
  );
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles.map((role: { id: string }) => role.id)).toEqual([
    "role-2",
    "role-3",
  ]);
  expect(draft.roles[1].parentRole).toBe("role-2");
});

it("updates directed constraints, phases, and inventory reservations independently", () => {
  setup();
  fireEvent.click(screen.getByText("Transitions & inventory"));
  fireEvent.change(screen.getByLabelText("Base configuration"), {
    target: { value: "role-2" },
  });
  fireEvent.change(screen.getByLabelText("Maximum equipment actions"), {
    target: { value: "3" },
  });
  fireEvent.change(screen.getByLabelText("Reserved supply slots"), {
    target: { value: "20" },
  });
  fireEvent.change(screen.getByLabelText("Transition topology"), {
    target: { value: "explicit" },
  });
  const edge = screen.getByLabelText("Configuration 1 → Configuration 2");
  fireEvent.click(edge);
  fireEvent.click(edge);
  fireEvent.change(screen.getByLabelText("Transition topology"), {
    target: { value: "ordered" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add phase" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove phase 2" }));
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft).toMatchObject({
    baseRole: "role-2",
    maxActions: "3",
    supplies: "20",
    transitions: [],
    orderedRoles: ["role-1", "role-2"],
  });
});

it("configures a weighted hypothetical Multi scenario with independent combat styles", () => {
  setup();
  const first = screen.getByRole("group", { name: "Configuration 1" });
  const second = screen.getByRole("group", { name: "Configuration 2" });
  fireEvent.change(within(first).getByLabelText("Name"), {
    target: { value: "Slash phase" },
  });
  fireEvent.click(within(first).getByText("Combat Options"));
  fireEvent.click(
    within(first).getByRole("checkbox", {
      name: "Optimize attack type, stance and spell with equipment",
    }),
  );
  fireEvent.change(within(first).getByLabelText("Melee attack type"), {
    target: { value: "stab" },
  });
  fireEvent.change(within(first).getByLabelText("Attack stance"), {
    target: { value: "aggressive" },
  });
  fireEvent.change(within(first).getByLabelText("Active-time weight"), {
    target: { value: "2.5" },
  });
  fireEvent.click(within(second).getByRole("button", { name: "magic" }));
  fireEvent.click(within(second).getByText("Combat Options"));
  fireEvent.click(
    within(second).getByRole("checkbox", {
      name: "Optimize attack type, stance and spell with equipment",
    }),
  );
  fireEvent.change(within(second).getByLabelText("Spell"), {
    target: { value: "fire_wave" },
  });
  fireEvent.change(screen.getByLabelText("Equipment access"), {
    target: { value: "future" },
  });
  fireEvent.click(screen.getByText("⚗ What-if assumptions"));
  fireEvent.change(screen.getByLabelText("Assumed Attack level"), {
    target: { value: "99" },
  });
  fireEvent.click(screen.getByLabelText("Assume demo quest complete"));
  fireEvent.change(screen.getByLabelText("Assumed acquired item IDs"), {
    target: { value: "6585" },
  });
  fireEvent.change(screen.getByLabelText("Additional purchase budget (GP)"), {
    target: { value: "10000" },
  });
  const draft = JSON.parse(screen.getByTestId("draft").textContent!);
  expect(draft.roles[0]).toMatchObject({
    name: "Slash phase",
    attackType: "stab",
    stance: "aggressive",
    combatOptionOptimization: false,
    weight: "2.5",
  });
  expect(draft.roles[1]).toMatchObject({
    style: "magic",
    spell: "fire_wave",
    combatOptionOptimization: false,
  });
  expect(draft).toMatchObject({
    mode: "future",
    budget: "10000",
    assumptions: { attack: "99", quest: true, acquired: "6585" },
  });
});

it("Auto is opt-in, preserves manual settings, and follows the draft into Multi", () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <Harness />
    </GearProvider>,
  );
  expect(screen.getByRole("button", { name: "Auto" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  fireEvent.click(screen.getByRole("button", { name: "Auto" }));
  expect(
    JSON.parse(screen.getByTestId("draft").textContent!).roles[0]
      .allowedDisciplines,
  ).toEqual(["melee", "ranged", "magic"]);
  fireEvent.click(screen.getByRole("checkbox", { name: "magic" }));
  fireEvent.click(screen.getByRole("button", { name: "melee" }));
  expect(
    JSON.parse(screen.getByTestId("draft").textContent!).roles[0]
      .autoDiscipline,
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Auto" }));
  expect(screen.getByRole("checkbox", { name: "magic" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Enter Multi" }));
  expect(screen.getAllByRole("button", { name: "Auto" })).toHaveLength(2);
  const roles = JSON.parse(screen.getByTestId("draft").textContent!).roles;
  expect(roles[0].autoDiscipline).toBe(true);
  expect(roles[0].allowedDisciplines).toEqual(["melee", "ranged"]);
  expect(roles[1].autoDiscipline).not.toBe(true);
});

it("sets independent Auto allowlists and reports the joint combination count", () => {
  setup();
  const first = within(screen.getByRole("group", { name: "Configuration 1" }));
  const second = within(screen.getByRole("group", { name: "Configuration 2" }));
  fireEvent.click(first.getByRole("button", { name: "Auto" }));
  fireEvent.click(first.getByRole("checkbox", { name: "magic" }));
  fireEvent.click(second.getByRole("button", { name: "Auto" }));
  expect(
    screen.getByLabelText("Joint discipline search effort"),
  ).toHaveTextContent("6 discipline combinations");
  expect(
    screen.getByLabelText("Joint discipline search effort"),
  ).toHaveTextContent("Potion optimization adds searches");
  const roles = JSON.parse(screen.getByTestId("draft").textContent!).roles;
  expect(roles[0].allowedDisciplines).toEqual(["melee", "ranged"]);
  expect(roles[1].allowedDisciplines).toEqual(["melee", "ranged", "magic"]);
});

it("clears Auto when converting a configuration to unscored utility", () => {
  setup();
  const second = within(screen.getByRole("group", { name: "Configuration 2" }));
  fireEvent.click(
    second.getByRole("checkbox", {
      name: "Optimize attack type, stance and spell with equipment",
    }),
  );
  fireEvent.click(second.getByRole("button", { name: "Auto" }));
  fireEvent.click(
    second.getByRole("checkbox", { name: "Unscored utility configuration" }),
  );
  const role = JSON.parse(screen.getByTestId("draft").textContent!).roles[1];
  expect(role).toMatchObject({
    utility: true,
    autoDiscipline: false,
    combatOptionOptimization: false,
    parentRole: "role-1",
  });
  expect(role.allowedDisciplines).toBeUndefined();
  expect(
    second.queryByRole("button", { name: "Auto" }),
  ).not.toBeInTheDocument();
  const first = within(screen.getByRole("group", { name: "Configuration 1" }));
  fireEvent.click(first.getByRole("button", { name: "Auto" }));
  expect(
    JSON.parse(screen.getByTestId("draft").textContent!).roles[0]
      .autoDiscipline,
  ).toBe(true);
});
