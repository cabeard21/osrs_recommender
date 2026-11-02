import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DisciplineTabs } from "../components/DisciplineTabs";
it("selects searched disciplines and supports arrow navigation", async () => {
  const select = vi.fn();
  render(
    <DisciplineTabs
      disciplines={["melee", "magic"]}
      active="overall"
      onSelect={select}
    />,
  );
  expect(screen.queryByRole("tab", { name: "Ranged" })).toBeNull();
  const overall = screen.getByRole("tab", { name: "Auto overall" });
  expect(overall).toHaveAttribute("aria-selected", "true");
  overall.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(select).toHaveBeenCalledWith("melee");
  await userEvent.click(screen.getByRole("tab", { name: "Magic" }));
  expect(select).toHaveBeenCalledWith("magic");
});
it("wraps and supports Home and End while ignoring unrelated keys", async () => {
  const select = vi.fn();
  render(
    <DisciplineTabs
      disciplines={["melee", "magic"]}
      active="magic"
      onSelect={select}
    />,
  );
  screen.getByRole("tab", { name: "Magic" }).focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(select).toHaveBeenLastCalledWith("overall");
  await userEvent.keyboard("{ArrowLeft}");
  expect(select).toHaveBeenLastCalledWith("magic");
  await userEvent.keyboard("{Home}");
  expect(select).toHaveBeenLastCalledWith("overall");
  await userEvent.keyboard("{End}");
  expect(select).toHaveBeenLastCalledWith("magic");
  select.mockClear();
  await userEvent.keyboard("x");
  expect(select).not.toHaveBeenCalled();
});
