import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { CombatOptionSummary } from "../components/CombatOptionSummary";

test("displays the selected built-in spell as a combat option", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "magic",
        attackType: "slash",
        stance: "accurate",
        spell: "fire_strike",
      }}
      weapon="Warped sceptre"
      option={{
        attack_type: "magic",
        stance: "accurate",
        spell: null,
        powered_attack: "warped",
      }}
    />,
  );
  expect(
    screen.getByLabelText("Selected combat configuration"),
  ).toHaveTextContent("Built-in spell");
});
