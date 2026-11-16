import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ObjectiveScatter } from "../components/ObjectiveScatter";

const axes = [
  { id: "dps", label: "DPS" },
  { id: "accuracy", label: "Accuracy", unit: "probability" },
  { id: "magic_damage_bonus", label: "Magic damage", unit: "percent" },
];
const points = [
  {
    id: "a",
    score: 4,
    objective_values: { accuracy: 0.8, magic_damage_bonus: 3.5 },
    purchase_cost_gp: 20,
  },
  {
    id: "b",
    score: 3,
    objective_values: { accuracy: 0.9, magic_damage_bonus: 10 },
    purchase_cost_gp: 50,
  },
];
it("can color by a current axis after clearing color without duplicating dimensions", () => {
  render(
    <ObjectiveScatter
      axes={axes}
      points={points}
      selectedId="a"
      onSelect={() => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText("Color represents"), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText("Color represents"), {
    target: { value: "dps" },
  });
  expect(screen.getByLabelText("Color represents")).toHaveValue("dps");
  expect(screen.getByLabelText("Horizontal axis")).toHaveValue(
    "magic_damage_bonus",
  );
  expect(screen.getByLabelText("Vertical axis")).toHaveValue("accuracy");
  fireEvent.change(screen.getByLabelText("Color represents"), {
    target: { value: "" },
  });
  fireEvent.change(screen.getByLabelText("Color represents"), {
    target: { value: "accuracy" },
  });
  expect(screen.getByLabelText("Color represents")).toHaveValue("accuracy");
  expect(screen.getByLabelText("Vertical axis")).toHaveValue("dps");
});
it("defaults to the third objective as color with formatted legend and exact tooltip units", () => {
  render(
    <ObjectiveScatter
      axes={axes}
      points={points}
      selectedId="a"
      onSelect={() => {}}
    />,
  );
  expect(screen.getByLabelText("Color represents")).toHaveValue(
    "magic_damage_bonus",
  );
  expect(
    screen.getByRole("group", {
      name: "DPS vs Accuracy, colored by Magic damage",
    }),
  ).toBeVisible();
  expect(
    screen.getByRole("img", {
      name: "Magic damage color scale: 3.50% to 10.00%",
    }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: /Select tradeoff a,/ }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByText(
      "DPS: 4.000; Accuracy: 80.00%; Magic damage: 3.50%; Purchase cost: 20 GP",
    ),
  ).toBeInTheDocument();
});
it("swaps axes without duplicate dimensions or rerunning and selects through keyboard", () => {
  const onSelect = vi.fn();
  render(
    <ObjectiveScatter
      axes={axes}
      points={points}
      selectedId="a"
      onSelect={onSelect}
    />,
  );
  fireEvent.change(screen.getByLabelText("Horizontal axis"), {
    target: { value: "magic_damage_bonus" },
  });
  expect(screen.getByLabelText("Color represents")).toHaveValue("dps");
  expect(screen.getByLabelText("Vertical axis")).toHaveValue("accuracy");
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.keyDown(
    screen.getByRole("button", { name: /Select tradeoff b,/ }),
    { key: " " },
  );
  expect(onSelect).toHaveBeenCalledWith("b");
});
it("handles two objectives, constant ranges, unavailable data, and disabled selection", () => {
  const onSelect = vi.fn();
  const { rerender } = render(
    <ObjectiveScatter
      axes={axes.slice(0, 2)}
      points={[points[0]]}
      selectedId="a"
      onSelect={onSelect}
      disabled
    />,
  );
  expect(screen.queryByLabelText("Color represents")).not.toBeInTheDocument();
  const button = screen.getByRole("button", { name: /Select tradeoff a,/ });
  expect(Number(button.getAttribute("cx"))).toBeGreaterThan(0);
  fireEvent.click(button);
  expect(onSelect).not.toHaveBeenCalled();
  rerender(
    <ObjectiveScatter
      axes={axes}
      points={[]}
      selectedId="a"
      onSelect={onSelect}
    />,
  );
  expect(
    screen.getByText("No chart values are available for these objectives."),
  ).toBeVisible();
});
