import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ObjectiveFrontier } from "../components/ObjectiveFrontier";
import type { OptimizationReply } from "../api/contracts";

afterEach(() => vi.unstubAllGlobals());

it("formats magic damage percentage points without multiplying by 100", async () => {
  const raw = { ...solution, objective_values: { magic_damage_bonus: 3.5 } };
  const magic = {
    ...result,
    scenario: { request: { objectives: [{ kind: "magic_damage_bonus" }] } },
    live: {
      run_id: "magic-run",
      result: {
        objective_definitions: [
          {
            id: "magic_damage_bonus",
            kind: "magic_damage_bonus",
            label: "Magic damage",
            unit: "percent",
          },
        ],
        objective_frontiers: [
          {
            id: "magic",
            swap_limit: 0,
            baseline_dps: 10,
            sampled: false,
            total_count: 1,
            points: [
              { id: "sample", solution: raw, dps_loss: 0, dps_loss_pct: 0 },
            ],
          },
        ],
      },
    },
  } as unknown as OptimizationReply;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            points: [{ id: "sample", ...raw }],
            total: 1,
            next_cursor: null,
          }),
          { status: 200 },
        ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={magic}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  expect(await screen.findByRole("cell", { name: "3.50%" })).toBeVisible();
});
const solution = {
  score: 10,
  objective_values: { prayer_bonus: 5 },
  purchase_cost_gp: 0,
  maximum_actions: 0,
};
const result = {
  scenario: { request: { objectives: [{ kind: "prayer_bonus" }] } },
  solutions: [],
  live: {
    run_id: "test-run",
    result: {
      objective_definitions: [
        {
          id: "prayer_bonus",
          kind: "prayer_bonus",
          label: "Prayer bonus",
          unit: "bonus",
        },
      ],
      objective_frontiers: [
        {
          id: "group",
          swap_limit: 0,
          baseline_dps: 10,
          sampled: true,
          total_count: 51,
          points: [{ id: "sample", solution, dps_loss: 0, dps_loss_pct: 0 }],
        },
      ],
    },
  },
} as unknown as OptimizationReply;
it("paginates all results and selects a complete unsampled solution", async () => {
  const user = userEvent.setup(),
    onSelect = vi.fn();
  const fetcher = vi.fn(
    async (input: string) =>
      new Response(
        JSON.stringify(
          input.includes("/solutions/")
            ? { solution }
            : {
                points: [
                  {
                    id: input.includes("cursor=") ? "second" : "unsampled",
                    ...solution,
                  },
                ],
                total: 51,
                next_cursor: input.includes("cursor=") ? null : "next",
              },
        ),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Select setup 1" }));
  expect(onSelect).toHaveBeenCalledWith("unsampled", solution);
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Select setup 51" });
  expect(fetcher.mock.calls.some(([url]) => url.includes("cursor=next"))).toBe(
    true,
  );
});
it("changes chart axes locally without rerunning or changing selection", async () => {
  const onSelect = vi.fn(),
    fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ points: [], total: 51, next_cursor: null }),
          { status: 200 },
        ),
    );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByRole("combobox", { name: "Horizontal axis" }), {
    target: { value: "prayer_bonus" },
  });
  expect(onSelect).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("shows a clear expired-session error without replacing existing results", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string) => new Response("{}", { status: 410 })),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "session has expired",
  );
});
it("selects chart points by keyboard and sorts the full table", async () => {
  const user = userEvent.setup(),
    onSelect = vi.fn();
  const fetcher = vi.fn(
    async (_input: string) =>
      new Response(
        JSON.stringify({
          points: [{ id: "sample", ...solution }],
          total: 1,
          next_cursor: null,
        }),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  fireEvent.keyDown(
    screen.getByRole("button", { name: /Select tradeoff sample/ }),
    { key: "Enter" },
  );
  expect(onSelect).toHaveBeenCalledWith("sample", solution);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Sort tradeoffs" }),
    "prayer_bonus",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Sort direction" }),
    "asc",
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes("direction=asc")),
    ).toBe(true),
  );
});
it("reports malformed result pages", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (_input: string) =>
        new Response(
          JSON.stringify({ points: [], total: -1, next_cursor: null }),
          { status: 200 },
        ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={() => {}}
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Invalid objective result page",
  );
});
it("reports failed detail requests without selecting a different configuration", async () => {
  const user = userEvent.setup(),
    onSelect = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("/solutions/")
        ? new Response("{}", { status: 500 })
        : new Response(
            JSON.stringify({
              points: [{ id: "unsampled", ...solution }],
              total: 1,
              next_cursor: null,
            }),
            { status: 200 },
          ),
    ),
  );
  render(
    <ObjectiveFrontier
      result={result}
      swapLimit={0}
      selectedId="sample"
      onSelect={onSelect}
    />,
  );
  await screen.findByRole("button", { name: "Select setup 1" });
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Next page" })).toBeDisabled(),
  );
  await user.click(screen.getByRole("button", { name: "Select setup 1" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load");
  expect(onSelect).not.toHaveBeenCalled();
});
