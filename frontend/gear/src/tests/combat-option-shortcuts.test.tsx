import { expect, test, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { contextFixture, FixtureGearClient } from "../fixtures/client";
import { newDraft, normalize } from "../state/scenario";
import {
  emptyCombatOptionGroups,
  selectedCombatOptions,
  spellQuickPicks,
} from "../api/combatOptions";
import { CombatOptionsControls } from "../components/CombatOptionsControls";
import { ConfigurationPanel } from "../components/ConfigurationPanel";
import { GearProvider, useGear } from "../state/GearProvider";
import type { GearContext, Role } from "../api/contracts";

const SPELLS = [
  ["wind_strike", true],
  ["fire_strike", true],
  ["wind_bolt", true],
  ["fire_bolt", true],
  ["fire_wave", false],
  ["smoke_rush", true],
  ["ice_rush", true],
  ["ice_burst", false],
  ["iban_blast", true],
] as const;

function context(): GearContext {
  return {
    ...contextFixture,
    source: "live",
    live: {
      capabilities: {
        combat_options: {
          attack_types: ["stab", "slash", "crush", "magic"].map((id) => ({
            id,
            available: true,
          })),
          stances: ["accurate", "aggressive", "defensive", "controlled"].map(
            (id) => ({ id, available: true }),
          ),
          spells: SPELLS.map(([id, available]) => ({
            id,
            available,
            reason: available ? undefined : "Magic level unmet",
          })),
        },
      },
    } as unknown as GearContext["live"],
  };
}

const magicRole = (patch: Partial<Role> = {}): Role => ({
  ...newDraft().roles[0],
  style: "magic",
  ...patch,
});

function renderControls(role: Role) {
  const onChange = vi.fn();
  render(
    <CombatOptionsControls
      role={role}
      context={context()}
      liveMode
      onChange={onChange}
    />,
  );
  return onChange;
}

const lastSpells = (onChange: ReturnType<typeof vi.fn>) => {
  const patch = onChange.mock.calls.at(-1)![0] as Partial<Role>;
  return selectedCombatOptions(magicRole(patch), context())!.spells;
};

test("reports only the groups that apply to the role's disciplines", () => {
  const melee = {
    ...newDraft().roles[0],
    combatOptionDisabled: {
      attack_types: ["stab", "slash", "crush"],
      stances: [],
      spells: [],
    },
  };
  expect(emptyCombatOptionGroups(melee, context())).toEqual(["attack_types"]);
  const magic = magicRole({ combatOptionExplicitlyEmpty: { spells: true } });
  expect(emptyCombatOptionGroups(magic, context())).toEqual(["spells"]);
});

test("blocks a live run when a Combat Options group is empty", () => {
  const draft = newDraft();
  draft.roles[0] = magicRole({ combatOptionExplicitlyEmpty: { spells: true } });
  expect(() =>
    normalize(draft, "fixture-snapshot-01", true, context()),
  ).toThrow(/Configuration 1.*at least one spell/);
});

test("does not block when option optimization is turned off", () => {
  const draft = newDraft();
  draft.roles[0] = magicRole({
    combatOptionOptimization: false,
    combatOptionExplicitlyEmpty: { spells: true },
  });
  expect(() =>
    normalize(draft, "fixture-snapshot-01", true, context()),
  ).not.toThrow();
});

test("marks the empty group invalid so Run can focus it", async () => {
  const user = userEvent.setup();
  renderControls(magicRole({ combatOptionExplicitlyEmpty: { spells: true } }));
  await user.click(screen.getByText("Combat Options"));
  const spells = screen.getByRole("group", {
    name: "Spells and powered attacks",
  });
  expect(
    within(spells).getByRole("checkbox", { name: "wind strike" }),
  ).toHaveAttribute("aria-invalid", "true");
  const stances = screen.getByRole("group", { name: "Stances" });
  expect(
    within(stances).getByRole("checkbox", { name: "accurate" }),
  ).not.toHaveAttribute("aria-invalid");
});

test("None clears every spell in one click", async () => {
  const user = userEvent.setup();
  const onChange = renderControls(magicRole());
  await user.click(screen.getByText("Combat Options"));
  await user.click(
    screen.getByRole("button", {
      name: "Select none of the spells and powered attacks",
    }),
  );
  expect(lastSpells(onChange)).toEqual([]);
  expect(onChange.mock.calls.at(-1)![0].combatOptionExplicitlyEmpty).toEqual(
    expect.objectContaining({ spells: true }),
  );
});

test("spell quick picks select only eligible matching spells", () => {
  const picks = Object.fromEntries(
    spellQuickPicks(magicRole(), context()).map((pick) => [
      pick.label,
      pick.ids,
    ]),
  );
  expect(picks.Standard).toEqual([
    "wind_strike",
    "fire_strike",
    "wind_bolt",
    "fire_bolt",
  ]);
  expect(picks.Ancient).toEqual(["smoke_rush", "ice_rush"]);
  expect(picks["Highest tier"]).toEqual([
    "wind_bolt",
    "fire_bolt",
    "smoke_rush",
    "ice_rush",
  ]);
  expect(picks.Fire).toEqual(["fire_strike", "fire_bolt"]);
  expect(picks.Water).toBeUndefined();
});

test("a quick pick replaces the spell selection", async () => {
  const user = userEvent.setup();
  const onChange = renderControls(magicRole());
  await user.click(screen.getByText("Combat Options"));
  await user.click(
    screen.getByRole("button", { name: "Select only Fire spells" }),
  );
  expect(lastSpells(onChange)).toEqual(["fire_strike", "fire_bolt"]);
});

test("the collapsed header summarizes each group", () => {
  renderControls(
    magicRole({
      combatOptionDisabled: {
        attack_types: [],
        stances: ["defensive"],
        spells: ["wind_strike", "wind_bolt"],
      },
    }),
  );
  expect(screen.getByText("Combat Options").textContent).toBe(
    "Combat Options · All attack types · 1/2 stances · 5/7 spells",
  );
});

function MultiHarness() {
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

test("Multi copies one configuration's target to the others", () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <MultiHarness />
    </GearProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Enter Multi" }));
  const first = screen.getByRole("group", { name: "Configuration 1" });
  const copy = within(first).getByRole("button", {
    name: "Use this target for all configurations",
  });
  expect(copy).toBeDisabled();
  fireEvent.change(within(first).getByLabelText("Role target name"), {
    target: { value: "Armoured target" },
  });
  fireEvent.change(within(first).getByLabelText("Role target defence"), {
    target: { value: "150" },
  });
  expect(copy).toBeEnabled();
  fireEvent.click(copy);
  const roles = JSON.parse(screen.getByTestId("draft").textContent!)
    .roles as Role[];
  expect(roles[1].combatTarget).toEqual(roles[0].combatTarget);
  expect(roles[1].combatTarget?.defence_level).toBe(150);
  expect(roles[1].targetInputs).toEqual(roles[0].targetInputs);
  expect(copy).toBeDisabled();
});
