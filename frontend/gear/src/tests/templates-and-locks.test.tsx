import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { ConfigurationPanel } from "../components/ConfigurationPanel";
import { GearProvider, useGear } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import type { Draft } from "../api/contracts";

function Harness() {
  const { dispatch, current, edit } = useGear();
  return (
    <>
      <button onClick={() => dispatch({ type: "navigate", mode: "multi" })}>
        Enter Multi
      </button>
      <button
        onClick={() => edit({ ...current.draft, exclusions: [4151, 6585] })}
      >
        Seed exclusions
      </button>
      <ConfigurationPanel />
      <output data-testid="draft">{JSON.stringify(current.draft)}</output>
    </>
  );
}

const draft = () =>
  JSON.parse(screen.getByTestId("draft").textContent!) as Draft;

function setup(multi = false) {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <Harness />
    </GearProvider>,
  );
  if (multi)
    fireEvent.click(screen.getByRole("button", { name: "Enter Multi" }));
}

it("a template replaces the configurations and can be undone", () => {
  setup(true);
  fireEvent.change(
    within(
      screen.getByRole("group", { name: "Configuration 1" }),
    ).getByLabelText("Role target defence"),
    { target: { value: "120" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Tribrid" }));
  const roles = draft().roles;
  expect(roles.map((role) => [role.name, role.style, role.stance])).toEqual([
    ["Melee", "melee", "accurate"],
    ["Ranged", "ranged", "rapid"],
    ["Magic", "magic", "accurate"],
  ]);
  expect(roles.every((role) => role.combatTarget?.defence_level === 120)).toBe(
    true,
  );
  expect(draft().baseRole).toBe(roles[0].id);
  expect(
    screen.getByText(/Applied the Tribrid template/).closest("[role=status]"),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Undo template" }));
  expect(draft().roles.map((role) => role.name)).toEqual([
    "Configuration 1",
    "Configuration 2",
  ]);
});

it("the spec weapon template adds a utility configuration on the main one", () => {
  setup(true);
  fireEvent.click(screen.getByRole("button", { name: "Main + spec weapon" }));
  const [main, spec] = draft().roles;
  expect(main.utility).toBeFalsy();
  expect(spec).toEqual(
    expect.objectContaining({ utility: true, parentRole: main.id }),
  );
});

it("single-style can lock a slot before running and clear all locks", () => {
  setup();
  fireEvent.click(screen.getByText("Draft locks & exclusions"));
  expect(screen.queryByLabelText("Constraint scope")).not.toBeInTheDocument();
  expect(screen.getByText("No locks or exclusions yet.")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Physical item ID or empty"), {
    target: { value: "4151" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  fireEvent.change(screen.getByLabelText("Equipment slot"), {
    target: { value: "head" },
  });
  fireEvent.change(screen.getByLabelText("Physical item ID or empty"), {
    target: { value: "empty" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  expect(draft().roles[0].locks).toEqual({ weapon: 4151, head: null });
  fireEvent.click(screen.getByRole("button", { name: "Clear all locks" }));
  expect(draft().roles[0].locks).toEqual({});
  expect(
    screen.queryByRole("button", { name: "Clear all locks" }),
  ).not.toBeInTheDocument();
});

it("clears every exclusion at once", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Seed exclusions" }));
  fireEvent.click(screen.getByText("Draft locks & exclusions"));
  fireEvent.click(screen.getByRole("button", { name: "Clear all exclusions" }));
  expect(draft().exclusions).toEqual([]);
});

it("multi-style clear all also removes global locks", () => {
  setup(true);
  fireEvent.click(screen.getByText("Draft locks & exclusions"));
  fireEvent.change(screen.getByLabelText("Physical item ID or empty"), {
    target: { value: "4151" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set equipment lock" }));
  expect(draft().globalLocks).toEqual({ weapon: 4151 });
  fireEvent.click(screen.getByRole("button", { name: "Clear all locks" }));
  expect(draft().globalLocks).toEqual({});
});
