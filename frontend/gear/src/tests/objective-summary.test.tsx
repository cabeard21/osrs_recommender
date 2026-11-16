import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { JointSolutionDTO, OptimizationReply } from "../api/contracts";
import type { Objective } from "../api/objectives";
import { SecondaryPrioritySummary } from "../components/SecondaryPrioritySummary";

function reply(objectives: Objective[]): OptimizationReply {
  return {
    source: "live",
    scenario: {
      request: { objectives, roles: [{ id: "single" }], skill_overrides: {} },
    },
  } as unknown as OptimizationReply;
}

it("shows each vector objective and its native units without a scalar None label", () => {
  const result = reply([
    { kind: "defence_roll", styles: ["stab", "magic"], aggregation: "minimum" },
    { kind: "prayer_bonus" },
    { kind: "accuracy" },
  ]);
  const selected = {
    objective_values: {
      "defence_roll:minimum:stab+magic": 12345,
      prayer_bonus: 7,
      accuracy: 0.75,
    },
  } as unknown as JointSolutionDTO;
  render(<SecondaryPrioritySummary result={result} solution={selected} />);
  expect(screen.getByText(/Weakest: stab \/ magic defence/)).toHaveTextContent(
    "12.35k roll",
  );
  expect(screen.getByText(/Prayer bonus:/)).toHaveTextContent("7.00 bonus");
  expect(screen.getByText(/Accuracy:/)).toHaveTextContent("75.00% hit chance");
  expect(screen.queryByText(/None — DPS only/)).not.toBeInTheDocument();
});

it("identifies an empty vector configuration as DPS only", () => {
  render(<SecondaryPrioritySummary result={reply([])} />);
  expect(screen.getByText("DPS only.")).toBeInTheDocument();
  expect(screen.queryByText(/inventory \/ cost/)).not.toBeInTheDocument();
});

it("does not invent measurements for an unmeasured objective", () => {
  render(
    <SecondaryPrioritySummary result={reply([{ kind: "prayer_bonus" }])} />,
  );
  expect(screen.getByText(/Prayer bonus:/)).toHaveTextContent("not measured");
});
