import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { Draft } from "../api/contracts";
import { defaultWilderness } from "../api/wilderness";
import { ConfigurationPanel } from "../components/ConfigurationPanel";
import { FixtureGearClient } from "../fixtures/client";
import { GearProvider, useGear } from "../state/GearProvider";
import { saveObjectivePreset } from "../state/objectivePresets";
import { saveSetup } from "../state/savedSetups";
import { newDraft, normalize } from "../state/scenario";

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
}

const draft = () =>
  JSON.parse(screen.getByTestId("draft").textContent!) as Draft;
const lossObjective = "Wilderness loss if PK’d (GP)";

it("orders the core controls and keeps saved setup management collapsed", () => {
  setup();
  const panel = screen.getByRole("region", {
    name: /optimization parameters/i,
  });
  const headings = within(panel).getAllByRole("heading", { level: 3 });
  expect(headings.map((heading) => heading.textContent)).toEqual([
    "Encounter target",
    "Combat discipline",
    "Budget and access",
    "Optimize for",
  ]);
  expect(screen.getByLabelText("Save current setup as")).not.toBeVisible();
  fireEvent.click(screen.getByText("Saved setups", { selector: "summary" }));
  expect(screen.getByLabelText("Save current setup as")).toBeVisible();
});

it("summarizes Multi targets and normalized shares with role-specific errors", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Enter Multi" }));
  const first = within(screen.getByRole("group", { name: "Configuration 1" }));
  const second = within(screen.getByRole("group", { name: "Configuration 2" }));
  fireEvent.change(first.getByLabelText("Role target name"), {
    target: { value: "Armoured target" },
  });
  const weight = first.getByLabelText("Active-time weight");
  fireEvent.change(weight, { target: { value: "3" } });
  expect(
    screen.getByText(/Configuration 1.*Armoured target.*75% active time/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Configuration 2.*25% active time/),
  ).toBeInTheDocument();
  fireEvent.change(weight, { target: { value: "-1" } });
  expect(weight).toHaveAccessibleDescription(/weight.*0.*1,000,000/i);
  expect(weight).toHaveAttribute("aria-invalid", "true");
  expect(second.getByLabelText("Active-time weight")).not.toHaveAttribute(
    "aria-invalid",
  );
  const duration = second.getByLabelText(
    "Fight duration for status damage (seconds)",
  );
  fireEvent.change(duration, { target: { value: "" } });
  expect(duration).toHaveAccessibleDescription(/1 to 3600/);
  const defence = second.getByLabelText("Role target defence");
  fireEvent.change(defence, { target: { value: "10001" } });
  expect(defence).toHaveAccessibleDescription(
    /Configuration 2 target defence level.*0 to 10000/,
  );
});

it("marks current hitpoints when they exceed the configured base", () => {
  setup();
  fireEvent.click(
    screen.getByText("Target hitpoints", { selector: "summary" }),
  );
  fireEvent.change(screen.getByLabelText("Target base hitpoints"), {
    target: { value: "30" },
  });
  const current = screen.getByLabelText("Target current hitpoints");
  fireEvent.change(current, { target: { value: "31" } });
  expect(current).toHaveAccessibleDescription(
    "Target current hitpoints cannot exceed base hitpoints.",
  );
  expect(() => normalize(draft(), "test")).toThrow(
    "Target current hitpoints cannot exceed base hitpoints.",
  );
  fireEvent.change(current, { target: { value: "30" } });
  expect(current).not.toHaveAttribute("aria-invalid");
  expect(
    normalize(draft(), "test").request.target.definition?.current_hitpoints,
  ).toBe(30);
});

it("keeps the active zero cap when adding the loss objective", () => {
  setup();
  fireEvent.click(screen.getByLabelText("Wilderness"));
  const risk = within(
    screen.getByRole("group", { name: "Wilderness settings" }),
  );
  fireEvent.click(risk.getByLabelText(lossObjective));
  expect(risk.getByLabelText("No loss cap")).not.toBeChecked();
  expect(risk.getByLabelText("Max gear loss if PK’d (GP)")).toHaveValue("0");
  expect(risk.getByLabelText("Attacks per combat setup")).toHaveValue("100");
  expect(normalize(draft(), "test").request.wilderness).toMatchObject({
    max_loss_gp: 0,
    attacks_per_setup: 100,
  });
  fireEvent.click(risk.getByLabelText("No loss cap"));
  expect(normalize(draft(), "test").request.wilderness).not.toHaveProperty(
    "max_loss_gp",
  );
  fireEvent.change(risk.getByLabelText("Attacks per combat setup"), {
    target: { value: "25" },
  });
  fireEvent.click(risk.getByLabelText("Wilderness"));
  fireEvent.click(risk.getByLabelText("Wilderness"));
  fireEvent.click(risk.getByLabelText(lossObjective));
  expect(risk.getByLabelText("No loss cap")).not.toBeChecked();
  expect(risk.getByLabelText("Attacks per combat setup")).toHaveValue("25");
});

it("carries the entered cap through objective preset and custom group selection", () => {
  saveObjectivePreset("Trip plan", [{ kind: "wilderness_loss_gp" }]);
  setup();
  fireEvent.click(screen.getByLabelText("Wilderness"));
  fireEvent.change(screen.getByLabelText("Max gear loss if PK’d (GP)"), {
    target: { value: "25k" },
  });
  fireEvent.click(
    screen.getByText("Tradeoff objectives", { selector: "summary" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Edit objective groups" }),
  );
  fireEvent.click(screen.getByRole("button", { name: `+ ${lossObjective}` }));
  expect(screen.getByLabelText("No loss cap")).not.toBeChecked();
  fireEvent.click(
    screen.getByRole("button", { name: `Remove ${lossObjective}` }),
  );
  const presets = screen.getByText("Objective presets", {
    selector: "summary",
  });
  fireEvent.click(presets);
  fireEvent(presets.closest("details")!, new Event("toggle"));
  fireEvent.click(screen.getByRole("button", { name: "Trip plan" }));
  expect(draft().wildernessLimitLoss).toBe(true);
  expect(normalize(draft(), "test").request.wilderness?.max_loss_gp).toBe(
    25_000,
  );
});

it("loads a saved trip with an explicitly uncapped loss", () => {
  saveSetup("Uncapped trip", "single", {
    ...newDraft(),
    wilderness: defaultWilderness,
    objectives: [{ kind: "wilderness_loss_gp" }],
    wildernessLimitLoss: false,
    wildernessRiskBudget: "15k",
    wildernessSpellCasts: "40",
  });
  setup();
  fireEvent.click(screen.getByText("Saved setups", { selector: "summary" }));
  fireEvent.change(screen.getByLabelText("Saved setups"), {
    target: { value: "Uncapped trip" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load setup" }));
  expect(screen.getByLabelText("No loss cap")).toBeChecked();
  expect(normalize(draft(), "test").request.wilderness).not.toHaveProperty(
    "max_loss_gp",
  );
  expect(screen.getByLabelText("Attacks per combat setup")).toHaveValue("40");
});
