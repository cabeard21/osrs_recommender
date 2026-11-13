import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import type { CombatPerformance } from "../api/contracts";
import { CombatOptionSummary } from "../components/CombatOptionSummary";

const role = {
  style: "magic" as const,
  attackType: "slash" as const,
  stance: "accurate",
  spell: "earth_wave",
};
const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 27,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
  elemental_weakness: {
    element: "earth",
    percent: 35,
    applied: true,
    reason: null,
    max_hit_bonus: 7,
    attack_roll_bonus: 100,
  },
};

test("explains the amulet base bonus separately from weakness", () => {
  render(
    <CombatOptionSummary
      role={role}
      weapon="Mystic staff"
      performance={{
        ...performance,
        elemental_amulet_bonus: {
          item_id: 34419,
          element: "earth",
          base_max_hit_bonus: 2,
        },
      }}
    />,
  );
  expect(screen.getByLabelText("Elemental amulet effect")).toHaveTextContent(
    "+2 base max hit before damage and weakness bonuses",
  );
});

test("shows the actual weakness bonuses computed by Python", () => {
  render(
    <CombatOptionSummary
      role={role}
      weapon="Mystic staff"
      performance={performance}
    />,
  );
  expect(screen.getByText(/Earth weakness 35% applied/)).toHaveTextContent(
    "+7 max hit",
  );
});

test("discloses omitted bonuses for supported base-stat performance", () => {
  const omission = "Obsidian set bonus is omitted; ordinary base stats only.";
  render(
    <CombatOptionSummary
      role={role}
      weapon="Obsidian staff"
      performance={{ ...performance, limitations: [omission] }}
    />,
  );
  expect(screen.getByText("Combat model limitations")).toBeInTheDocument();
  expect(screen.getByText(omission)).toBeInTheDocument();
});

test("explains why a target weakness did not apply", () => {
  render(
    <CombatOptionSummary
      role={role}
      weapon="Powered staff"
      performance={{
        ...performance,
        elemental_weakness: {
          ...performance.elemental_weakness!,
          applied: false,
          reason: "Powered attacks do not receive elemental weakness bonuses.",
          max_hit_bonus: 0,
          attack_roll_bonus: 0,
        },
      }}
    />,
  );
  expect(screen.getByText(/Powered attacks do not receive/)).toBeVisible();
  expect(screen.queryByText(/\+7 max hit/)).not.toBeInTheDocument();
});

test("older results without explanation metadata remain readable", () => {
  render(<CombatOptionSummary role={role} weapon="Mystic staff" />);
  expect(
    screen.getByLabelText("Selected combat configuration"),
  ).toHaveTextContent("earth wave");
  expect(screen.queryByText(/weakness/i)).not.toBeInTheDocument();
});

test("targets without an element use the server's non-application reason", () => {
  render(
    <CombatOptionSummary
      role={role}
      weapon="Mystic staff"
      performance={{
        ...performance,
        elemental_weakness: {
          ...performance.elemental_weakness!,
          element: null,
          percent: 0,
          applied: false,
          reason: "The target has no elemental weakness.",
          max_hit_bonus: 0,
          attack_roll_bonus: 0,
        },
      }}
    />,
  );
  expect(screen.getByLabelText("Elemental weakness effect")).toHaveTextContent(
    "No elemental weakness",
  );
});

test("missing selected attack is reported without inferring an explanation", () => {
  render(
    <CombatOptionSummary
      role={{
        ...role,
        combatOptions: { attack_types: [], stances: [], spells: [] },
      }}
      weapon="Mystic staff"
      performance={performance}
    />,
  );
  expect(
    screen.getByText("Selected combat option unavailable in this result."),
  ).toBeVisible();
  expect(
    screen.queryByLabelText("Elemental weakness effect"),
  ).not.toBeInTheDocument();
});

test("a draft spell edit does not replace the evaluated weakness explanation", () => {
  const { rerender } = render(
    <CombatOptionSummary
      role={role}
      weapon="Mystic staff"
      performance={performance}
    />,
  );
  rerender(
    <CombatOptionSummary
      role={{ ...role, spell: "fire_wave" }}
      weapon="Mystic staff"
      performance={performance}
    />,
  );
  expect(screen.getByText(/Earth weakness 35% applied/)).toHaveTextContent(
    "+7 max hit",
  );
});
