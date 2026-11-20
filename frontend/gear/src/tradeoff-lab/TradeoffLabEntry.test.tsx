import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import TradeoffLabEntry from "./TradeoffLabEntry";
import { example, METRICS, metricValue } from "./model";
import { storeLabSnapshot } from "./snapshot";

afterEach(() => {
  history.replaceState(null, "", "/");
  localStorage.clear();
});
vi.mock("./TradeoffLab", () => ({
  default: ({ data }: { data?: typeof example }) => (
    <h1>{data?.target ?? "Saved example"}</h1>
  ),
}));
it("opens the saved example only when no live session was requested", () => {
  render(<TradeoffLabEntry />);
  expect(screen.getByRole("heading", { name: "Saved example" })).toBeVisible();
});
it("opens the current run snapshot instead of substituting the example", () => {
  const token = storeLabSnapshot({
    ...example,
    target: "Current dragon",
    sourceDescription: "Saved from current run",
    metrics: METRICS.map((m) => ({
      ...m,
      unit: m.key === "dps" ? "dps" : m.key === "defence" ? "roll" : "bonus",
    })),
    points: example.points.map((p) => ({
      ...p,
      values: Object.fromEntries(
        METRICS.map((m) => [m.key, metricValue(p, m.key)]),
      ),
    })),
  });
  history.replaceState(null, "", `/?view=tradeoff-lab&session=${token}`);
  render(<TradeoffLabEntry />);
  expect(screen.getByRole("heading", { name: "Current dragon" })).toBeVisible();
});
it("explains a missing session and offers a return link without showing another scenario", () => {
  history.replaceState(null, "", "/?view=tradeoff-lab&session=missing");
  render(<TradeoffLabEntry />);
  expect(screen.getByRole("alert")).toHaveTextContent(
    /expired|unavailable|missing|found|invalid/i,
  );
  expect(
    screen.getByRole("link", { name: "Open Gear optimizer" }),
  ).toHaveAttribute("href", "/gear");
  expect(
    screen.getByText(/Switch to the original Gear optimizer tab/),
  ).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: "Saved example" }),
  ).not.toBeInTheDocument();
});

it("rejects an explicitly empty session instead of substituting the example", () => {
  history.replaceState(null, "", "/?view=tradeoff-lab&session=");
  render(<TradeoffLabEntry />);
  expect(screen.getByRole("alert")).toHaveTextContent(/invalid/i);
  expect(
    screen.queryByRole("heading", { name: "Saved example" }),
  ).not.toBeInTheDocument();
});
