import { fireEvent, render, screen, within } from "@testing-library/react";
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
it("starts both axes at zero and positions points on the zero-based scales", () => {
  render(
    <ObjectiveScatter
      axes={axes}
      points={points}
      selectedId="a"
      onSelect={() => {}}
    />,
  );
  const chart = within(
    screen.getByRole("group", {
      name: "DPS vs Accuracy, colored by Magic damage",
    }),
  );
  expect(chart.getByText("0.000", { exact: true })).toBeVisible();
  expect(chart.getByText("0.00%", { exact: true })).toBeVisible();
  expect(
    chart.getByRole("button", { name: /Select tradeoff b,/ }),
  ).toHaveAttribute("cx", "457.5");
  const point = chart.getByRole("button", { name: /Select tradeoff a,/ });
  expect(Number(point.getAttribute("cy"))).toBeCloseTo(50);
});

it("plots zero-valued points at the origin and keeps negative values off the chart", () => {
  render(
    <ObjectiveScatter
      axes={[axes[0], axes[2]]}
      points={[
        { ...points[0], score: 0, objective_values: { magic_damage_bonus: 0 } },
        {
          ...points[1],
          score: 0,
          objective_values: { magic_damage_bonus: -1 },
        },
      ]}
      selectedId="a"
      onSelect={() => {}}
    />,
  );
  const point = screen.getByRole("button", { name: /Select tradeoff a,/ });
  expect(point).toHaveAttribute("cx", "90");
  expect(point).toHaveAttribute("cy", "250");
  expect(
    screen.queryByRole("button", { name: /Select tradeoff b,/ }),
  ).toBeNull();
  expect(screen.getByText(/negative value on either axis/)).toBeVisible();
});

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

const runningCost = {
  id: "gp_per_damage",
  label: "Running cost",
  unit: "GP/damage",
};
const costPoint = (id: string, cost: number | null) => ({
  id,
  score: 4,
  objective_values: { gp_per_damage: cost, accuracy: 0.8 },
  purchase_cost_gp: 0,
});

it("defaults to log running cost and redraws the same selected point on a linear scale", () => {
  const onSelect = vi.fn();
  render(
    <ObjectiveScatter
      axes={[axes[0], runningCost, axes[1]]}
      points={[
        costPoint("free", 0),
        costPoint("mid", 30),
        costPoint("max", 867.3212),
        costPoint("unknown", null),
      ]}
      selectedId="mid"
      onSelect={onSelect}
    />,
  );
  const scale = screen.getByLabelText("Running cost scale");
  expect(scale).toHaveValue("log");
  expect(
    screen.getByText("Running cost (GP/damage, log scale) →"),
  ).toBeVisible();
  const point = screen.getByRole("button", { name: /Select tradeoff mid,/ });
  const costFraction = () => (250 - Number(point.getAttribute("cy"))) / 225;
  expect(costFraction()).toBeCloseTo(0.5075, 4);
  expect(
    screen.getByRole("button", { name: /Select tradeoff free,/ }),
  ).toHaveAttribute("cy", "250");
  expect(
    screen.getByRole("button", { name: /Select tradeoff max,/ }),
  ).toHaveAttribute("cy", "25");
  expect(
    screen.queryByRole("button", { name: /Select tradeoff unknown,/ }),
  ).toBeNull();
  expect(screen.getByText("300", { exact: true })).toBeVisible();
  expect(screen.getByText("30", { exact: true })).toHaveAttribute(
    "y",
    String(Number(point.getAttribute("cy")) + 4),
  );

  fireEvent.change(scale, { target: { value: "linear" } });
  expect(screen.getByText("Running cost (GP/damage) →")).toBeVisible();
  expect(costFraction()).toBeCloseTo(0.03459, 4);
  expect(point).toHaveAttribute("aria-pressed", "true");
  expect(point).toHaveAccessibleName(/Running cost: 30\.0000 GP\/damage/);
  expect(onSelect).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Horizontal axis"), {
    target: { value: "gp_per_damage" },
  });
  const horizontalCostFraction = () =>
    (Number(point.getAttribute("cx")) - 90) / 490;
  expect(horizontalCostFraction()).toBeCloseTo(0.03459, 4);
  fireEvent.change(scale, { target: { value: "log" } });
  expect(horizontalCostFraction()).toBeCloseTo(0.5075, 4);
  fireEvent.change(scale, { target: { value: "linear" } });

  fireEvent.change(screen.getByLabelText("Color represents"), {
    target: { value: "gp_per_damage" },
  });
  expect(screen.getByLabelText("Running cost scale")).toHaveValue("linear");
  const linearLegend = screen.getByRole("img", {
    name: /Running cost .*color scale/,
  });
  const linearFill = point.getAttribute("fill");
  expect(within(linearLegend).getByText("0", { exact: true })).toBeVisible();
  const positionBefore = [point.getAttribute("cx"), point.getAttribute("cy")];
  fireEvent.change(scale, { target: { value: "log" } });
  const logLegend = screen.getByRole("img", {
    name: /Running cost .*log scale.*color scale/,
  });
  const legendX = (tick: string) =>
    Number(
      within(logLegend).getByText(tick, { exact: true }).getAttribute("x"),
    );
  expect(
    (legendX("30") - legendX("0")) / (legendX("867") - legendX("0")),
  ).toBeCloseTo(0.5075, 4);
  expect(point.getAttribute("fill")).not.toBe(linearFill);
  expect([point.getAttribute("cx"), point.getAttribute("cy")]).toEqual(
    positionBefore,
  );
  expect(point).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByRole("button", { name: /Select tradeoff unknown,/ }),
  ).toHaveAttribute("fill", "#7bd0ff");
  fireEvent.change(scale, { target: { value: "linear" } });
  fireEvent.change(screen.getByLabelText("Vertical axis"), {
    target: { value: "gp_per_damage" },
  });
  expect(screen.getByLabelText("Running cost scale")).toHaveValue("linear");
  expect(costFraction()).toBeCloseTo(0.03459, 4);
});

it("renders readable log ticks for small and all-zero running costs", () => {
  const { rerender } = render(
    <ObjectiveScatter
      axes={[axes[0], runningCost]}
      points={[costPoint("free", 0), costPoint("low", 0.02)]}
      selectedId="free"
      onSelect={() => {}}
    />,
  );
  expect(screen.getByText("0.02", { exact: true })).toBeVisible();
  expect(screen.getByText("0.01", { exact: true })).toBeVisible();
  rerender(
    <ObjectiveScatter
      axes={[axes[0], runningCost]}
      points={[costPoint("free", 0)]}
      selectedId="free"
      onSelect={() => {}}
    />,
  );
  expect(screen.getByText("0", { exact: true })).toBeVisible();
  expect(screen.queryByText("0.02", { exact: true })).toBeNull();
  expect(
    screen.getByRole("button", { name: /Select tradeoff free,/ }),
  ).toHaveAttribute("cy", "250");
  fireEvent.change(screen.getByLabelText("Running cost scale"), {
    target: { value: "linear" },
  });
  expect(screen.getByText("0", { exact: true })).toBeVisible();
  expect(
    screen.getByRole("button", { name: /Select tradeoff free,/ }),
  ).toHaveAttribute("cy", "250");
});
