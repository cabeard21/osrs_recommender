import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { CombatOptionSummary } from "../components/CombatOptionSummary";

test("powered selection discloses charging without exposing its internal model key", () => {
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
      preparations={[
        {
          source_item_id: 28583,
          usable_item_id: 28585,
          market_item_id: 28583,
          charging_required: true,
          charges: "unknown",
          activation_reserve: [],
          message: "Charging required; actual charge availability is unknown.",
        },
      ]}
    />,
  );
  expect(
    screen.getByLabelText("Selected combat configuration"),
  ).toHaveTextContent("Built-in spell");
  expect(
    screen.getByText(
      "Charging required; actual charge availability is unknown.",
    ),
  ).toBeVisible();
});
