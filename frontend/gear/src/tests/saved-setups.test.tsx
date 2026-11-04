import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import { ConfigurationPanel } from "../components/ConfigurationPanel";
import { FixtureGearClient } from "../fixtures/client";
import { GearProvider, useGear } from "../state/GearProvider";
import {
  MAX_SAVED_SETUPS,
  defaultDraft,
  deleteSetup,
  readSavedSetups,
  saveSetup,
} from "../state/savedSetups";
import { newDraft } from "../state/scenario";
import type { Draft } from "../api/contracts";

beforeEach(() => localStorage.clear());

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

const draft = () =>
  JSON.parse(screen.getByTestId("draft").textContent!) as Draft;

function setup() {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <Harness />
    </GearProvider>,
  );
}

const budget = () => screen.getByLabelText("Additional purchase budget (GP)");

it("saving under an existing name replaces that setup, ignoring case", () => {
  saveSetup("Vorkath", "single", { ...newDraft(), budget: "1m" });
  const list = saveSetup("vorkath", "single", { ...newDraft(), budget: "2m" });
  expect(list).toHaveLength(1);
  expect(readSavedSetups()[0]).toMatchObject({
    name: "vorkath",
    draft: { budget: "2m" },
  });
  saveSetup("vorkath", "multi", defaultDraft("multi"));
  expect(readSavedSetups()).toHaveLength(2);
  expect(deleteSetup("VORKATH", "single")).toHaveLength(1);
});

it("rejects blank names, too many setups, and skips unreadable rows", () => {
  expect(() => saveSetup("  ", "single", newDraft())).toThrow("Enter a name");
  for (let i = 0; i < MAX_SAVED_SETUPS; i++)
    saveSetup(`Setup ${i}`, "single", newDraft());
  expect(() => saveSetup("One more", "single", newDraft())).toThrow(
    "Delete one first",
  );
  localStorage.setItem(
    "gear.savedSetups.v1",
    JSON.stringify([
      { name: "Broken", mode: "single", savedAt: "x", draft: { roles: [] } },
      { name: "", mode: "single", savedAt: "x", draft: newDraft() },
      {
        name: "Good",
        mode: "single",
        savedAt: "2026-11-04T12:00:00.000Z",
        draft: newDraft(),
      },
    ]),
  );
  expect(readSavedSetups().map((setup) => setup.name)).toEqual(["Good"]);
});

it("a fresh Multi-style draft has two configurations", () => {
  expect(defaultDraft("multi").roles).toHaveLength(2);
  expect(defaultDraft("single")).toEqual(newDraft());
});

it("saves, resets, undoes and loads a setup", () => {
  setup();
  expect(screen.getByRole("button", { name: "Reset all" })).toBeDisabled();
  fireEvent.change(budget(), { target: { value: "5m" } });
  fireEvent.change(screen.getByLabelText("Save current setup as"), {
    target: { value: "Main" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save setup" }));
  expect(screen.getByText("Saved “Main”.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Reset all" }));
  expect(draft().budget).toBe("0");
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(draft().budget).toBe("5m");

  fireEvent.change(budget(), { target: { value: "1m" } });
  fireEvent.change(screen.getByLabelText("Saved setups"), {
    target: { value: "Main" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load setup" }));
  expect(draft().budget).toBe("5m");
  expect(screen.getByText(/Loaded “Main”/)).toBeInTheDocument();
});

it("Undo is withdrawn once the loaded setup is edited", () => {
  saveSetup("Main", "single", { ...newDraft(), budget: "5m" });
  setup();
  fireEvent.change(screen.getByLabelText("Saved setups"), {
    target: { value: "Main" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load setup" }));
  fireEvent.change(budget(), { target: { value: "6m" } });
  expect(
    screen.queryByRole("button", { name: "Undo" }),
  ).not.toBeInTheDocument();
});

it("a deleted setup can be restored, and setups are kept per mode", () => {
  saveSetup("Main", "single", newDraft());
  setup();
  fireEvent.change(screen.getByLabelText("Saved setups"), {
    target: { value: "Main" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete setup" }));
  expect(screen.queryByLabelText("Saved setups")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByLabelText("Saved setups")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Enter Multi" }));
  expect(screen.queryByLabelText("Saved setups")).not.toBeInTheDocument();
});
