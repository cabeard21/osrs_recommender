import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { EquipmentBonuses } from "../components/EquipmentBonuses";

it("shows signed bonuses, OSRS icons, percentage units and missing values", () => {
  render(
    <EquipmentBonuses bonuses={{ stab: -5, magic_damage: 12.5, prayer: 0 }} />,
  );
  const panel = screen.getByRole("region", { name: "Equipment bonuses" });
  expect(within(panel).getByText("-5")).toBeVisible();
  expect(within(panel).getByText("+12.5%")).toBeVisible();
  expect(within(panel).getAllByText("—").length).toBeGreaterThan(0);
  expect(panel.querySelectorAll('img[alt=""]').length).toBe(14);
});
it("compares candidate bonuses without inventing unknown baseline values", () => {
  render(
    <EquipmentBonuses
      bonuses={{ stab: 20, prayer: 2 }}
      baseline={{ stab: 15 }}
      title="Item bonuses only"
    />,
  );
  const panel = screen.getByRole("region", { name: "Item bonuses only" });
  expect(within(panel).getByText("(+5)")).toBeVisible();
  expect(within(panel).queryByText("(+2)")).not.toBeInTheDocument();
});
