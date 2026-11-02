import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { AmmoComparison } from "../components/AmmoComparison";

afterEach(() => vi.unstubAllGlobals());
const points = [
  {
    ammo_id: 1,
    cape_id: 10499,
    ammo_name: "Rune arrow",
    cape_name: "Ava's accumulator",
    dps: 5,
    recovery_rate: 0.72,
    arrows_lost_per_hour: 560,
    gp_per_hour: 28000,
    gp_per_damage: 1.55,
    frontier: true,
    current: true,
    reasons: [],
    price: { layer: "cached" },
  },
  {
    ammo_id: 2,
    cape_id: null,
    ammo_name: "Bronze arrow",
    cape_name: "No cape",
    dps: 3,
    recovery_rate: 0,
    arrows_lost_per_hour: 2000,
    gp_per_hour: null,
    gp_per_damage: null,
    frontier: false,
    current: false,
    reasons: ["No price available"],
    price: null,
  },
];
const props = {
  scenario: {},
  loadout: { weapon: 861 },
  identity: { snapshot_id: "s", catalog_version: "c", price_revision: "p" },
};
it("explains missing prices and unreviewed recovery instead of generic unknown costs", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...props.identity,
        points: [
          { ...points[1], dps_loss_pct: 10, price: { amount_gp: null } },
          {
            ...points[0],
            recovery_rate: null,
            arrows_lost_per_hour: null,
            gp_per_hour: null,
            gp_per_damage: null,
            reasons: ["Ammo recovery for this cape has not been reviewed."],
          },
        ],
      }),
    }),
  );
  render(<AmmoComparison {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "Compare arrows" }));
  await screen.findByRole("table");
  expect(screen.getByRole("cell", { name: "10%" })).toBeInTheDocument();
  expect(screen.getAllByText("Price unavailable")).toHaveLength(2);
  expect(screen.getAllByText("Recovery not modeled")).toHaveLength(4);
  expect(screen.queryByText("Unknown")).not.toBeInTheDocument();
});
it("shows current setup, unknown costs and linked selection without changing equipment", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...props.identity, points }),
    }),
  );
  render(<AmmoComparison {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "Compare arrows" }));
  expect(
    await screen.findByRole("table", { name: "Arrow running cost comparison" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/Current setup/)).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Preview Bronze arrow / No cape" }),
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Preview: Bronze arrow / No cape",
  );
  expect(screen.getByText("No price available")).toBeInTheDocument();
});
it("hides old results when the source becomes outdated", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...props.identity, points }),
    }),
  );
  const view = render(<AmmoComparison {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "Compare arrows" }));
  await screen.findByRole("table");
  view.rerender(<AmmoComparison {...props} outdated />);
  await waitFor(() =>
    expect(screen.queryByRole("table")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: "Compare arrows" })).toBeDisabled();
});

it("explains unsupported comparisons and refuses changed price identities", async () => {
  const transport = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...props.identity,
        points: [],
        limitations: ["This bow is unsupported."],
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...props.identity,
        price_revision: "changed",
        points,
      }),
    });
  vi.stubGlobal("fetch", transport);
  render(<AmmoComparison {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "Compare arrows" }));
  expect(
    await screen.findByText("This bow is unsupported."),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Compare arrows" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Comparison sources changed",
  );
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("computes DPS loss against the actual maximum below one DPS and selects through plot", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...props.identity,
        points: [{ ...points[0], dps: 0.5 }],
      }),
    }),
  );
  render(<AmmoComparison {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "Compare arrows" }));
  await screen.findByRole("table");
  expect(screen.getByRole("cell", { name: "0%" })).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Plot Rune arrow / Ava's accumulator" }),
  );
  expect(screen.getByRole("status")).toHaveTextContent("Preview: Rune arrow");
});
