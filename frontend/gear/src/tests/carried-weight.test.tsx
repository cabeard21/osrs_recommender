import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { canonicalObjectives } from "../api/objectives";
import { ObjectiveScatter } from "../components/ObjectiveScatter";
import { formatMetric, metricDelta } from "../tradeoff-lab/model";

const weight = {
  id: "carried_weight_kg",
  label: "Carried gear weight",
  unit: "kg",
};
const axis = { key: weight.id, shortLabel: weight.label, ...weight };

it("keeps signed grams of precision in the objective builder and Lab comparisons", () => {
  expect(canonicalObjectives([{ kind: weight.id }])).toEqual([
    { kind: weight.id },
  ]);
  expect(formatMetric(weight.id, -3.001, axis)).toBe("-3.001 kg");
  expect(metricDelta(weight.id, 0.6, -3, axis)).toBe("+3.6 kg");
});

it.each([
  [-3, -1],
  [-3, 0.6],
])(
  "plots both weight endpoints %s and %s on the signed axis",
  (light, heavy) => {
    render(
      <ObjectiveScatter
        axes={[{ id: "dps", label: "DPS" }, weight]}
        points={[light, heavy].map((v, i) => ({
          id: String(i),
          score: i + 1,
          purchase_cost_gp: 0,
          objective_values: { [weight.id]: v },
        }))}
        selectedId="0"
        onSelect={() => {}}
      />,
    );
    const lightPoint = screen.getByRole("button", {
      name: /Select tradeoff 0,/,
    });
    const heavyPoint = screen.getByRole("button", {
      name: /Select tradeoff 1,/,
    });
    expect(lightPoint).toHaveAccessibleName(/-3 kg/);
    expect(Number(lightPoint.getAttribute("cy"))).toBeGreaterThan(
      Number(heavyPoint.getAttribute("cy")),
    );
    expect(Number(lightPoint.getAttribute("cy"))).toBeLessThanOrEqual(250);
  },
);

it("validates signed totals, exact role coverage and the heaviest role in a kit", async () => {
  const { validateCarriedWeight } = await import("../api/carriedWeight");
  const roles = {
    main: { worn_kg: -3, backpack_kg: 1, total_kg: -2 },
    utility: { worn_kg: 1, backpack_kg: 0.6, total_kg: 1.6 },
  };
  const validate = (heaviest: number, ids: string[]) =>
    validateCarriedWeight({ heaviest_kg: heaviest, roles }, ids, 1.6);
  expect(() => validate(1.6, ["main", "utility"])).not.toThrow();
  expect(() => validate(-2, ["main", "utility"])).toThrow();
  expect(() => validate(1.6, ["main"])).toThrow();
  expect(() =>
    validateCarriedWeight(
      {
        heaviest_kg: 1.6,
        roles: { ...roles, main: { ...roles.main, total_kg: -3 } },
      },
      ["main", "utility"],
      1.6,
    ),
  ).toThrow();
});
it("shows each role's worn and backpack contributions and the role setting the peak", async () => {
  const { RoleWeightBreakdown } =
    await import("../components/RoleWeightBreakdown");
  const weight = {
    heaviest_kg: 1.6,
    roles: {
      main: { worn_kg: -3, backpack_kg: 1, total_kg: -2 },
      utility: { worn_kg: 1, backpack_kg: 0.6, total_kg: 1.6 },
    },
  };
  const { rerender } = render(
    <RoleWeightBreakdown
      weight={weight}
      roleName={(id) => (id === "main" ? "Main" : "Utility")}
    />,
  );
  screen.getByText("Carried weight by role").click();
  expect(screen.getByRole("row", { name: /Main/ })).toHaveTextContent(
    "-3 kg1 kg-2 kg",
  );
  expect(
    screen.getByRole("row", { name: /Utility · Heaviest/ }),
  ).toHaveTextContent("1 kg0.6 kg1.6 kg");
  rerender(
    <RoleWeightBreakdown
      weight={{ heaviest_kg: -2, roles: { main: weight.roles.main } }}
      roleName={() => "Main"}
    />,
  );
  expect(screen.queryByText("Carried weight by role")).toBeNull();
});
